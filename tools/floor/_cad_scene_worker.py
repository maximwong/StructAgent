"""Isolate existing scene conversion without changing its data or formulas."""

from contextlib import redirect_stdout
import json
from pathlib import Path
import sys


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "legacy" / "rc_floor"))
    try:
        result = json.load(sys.stdin)
        with redirect_stdout(sys.stderr):
            from cad_scene import export_drawing
            scene = export_drawing(result, Path(sys.argv[1]))
        response = {"success": True, "entities": sum(len(v) for v in scene["groups"].values())}
    except Exception as exc:
        response = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
