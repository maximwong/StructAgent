"""Run from the repo root: python -m examples.floor_design [--case demo_a]."""

import argparse
import json
from pathlib import Path
import sys

from core import ToolRegistry
from tools.floor import FloorDesignTool


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run the complete floor design through Tool Registry.")
    parser.add_argument("--case", choices=("demo_a", "sample1", "changed"), default="demo_a")
    parser.add_argument("--full", action="store_true", help="Print the full ToolResult instead of a summary.")
    args = parser.parse_args()
    if args.case == "demo_a":
        parameters = {"input_mode": "template", "template_id": "office_floor_demo_v1",
                      "span_x": 6000, "span_y": 6000, "concrete": "C30", "steel": "HRB400", "live_load": 2.0}
    else:
        path = Path(__file__).resolve().parents[1] / "legacy" / "rc_floor" / (args.case + ".json")
        parameters = {"input_mode": "explicit", "model": json.loads(path.read_text(encoding="utf-8-sig"))}
    registry = ToolRegistry()
    registry.register(FloorDesignTool())
    result = registry.get("design_floor_system").execute({
        "project_id": "CSU-DEMO-001", "tool": "design_floor_system",
        "context": {"unit_system": "SI", "design_code": "GB"}, "parameters": parameters,
    })
    output = result.to_dict()
    if result.success and not args.full:
        output["summary"] = {
            "slab_sections": len(result.result["slab"]["sections"]),
            "secondary_sections": len(result.result["secondary_beam"]["sections"]),
            "main_sections": len(result.result["main_beam"]["sections"]),
            "bar_records": len(result.result["reinforcement"]["bars"]),
        }
        del output["result"]
    print(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
