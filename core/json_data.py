"""Strict JSON boundary shared by local HTTP and structured requests."""
import json
from .validation import ensure_json


def loads_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('JSON包含重复字段。')
            result[key] = value
        return result

    def constant(value):
        raise ValueError('JSON不能包含非有限数值。')

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    ensure_json(value)
    return value
