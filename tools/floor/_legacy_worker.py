"""Private JSON bridge, run in a separate interpreter to isolate legacy imports."""

from contextlib import redirect_stdout
import json
from pathlib import Path
import sys


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    legacy_dir = Path(__file__).resolve().parents[2] / "legacy" / "rc_floor"
    sys.path.insert(0, str(legacy_dir))
    try:
        model = json.load(sys.stdin)
        with redirect_stdout(sys.stderr):
            from engine import calculate
            result = calculate(model)
        # Serialize before writing so an unsupported result cannot leave partial JSON.
        message = json.dumps({"protocol": 1, "success": True, "result": result},
                             ensure_ascii=False, allow_nan=False)
    except ValueError as exc:
        message = json.dumps({"protocol": 1, "success": False, "error": {
            "code": "design_rejected", "message": str(exc) or "Legacy design rejected the input.",
        }}, ensure_ascii=False)
    except Exception as exc:
        message = json.dumps({"protocol": 1, "success": False, "error": {
            "code": "legacy_execution_error", "message": f"{type(exc).__name__}: {exc}",
        }}, ensure_ascii=False)
    sys.stdout.write(message)


if __name__ == "__main__":
    main()
