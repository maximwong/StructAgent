"""Live semantic-language acceptance; no design or AutoCAD execution."""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from agent.parameter_parser import ParameterParser
from config import load_settings
from core import ToolRegistry
from core.persistence import write_json
from llm import DeepSeekGateway
from tools.floor import FloorDesignTool
from tools.floor.language_profile import FloorDemoProfile

ROOT = Path(__file__).resolve().parents[1]


def qualifies(case, result):
    if result.status != case["status"]:
        return False
    if case["status"] == "ready":
        return all(result.envelope["parameters"].get(k) == v for k, v in case["parameters"].items())
    return (result.envelope is None
            and set(case.get("missing_fields", [])).issubset(result.missing_fields)
            and (not case.get("error") or case["error"] in {e["code"] for e in result.errors}))


def main():
    args_parser = argparse.ArgumentParser(description=__doc__)
    args_parser.add_argument("--output-root", type=Path, default=ROOT / "data/projects/language-acceptance")
    args = args_parser.parse_args()
    settings = load_settings()
    registry = ToolRegistry()
    registry.register(FloorDesignTool())
    parser = ParameterParser(registry, DeepSeekGateway(settings), [FloorDemoProfile()])
    directory = args.output_root / uuid4().hex
    summary = {"success": False, "evidence_kind": "live", "runs": []}
    cases = json.loads((ROOT / "demos/language_cases.json").read_text(encoding="utf-8"))["cases"]
    for case in cases:
        result = parser.parse(case["text"], project_id="CSU-LANGUAGE-DEMO", profile_name="office_floor_demo_v1")
        write_json(directory / (case["id"] + ".json"), result.to_dict(), exclusive=True)
        row = {"case": case["id"], "status": result.status, "qualified": qualifies(case, result),
               "metadata": result.metadata, "errors": result.errors}
        summary["runs"].append(row)
        write_json(directory / "summary.json", summary)
        print(json.dumps(row, ensure_ascii=True), flush=True)
        if not row["qualified"]:
            return 1  # Keep evidence; never silently retry or relax validation.
    summary["success"] = True
    write_json(directory / "summary.json", summary)
    print(json.dumps({"success": True, "cases": len(cases), "summary": str(directory / "summary.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
