"""Strict JSON and scalar validation shared by the local development seed."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from typing import Any


def text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be a nonempty string')
    return value


def timestamp(value: Any, name: str = 'timestamp') -> datetime:
    text(value, name)
    if not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)', value):
        raise ValueError(f'{name} must be an offset-aware RFC3339 timestamp')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None:
        raise ValueError(f'{name} must include a timezone')
    return result


def digest(value: Any, name: str = 'hash') -> str:
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError(f'{name} must be a lowercase SHA-256 digest')
    return value


def unique_strings(values: Any, name: str) -> None:
    if not isinstance(values, (tuple, list)):
        raise ValueError(f'{name} must be a sequence')
    for value in values:
        text(value, name)
    if len(set(values)) != len(values):
        raise ValueError(f'{name} contains duplicates')


def strict_loads(raw: str) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    def reject(value):
        raise ValueError(f'Non-finite JSON number: {value}')
    def finite_float(value):
        number=float(value)
        if not math.isfinite(number): reject(value)
        return number
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject, parse_float=finite_float)


def canonical_bytes(value: Any) -> bytes:
    def check(item):
        if isinstance(item, dict):
            if any(not isinstance(k, str) for k in item):
                raise ValueError('JSON object keys must be strings')
            for v in item.values(): check(v)
        elif isinstance(item, (tuple, list)):
            for v in item: check(v)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise ValueError(f'Not a JSON value: {type(item).__name__}')
    check(value)
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def object_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
