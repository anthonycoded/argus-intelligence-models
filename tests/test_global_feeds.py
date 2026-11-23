from copy import deepcopy
import ipaddress
import socket
import threading

import pytest

from src.global_feeds import _PinnedHTTPSConnection, collect, fetch_feed, load_config, parse_feed, public_addresses, publication_timestamp, validate_feed
from src.global_io import encoded


def feed(country="KE", region="Africa", host="kenya.example.org"):
    return {"id": country.lower(), "enabled": True, "verification": "operator_verified", "url": f"https://{host}/rss",
            "article_hosts": [host], "publisher": f"Synthetic {country} publisher", "publisher_country": country,
            "source_region": region, "language": "en"}


def xml(host="kenya.example.org"):
    return f'<rss><channel><item><title>Global developments</title><link>https://{host}/story</link><description>DO NOT IMPORT BODY</description></item></channel></rss>'.encode()


def test_multicountry_config_opt_in_and_offline_collection(tmp_path):
    config = {"schema_version": "aic-global-feeds-v1", "feeds": [feed(), feed("BR", "South America", "brazil.example.org")]}
    path = tmp_path / "config.json"
    path.write_bytes(encoded(config))
    result = collect(path, tmp_path / "poll", fetcher=lambda f: xml(f["article_hosts"][0]), collected_at="2026-11-22T00:00:00Z")
    assert result["records"] == 2
    with pytest.raises(FileExistsError):
        collect(path, tmp_path / "poll", fetcher=lambda _: pytest.fail("Overwrite fetched again"))


def test_default_sources_are_explicitly_disabled():
    assert all(not f["enabled"] for f in load_config("configs/global_feeds.json")["feeds"])


def test_unverified_feed_cannot_be_enabled():
    entry = feed()
    entry["verification"] = "unverified"
    with pytest.raises(ValueError):
        validate_feed(entry)


def test_only_allowed_publisher_hosts_and_metadata_are_emitted():
    rows = parse_feed(xml(), feed(), "2026-11-22T00:00:00Z")
    assert rows[0]["source_region"] == "Africa"
    assert rows[0]["metadata_basis"] == "source_config_not_event_geography"
    assert "article_text" not in rows[0] and "DO NOT IMPORT" not in str(rows)
    assert not parse_feed(xml("kenya.example.org.evil.test"), feed(), "2026-11-22T00:00:00Z")


@pytest.mark.parametrize("url", ["http://kenya.example.org/rss", "https://u:p@kenya.example.org/rss", "https://127.0.0.1/rss",
                                 "https://kenya.example.org:444/rss", "https://kenya.example.org/rss#fragment", "https://kenya.example.org/\\x"])
def test_feed_url_safety(url):
    entry = feed()
    entry["url"] = url
    with pytest.raises(ValueError):
        validate_feed(entry)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "fc00::1", "::ffff:127.0.0.1", "224.0.0.1", "0.0.0.0"])
def test_private_and_special_dns_answers_rejected(address):
    def resolver(*args, **kwargs):
        return [(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
    with pytest.raises(ValueError, match="SSRF"):
        public_addresses("feed.example.org", resolver)


def test_mixed_public_private_dns_is_rejected():
    def resolver(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ("8.8.8.8", "127.0.0.1")]
    with pytest.raises(ValueError, match="mixed"):
        public_addresses("feed.example.org", resolver)


@pytest.mark.parametrize("failure", ["redirect", "mime", "compression", "declared_size", "actual_size"])
def test_transport_rejects_unsafe_responses_without_redirects_or_network(failure):
    class Response:
        status = 302 if failure == "redirect" else 200
        def getheader(self, name, default=None):
            return {"Content-Type": "text/html" if failure == "mime" else "application/rss+xml",
                    "Content-Encoding": "gzip" if failure == "compression" else "identity",
                    "Content-Length": str(3 * 1024 * 1024) if failure == "declared_size" else None}.get(name, default)
        def read(self, limit):
            return b"x" * limit if failure == "actual_size" else xml()
    class Connection:
        sock = None
        def __init__(self, host, addresses):
            assert host == "kenya.example.org" and addresses[0][4][0] == "8.8.8.8"
        def request(self, *args, **kwargs):
            pass
        def getresponse(self):
            return Response()
        def close(self):
            pass
    resolver = lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    with pytest.raises(ValueError):
        fetch_feed(feed(), resolver, Connection)


def test_utf16_entities_rejected_in_generic_collector():
    raw = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE rss [<!ENTITY x "unsafe">]><rss><channel/></rss>'.encode("utf-16")
    with pytest.raises(ValueError, match="DOCTYPE"):
        parse_feed(raw, feed(), "2026-11-22T00:00:00Z")


def test_connection_uses_validated_address_without_resolving_again_and_preserves_tls_hostname(monkeypatch):
    calls = []
    class Sock:
        def settimeout(self, value):
            pass
        def connect(self, address):
            calls.append(("connect", address))
        def close(self):
            pass
    class Context:
        def wrap_socket(self, sock, server_hostname):
            calls.append(("tls", server_hostname))
            return sock
    monkeypatch.setattr(socket, "socket", lambda *args: Sock())
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: pytest.fail("DNS rebinding window: resolved twice"))
    connection = _PinnedHTTPSConnection("kenya.example.org", [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
    connection._context = Context()
    connection.connect()
    assert calls == [("connect", ("8.8.8.8", 443)), ("tls", "kenya.example.org")]


def test_deadline_prevents_new_connection_attempts(monkeypatch):
    connection = _PinnedHTTPSConnection("kenya.example.org", [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
    connection._expired = threading.Event()
    connection._expired.set()
    monkeypatch.setattr(socket, "socket", lambda *args: pytest.fail("Expired collector opened a new socket"))
    with pytest.raises(ValueError, match="deadline"):
        connection.connect()


@pytest.mark.parametrize("raw,expected", [("Fri, 20 Nov 2026 12:00:00 GMT", "2026-11-20T12:00:00+00:00"),
                                         ("2026-11-20T07:00:00-05:00", "2026-11-20T12:00:00+00:00"),
                                         ("2026-11-20", None), ("not a date", None)])
def test_publication_normalization_does_not_guess_timezones(raw, expected):
    assert publication_timestamp(raw) == expected


def test_updated_time_is_not_promoted_to_publication_time():
    raw = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Update only</title><link href="https://kenya.example.org/story"/><updated>2026-11-20T00:00:00Z</updated></entry></feed>'
    row = parse_feed(raw, feed(), "2026-11-22T00:00:00Z")[0]
    assert row["published_at"] is None and row["published_at_raw"] is None
    assert row["updated_at_raw"] == "2026-11-20T00:00:00Z"
