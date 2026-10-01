"""Publish complete JSON snapshots; never expose a half-written document."""

import json
import os
from pathlib import Path
import tempfile

from .validation import ensure_json


def write_json(path, data, *, exclusive=False):
    ensure_json(data)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".pending-", suffix=".json", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, path)  # Atomic publication that cannot overwrite another snapshot.
        else:
            os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
