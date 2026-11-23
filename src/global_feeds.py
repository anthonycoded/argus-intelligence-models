"""Opt-in worldwide RSS/Atom metadata collection with DNS-pinned HTTPS transport."""
import argparse
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

from .candidate_import import canonical_source
from .content_reference import validate_source_url
from .global_annotation_schema import COUNTRY_CODES
from .global_io import digest, document_hash, encoded, keys, now, publish_directory, read_object, string, timestamp
from .government_sources import child_text, entry_link, local_name
from .safe_xml import parse_xml

MAX_BYTES = 2 * 1024 * 1024
REGIONS = {"Africa", "Asia", "Europe", "North America", "South America", "Oceania", "Antarctica", "unknown"}
FEED_FIELDS = {"id", "enabled", "verification", "url", "article_hosts", "publisher", "publisher_country", "source_region", "language"}


def publication_timestamp(raw):
    """Normalize explicit publisher timestamps only; never guess missing timezones."""
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            value = parsedate_to_datetime(raw)
        except (ValueError, TypeError, OverflowError):
            return None
    return value.astimezone(timezone.utc).isoformat() if value.tzinfo is not None else None


def validate_feed(feed):
    keys(feed, FEED_FIELDS, "global feed")
    if not isinstance(feed["id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", feed["id"]):
        raise ValueError("Invalid feed ID")
    if type(feed["enabled"]) is not bool or feed["verification"] not in {"unverified", "local_archive", "operator_verified"}:
        raise ValueError("Explicit feed opt-in and verification metadata required")
    if feed["enabled"] and feed["verification"] == "unverified":
        raise ValueError("Unverified feeds cannot be enabled")
    validate_source_url(feed["url"], "manual")
    if not isinstance(feed["article_hosts"], list) or not 1 <= len(feed["article_hosts"]) <= 20:
        raise ValueError("Explicit exact publisher article hosts required")
    for host in feed["article_hosts"]:
        string(host, "article host")
        validate_source_url("https://" + host + "/", "manual")
        if host != urlsplit("https://" + host).hostname:
            raise ValueError("Article allowlist entries must be exact lowercase hostnames")
    string(feed["publisher"], "publisher")
    if feed["publisher_country"] not in COUNTRY_CODES or feed["source_region"] not in REGIONS:
        raise ValueError("Unknown publisher country/source region")
    if not isinstance(feed["language"], str) or not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]+)*", feed["language"]):
        raise ValueError("Explicit language metadata required")
    return feed


def load_config(path):
    obj = read_object(path)
    keys(obj, {"schema_version", "feeds"}, "feed config")
    if obj["schema_version"] != "aic-global-feeds-v1" or not isinstance(obj["feeds"], list) or not 1 <= len(obj["feeds"]) <= 100:
        raise ValueError("Unsupported feed config")
    for feed in obj["feeds"]:
        validate_feed(feed)
    if len({f["id"] for f in obj["feeds"]}) != len(obj["feeds"]):
        raise ValueError("Duplicate feed IDs")
    return obj


def public_addresses(host, resolver=socket.getaddrinfo):
    addresses = resolver(host, 443, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("No DNS addresses")
    for _, _, _, _, sockaddr in addresses:
        ip = ipaddress.ip_address(sockaddr[0])
        if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError("SSRF: nonpublic/mixed DNS answers rejected")
    return addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, addresses):
        super().__init__(host, timeout=12, context=ssl.create_default_context())
        self.addresses = addresses

    def connect(self):
        # Never resolve again at connect time; preserve original TLS SNI/Host.
        for family, socktype, proto, _, sockaddr in self.addresses[:4]:
            if getattr(self, "_expired", None) is not None and self._expired.is_set():
                raise ValueError("Feed deadline expired")
            sock = socket.socket(family, socktype, proto)
            self.sock = sock
            try:
                remaining = getattr(self, "_deadline", time.monotonic() + self.timeout) - time.monotonic()
                if remaining <= 0:
                    raise ValueError("Feed deadline expired")
                sock.settimeout(min(self.timeout, remaining))
                sock.connect(sockaddr)
                self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
                if getattr(self, "_expired", None) is not None and self._expired.is_set():
                    self.close()
                    raise ValueError("Feed deadline expired")
                return
            except OSError:
                sock.close()
        raise ValueError("Pinned HTTPS connection failed")


