"""JSON-only data and Draft 2020-12 validation without network retrieval."""

from math import isfinite

from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.exceptions import Unresolvable

from .exceptions import ToolValidationError


def reject(message: str, path=(), code="validation_error"):
    raise ToolValidationError([{"code": code, "message": message, "path": list(path)}])


def ensure_json(value, path=(), active=None):
    """Reject Python-only objects, cycles, non-string keys and NaN/infinity."""
    active = set() if active is None else active
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not isfinite(value):
            reject("Expected a finite JSON number.", path)
        return
    if type(value) not in (dict, list):
        reject(f"Expected JSON data, received {type(value).__name__}.", path)
    if id(value) in active:
        reject("Circular references are not JSON data.", path)
    active.add(id(value))
    try:
        if type(value) is dict:
            for key, item in value.items():
                if type(key) is not str:
                    reject("JSON object keys must be strings.", path)
                ensure_json(item, (*path, key), active)
        else:
            for index, item in enumerate(value):
                ensure_json(item, (*path, index), active)
    finally:
        active.remove(id(value))


def make_validator(schema):
    ensure_json(schema)
    Draft202012Validator.check_schema(schema)
    # An empty registry never retrieves external schemas. Local $defs still work.
    return Draft202012Validator(schema, registry=Registry())


def validate_json(value, validator, *, prefix=()):
    ensure_json(value, prefix)
    try:
        errors = [
            {"code": "validation_error", "message": error.message,
             "path": [*prefix, *error.absolute_path]}
            for error in validator.iter_errors(value)
        ]
    except Unresolvable as exc:
        reject(f"Schema reference cannot be resolved locally: {exc}", prefix)
    if errors:
        raise ToolValidationError(errors)
