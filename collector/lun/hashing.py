import hashlib
import json
from typing import Any


def without_today(value: Any) -> Any:
    """The payload minus every object with "isToday": true. The floating "today" point carries the export date,
    so it changes on every request even when LUN's data did not."""
    if isinstance(value, list):
        return [without_today(v) for v in value if not (isinstance(v, dict) and v.get('isToday') is True)]
    if isinstance(value, dict):
        return {k: without_today(v) for k, v in value.items()}
    return value


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _canonical(value: Any) -> Any:
    """Lists of records are sets to us: LUN returns the same records in a different order from request to request
    (seen on `price`), so they are sorted before hashing."""
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        items = [_canonical(v) for v in value]
        if items and all(isinstance(v, dict) for v in items):
            items.sort(key=_dumps)
        return items
    return value


def payload_hash(payload: Any) -> str:
    return hashlib.sha256(_dumps(_canonical(without_today(payload))).encode()).hexdigest()
