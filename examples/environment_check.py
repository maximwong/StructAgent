"""Check the frozen local demo runtime before starting a presentation."""

import importlib.metadata
import json
from pathlib import Path
import platform
import struct
import sys


def check():
    root = Path(__file__).resolve().parents[1]
    expected_python = (root / ".python-version").read_text().strip()
    errors = []
    if platform.python_version() != expected_python:
        errors.append(f"Python {expected_python} required; found {platform.python_version()}.")
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        errors.append("The desktop demo requires 64-bit Windows and Python.")
    packages = {}
    for row in (root / "requirements-demo.txt").read_text().splitlines():
        if not row.strip() or row.startswith("#"):
            continue
        name, expected = row.split("==")
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = "missing"
        packages[name] = actual
        if actual != expected:
            errors.append(f"{name}: expected {expected}, found {actual}.")
    return {"success": not errors, "python": platform.python_version(), "packages": packages,
            "errors": errors, "cad_requirement": "AutoCAD 2022; license, Unicode engine and trusted script configured locally."}


if __name__ == "__main__":
    result = check()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["success"] else 1)
