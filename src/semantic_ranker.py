"""Local, review-only semantic ranking of AIC-1 discovery JSONL records.

No article fetching, source changes, approval, labeling, or training rights mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

DEFAULT_MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_ROWS = 10000
MAX_TITLE_LEN = 2000
MAX_VECTOR_SIZE = 4096


def topic_query(spec: dict) -> str:
    required = ('title', 'mandatory_subject', 'geographic_scope', 'material_connection')
    if any(not isinstance(spec.get(k), str) or not spec[k].strip() for k in required):
        raise ValueError('Topic specification lacks required fields')
    return ' | '.join(spec[k].strip() for k in required)


def read_discoveries(paths: list[Path]) -> tuple[list[dict], dict]:
    records, seen = [], set()
    stats = {'input': 0, 'duplicates': 0, 'missing_title': 0}
    for path in paths:
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError(f'Input too large: {path}')
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if not line.strip():
                continue
            stats['input'] += 1
            if stats['input'] > MAX_ROWS:
                raise ValueError('Too many discovery records')
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('Each JSONL line must be an object')
            sid = row.get('source_id')
            if not isinstance(sid, str) or not sid.strip():
                raise ValueError('Discovery missing source_id')
            if sid in seen:
                stats['duplicates'] += 1
                continue
            seen.add(sid)
            title = row.get('article_title')
            if not isinstance(title, str) or not title.strip():
                stats['missing_title'] += 1
                continue
            if len(title) > MAX_TITLE_LEN:
                raise ValueError('Article title too long')
            records.append(row)
    return records, stats


def _atomic_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f'Refusing to overwrite: {path}')
    fd, tmp = tempfile.mkstemp(prefix='.aic1rank-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        # Avoid overwriting an output created by another process.
        with path.open('xb') as f:
            f.write(Path(tmp).read_bytes())
    finally:
        Path(tmp).unlink(missing_ok=True)


def _cache_key(model: str, text: str) -> str:
    return hashlib.sha256(json.dumps([model, text], ensure_ascii=False).encode('utf-8')).hexdigest()


def _valid_vector(vec) -> bool:
    return (isinstance(vec, list) and 1 <= len(vec) <= MAX_VECTOR_SIZE and
            all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in vec) and
            sum(float(v) ** 2 for v in vec) > 0)


def _unit(vec: list[float]) -> list[float]:
    size = math.sqrt(sum(v*v for v in vec))
    return [v/size for v in vec]


def _encode_with_cache(texts: list[str], model_name: str, cache_dir: Path, encoder) -> tuple[list[list[float]], int]:
    results: list[list[float] | None] = [None] * len(texts)
    missing: dict[str, list[int]] = {}
    cache_hits = 0
    for i, t in enumerate(texts):
        key = _cache_key(model_name, t)
        cached = cache_dir / f'{key}.json'
        if cached.exists():
            try:
                payload = json.loads(cached.read_text(encoding='utf-8'))
                vec = payload['vector']
                if not _valid_vector(vec):
                    raise ValueError('Invalid cached vector')
                results[i] = _unit([float(v) for v in vec])
                cache_hits += 1
                continue
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError(f'Corrupt embedding cache: {cached}') from exc
        missing.setdefault(t, []).append(i)
    if missing:
        new_texts = list(missing)
        vectors = encoder(new_texts)
        if len(vectors) != len(new_texts):
            raise ValueError('Embedding count mismatch')
        for t, raw in zip(new_texts, vectors):
            v = raw.tolist() if hasattr(raw, 'tolist') else list(raw)
            if not _valid_vector(v):
                raise ValueError('Invalid model embedding')
            norm = _unit([float(x) for x in v])
            for i in missing[t]:
                results[i] = norm
            dest = cache_dir / f'{_cache_key(model_name, t)}.json'
            _atomic_new(dest, json.dumps({'model': model_name, 'vector': norm}, separators=(',', ':')).encode())
    ready = [r for r in results if r is not None]
    if len(ready) != len(texts) or len({len(v) for v in ready}) != 1:
        raise ValueError('Missing or inconsistent embedding dimensions')
    return ready, cache_hits


def rank(input_paths: list[Path], topic: Path, output: Path, cache_dir: Path,
         model_name: str = DEFAULT_MODEL, *, encoder=None) -> dict:
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite: {output}')
    spec = json.loads(topic.read_text(encoding='utf-8-sig'))
    query = topic_query(spec)
    records, stats = read_discoveries(input_paths)
    if not records:
        raise ValueError('No eligible titled discovery records')
    if encoder is None:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name, device='cpu')
        encoder = lambda texts: model.encode(texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    vectors, hits = _encode_with_cache([query] + [r['article_title'].strip() for r in records], model_name, cache_dir, encoder)
    query_vec = vectors[0]
    ranked = []
    for row, v in zip(records, vectors[1:]):
        score = sum(a*b for a,b in zip(query_vec, v))
        result = dict(row)
        result['semantic_score'] = round(max(-1.0, min(1.0, score)), 6)
        result['embedding_model'] = model_name
        result['ranking_basis'] = 'title_only'
        ranked.append(result)
    ranked.sort(key=lambda r: (-r['semantic_score'], r['source_id']))
    for idx, r in enumerate(ranked, 1):
        r['semantic_rank'] = idx
    _atomic_new(output, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in ranked).encode('utf-8'))
    return {'read': stats['input'], 'ranked': len(ranked), 'duplicates': stats['duplicates'],
            'missing_title': stats['missing_title'], 'cache_hits': hits,
            'new_embeddings': len(vectors)-hits, 'output': str(output),
            'model': model_name, 'ranking_basis': 'title_only',
            'top': [{'title': r['article_title'], 'score': r['semantic_score']} for r in ranked[:5]]}


def main() -> None:
    parser = argparse.ArgumentParser(description='Offline semantic candidate ranking; review-only, titles only')
    parser.add_argument('--inputs', nargs='+', required=True, type=Path)
    parser.add_argument('--topic', default='topics/taiwan_military_v2.json', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cache-dir', default='data/embedding_cache', type=Path)
    parser.add_argument('--model', default=DEFAULT_MODEL)
    args = parser.parse_args()
    print(json.dumps(rank(args.inputs, args.topic, args.output, args.cache_dir, args.model), indent=2))


if __name__ == '__main__':
    main()
