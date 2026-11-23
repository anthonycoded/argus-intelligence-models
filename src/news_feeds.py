"""Metadata-only, publisher-allowlisted news feed discovery for AIC-1.

Separate from official government collector. No article-body retrieval, rights
clearance, relevance labeling, or operational database writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import ssl
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, HTTPSHandler, HTTPRedirectHandler, build_opener

from .candidate_import import canonical_source
from .feed_automation import priority
from .safe_xml import parse_xml

MAX_BYTES = 2 * 1024 * 1024
ROOT = 'defensenews.com'
FEED_PATH = '/global/asia-pacific/feed/'

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def permitted_url(url: str, *, feed: bool = False) -> bool:
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 or c == '\\' for c in url):
        return False
    try:
        p = urlsplit(url)
        host = (p.hostname or '').lower()
        return (p.scheme == 'https' and host in (ROOT, 'www.' + ROOT)
                and p.username is None and p.password is None
                and p.port in (None, 443) and not p.fragment
                and (not feed or p.path == FEED_PATH))
    except ValueError:
        return False

def fetch_feed(url: str) -> bytes:
    if not permitted_url(url, feed=True):
        raise ValueError('Unapproved publisher feed URL')
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    req = Request(url, headers={'User-Agent': 'AIC1NewsDiscovery/0.1', 'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml', 'Accept-Encoding': 'identity'})
    try:
        with opener.open(req, timeout=12) as res:
            if res.status != 200:
                raise ValueError(f'HTTP {res.status}')
            size = res.headers.get('Content-Length')
            if size and int(size) > MAX_BYTES:
                raise ValueError('Feed too large')
            raw = res.read(MAX_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, socket.timeout) as exc:
        raise ValueError(f'Feed request failed: {type(exc).__name__}') from exc
    if len(raw) > MAX_BYTES:
        raise ValueError('Feed too large')
    return raw

def localname(tag):
    return tag.rsplit('}', 1)[-1].lower()

def text_of(entry, key):
    for child in entry:
        if localname(child.tag) == key:
            return ' '.join(''.join(child.itertext()).split())
    return ''

def parse(raw: bytes, collected_at: str) -> tuple[list[dict], dict]:
    root = parse_xml(raw, MAX_BYTES)
    top = localname(root.tag)
    if top == 'rss':
        channel = next((x for x in root if localname(x.tag) == 'channel'), None)
        if channel is None:
            raise ValueError('Missing RSS channel')
        entries = [e for e in channel if localname(e.tag) == 'item']
    elif top == 'feed':
        entries = [e for e in root if localname(e.tag) == 'entry']
    else:
        raise ValueError('Not RSS or Atom')
    if len(entries) > 500:
        raise ValueError('Too many entries')
    results, within, stats = [], set(), {'total': len(entries), 'invalid': 0, 'unsupported_host': 0, 'duplicate': 0}
    for e in entries:
        title = text_of(e, 'title')
        url = ''
        for link in e:
            if localname(link.tag) == 'link':
                if link.attrib.get('href') and link.attrib.get('rel', 'alternate') == 'alternate':
                    url = link.attrib['href'].strip()
                    break
                if not link.attrib.get('href') and (link.text or '').strip():
                    url = link.text.strip()
                    break
        if not title or not url:
            stats['invalid'] += 1
            continue
        if not permitted_url(url):
            stats['unsupported_host'] += 1
            continue
        canonical = canonical_source(url)
        if canonical in within:
            stats['duplicate'] += 1
            continue
        within.add(canonical)
        rank, terms = priority(title)
        aid = hashlib.sha256(canonical.encode()).hexdigest()[:20]
        results.append({'discovery_id': aid, 'source_id': canonical,
                        'article_title': title,
                        'published_at_raw': text_of(e, 'pubdate') or text_of(e, 'updated') or text_of(e, 'published') or None,
                        'collected_at': collected_at, 'publisher': 'Defense News',
                        'content_type': 'metadata_only', 'review_status': 'discovered_unreviewed',
                        'priority': rank, 'matched_terms': terms})
    return results, stats

def atomic_write(path: Path, raw: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.aic1-news-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def collect(*, url: str, output: Path, state: Path, fetcher=fetch_feed, now: str | None = None):
    if not permitted_url(url, feed=True):
        raise ValueError('Unapproved feed URL')
    if output.exists():
        raise FileExistsError('Discovery output already exists')
    seen = set()
    if state.exists():
        if state.stat().st_size > 8 * 1024 * 1024:
            raise ValueError('State too large')
        data = json.loads(state.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('seen'), list):
            raise ValueError('Invalid state')
        if len(data['seen']) > 100000 or any(not isinstance(x, str) or not re.fullmatch('[0-9a-f]{20}', x) for x in data['seen']):
            raise ValueError('Invalid state IDs')
        seen = set(data['seen'])
    stamp = now or datetime.now(timezone.utc).isoformat()
    if datetime.fromisoformat(stamp.replace('Z', '+00:00')).tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    raw = fetcher(url)
    rows, counts = parse(raw, stamp)
    new = [r for r in rows if r['discovery_id'] not in seen]
    if len(seen) + len(new) > 100000:
        raise ValueError('State capacity exceeded')
    # Keep raw feed for diagnostics; never overwrite historic raw payloads.
    digest = hashlib.sha256(raw).hexdigest()[:16]
    feed_copy = output.parent / 'raw_news_feeds' / f'defensenews-{digest}.xml'
    if not feed_copy.exists():
        atomic_write(feed_copy, raw)
    atomic_write(output, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in new).encode())
    atomic_write(state, json.dumps({'schema_version': 1, 'seen': sorted(seen | {r['discovery_id'] for r in new})}, indent=2).encode())
    return {'feed': url, 'total': counts['total'], 'accepted': len(rows), 'new': len(new),
            'previously_seen': len(rows) - len(new), 'high_priority': sum(r['priority'] == 'high' for r in new),
            'unsupported_host': counts['unsupported_host'], 'invalid': counts['invalid'],
            'duplicate_in_feed': counts['duplicate'], 'output': str(output), 'state': str(state)}

def main():
    ap = argparse.ArgumentParser(description='Defense News Asia-Pacific metadata-only incremental RSS discovery')
    ap.add_argument('--url', default='https://www.defensenews.com/global/asia-pacific/feed/')
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--state', type=Path, default=Path('data/discovery/defensenews_seen.json'))
    args = ap.parse_args()
    print(json.dumps(collect(url=args.url, output=args.output, state=args.state), indent=2))

if __name__ == '__main__':
    main()
