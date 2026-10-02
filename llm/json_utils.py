"""Reject ambiguous/nonstandard JSON before schema validation."""

import json
import math


def strict_object(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON field.")
            result[key] = value
        return result

    def reject_constant(_):
        raise ValueError("Non-finite JSON value.")

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Non-finite JSON value.")
        return result

    if not isinstance(text, str) or not text.strip() or len(text) > 100_000:
        raise ValueError("Empty or oversized JSON response.")
    try:
        result = json.loads(text, object_pairs_hook=pairs, parse_constant=reject_constant, parse_float=finite_float)
    except (ValueError, RecursionError):
        raise ValueError("Invalid JSON response.") from None
    if not isinstance(result, dict):
        raise ValueError("JSON response must be an object.")
    return result