def fetch_feed(feed, resolver=socket.getaddrinfo, connection_factory=_PinnedHTTPSConnection):
    validate_feed(feed)
    if not feed["enabled"]:
        raise ValueError("Feed is not enabled")
    parts = urlsplit(feed["url"])
    addresses = public_addresses(parts.hostname, resolver)
    connection = connection_factory(parts.hostname, addresses)
    connection._expired = threading.Event()
    connection._deadline = time.monotonic() + 30

    def abort():
        connection._expired.set()
        sock = connection.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        connection.close()

    # A socket timeout alone does not bound a slow trickle of headers/body.
    watchdog = threading.Timer(30, abort)
    watchdog.daemon = True
    watchdog.start()
    try:
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        connection.request("GET", target, headers={"User-Agent": "AIC1GlobalDiscovery/1", "Accept-Encoding": "identity"})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("Non-200 feed response; redirects are never followed")
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise ValueError("Compressed feed responses are unsupported")
        mime = response.getheader("Content-Type", "").split(";")[0].strip().lower()
        if mime not in {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}:
            raise ValueError("Feed response must have an XML content type")
        length = response.getheader("Content-Length")
        if length is not None and not 0 <= int(length) <= MAX_BYTES:
            raise ValueError("Feed response exceeds size limit")
        raw = response.read(MAX_BYTES + 1)
        if connection._expired.is_set():
            raise ValueError("Feed deadline expired")
        if len(raw) > MAX_BYTES:
            raise ValueError("Feed response exceeds size limit")
        return raw
    finally:
        watchdog.cancel()
        connection.close()


def parse_feed(raw, feed, collected_at):
    validate_feed(feed)
    timestamp(collected_at, "collected_at")
    root = parse_xml(raw, MAX_BYTES)
    if local_name(root.tag) == "rss":
        channel = next((c for c in root if local_name(c.tag) == "channel"), None)
        if channel is None:
            raise ValueError("RSS channel missing")
        entries = [c for c in channel if local_name(c.tag) == "item"]
    elif local_name(root.tag) == "feed":
        entries = [c for c in root if local_name(c.tag) == "entry"]
    else:
        raise ValueError("Unsupported RSS/Atom root")
    if len(entries) > 500:
        raise ValueError("Feed exceeds 500 entries")
    rows, seen = [], set()
    for entry in entries:
        title, url = child_text(entry, "title"), entry_link(entry)
        if not title or not url:
            continue
        try:
            validate_source_url(url, "manual")
        except ValueError:
            continue
        if urlsplit(url).hostname not in feed["article_hosts"]:
            continue
        canonical = canonical_source(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        published = child_text(entry, "pubdate") or child_text(entry, "published") or None
        rows.append({"discovery_id": digest(canonical.encode())[:20], "source_id": canonical,
                     "article_title": title, "published_at_raw": published, "published_at": publication_timestamp(published),
                     "updated_at_raw": child_text(entry, "updated") or None,
                     "collected_at": collected_at, "publisher": feed["publisher"], "publisher_country": feed["publisher_country"],
                     "source_region": feed["source_region"], "language": feed["language"], "metadata_basis": "source_config_not_event_geography",
                     "feed_id": feed["id"], "content_type": "metadata_only", "review_status": "discovered_unreviewed"})
    return rows


def collect(config_path, output, fetcher=fetch_feed, collected_at=None, feed_files=None):
    config = load_config(config_path)
    enabled = [f for f in config["feeds"] if f["enabled"]]
    if not enabled:
        raise ValueError("No explicitly enabled feeds")
    if Path(output).exists():
        raise FileExistsError(output)
    stamp = collected_at or now()
    files, rows = {}, []
    for feed in enabled:
        if feed_files is not None:
            path = Path(feed_files[feed["id"]])
            if path.stat().st_size > MAX_BYTES:
                raise ValueError("Saved feed exceeds size limit")
            raw = path.read_bytes()
        else:
            raw = fetcher(feed)
        rows.extend(parse_feed(raw, feed, stamp))
        files[f"raw-{feed['id']}.xml"] = raw
    payload = b"".join(encoded(row) + b"\n" for row in rows)
    manifest = {"schema_version": "aic-global-feed-poll-v1", "config": config, "config_sha256": document_hash(config),
                "collected_at": stamp, "raw_sha256": {k: digest(v) for k, v in files.items()},
                "records": len(rows), "discovery_sha256": digest(payload)}
    files.update({"discovery.jsonl": payload, "manifest.json": encoded(manifest)})
    publish_directory(output, files)
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Opt-in global feed metadata; no article-body retrieval")
    parser.add_argument("--config", type=Path, default=Path("configs/global_feeds.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--feed-files", type=Path, help="Optional JSON map of feed IDs to saved XML paths; disables network")
    args = parser.parse_args()
    result = collect(args.config, args.output, feed_files=read_object(args.feed_files) if args.feed_files else None)
    print(encoded({"records": result["records"]}).decode())


if __name__ == "__main__":
    main()
