"""No-AI design -> CAD example. AutoCAD must be open and idle."""

import argparse
import json
from pathlib import Path
import sys

from core import ToolRegistry
from tools.floor import FloorDesignTool
from tools.floor.cad_adapter import FloorCADAdapter
from tools.floor.cad_tool import FloorCADTool
from tools.floor.design_store import FloorDesignStore


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Design a floor and generate an independently verified CAD drawing.")
    parser.add_argument("--case", choices=("demo_a", "sample1", "changed"), default="demo_a")
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parents[1] / "data/projects")
    parser.add_argument("--cad-timeout", type=float, default=240, help="CAD execution budget in seconds (10–900).")
    args = parser.parse_args()
    registry = ToolRegistry()
    store = FloorDesignStore(args.output_root / "designs")
    registry.register(FloorDesignTool())
    registry.register(FloorCADTool(store, FloorCADAdapter(args.output_root / "cad", timeout_seconds=args.cad_timeout)))
    model = json.loads((Path(__file__).resolve().parents[1] / "legacy/rc_floor" / (args.case + ".json")).read_text(encoding="utf-8-sig"))
    envelope = {"project_id": "CSU-DEMO-001", "tool": "design_floor_system",
                "context": {"unit_system": "SI", "design_code": "GB"},
                "parameters": {"input_mode": "explicit", "model": model}}
    design = registry.get(envelope["tool"]).execute(envelope)
    if not design.success:
        print(json.dumps(design.to_dict(), ensure_ascii=False, indent=2))
        return 1
    reference = store.save(design)
    envelope.update(tool="generate_floor_cad", parameters={"design_result_ref": reference})
    result = registry.get(envelope["tool"]).execute(envelope)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
