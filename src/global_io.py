"""Strict local artifact I/O for the separate global annotation store."""
import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def encoded(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def document_hash(obj):
    return digest(encoded(obj))


def _pairs(items):
    obj = {}
    for key, value in items:
        if key in obj:
            raise ValueError(f"Duplicate JSON key: {key}")
        obj[key] = value
    return obj


def parse_json(raw):
    def invalid(value):
        raise ValueError(f"Nonfinite JSON value: {value}")
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid)


def read_object(path):
    path = Path(path)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("JSON artifact exceeds 8 MiB")
    obj = parse_json(path.read_text(encoding="utf-8-sig"))
    if not isinstance(obj, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return obj


def keys(obj, expected, name):
    if not isinstance(obj, dict) or set(obj) != set(expected):
        raise ValueError(f"{name}: missing/unexpected fields")


def string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


def hash_string(value, name):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError(f"{name} must be a SHA-256")


def identifier(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(re.escape(prefix) + r"[0-9a-f]{64}", value):
        raise ValueError(f"Invalid {prefix} identifier")
    return value


def timestamp(value, name, utc=False):
    string(value, name)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None or (utc and dt.utcoffset().total_seconds() != 0):
            raise ValueError("timezone required; review timestamps must use UTC")
    except ValueError as exc:
        raise ValueError(f"Invalid {name}: {exc}") from exc


def now():
    return datetime.now(timezone.utc).isoformat()


def publish_directory(target, files):
    """Publish a new bundle. Existing artifacts are never replaced (single writer)."""
    target = Path(target)
    if target.exists():
        raise FileExistsError(f"Immutable artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".aic-global-", dir=target.parent) as temp:
        stage = Path(temp) / "bundle"
        stage.mkdir()
        for filename, raw in files.items():
            (stage / filename).write_bytes(raw)
        if target.exists():
            raise FileExistsError(target)
        stage.rename(target)
