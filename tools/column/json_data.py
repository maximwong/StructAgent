"""Strict local JSON and deterministic hashes; no floor or external dependency."""

import hashlib
import json

from core.validation import ensure_json


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key.")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("Non-finite JSON value.")


def loads_json(text):
    result = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    ensure_json(result)
    return result


def canonical_hash(data):
    ensure_json(data)
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode("utf-8")).hexdigest()
