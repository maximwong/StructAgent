"""Run a complete local column Envelope through the existing Controller."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

from agent.controller import AgentController
from agent.parameter_parser import ParseResult
from agent.state import AgentState
from agent.workflow import Workflow, WorkflowStep
from core import ToolValidationError
from core.plugin_base import PluginContext
from core.plugin_loader import load_plugins
from tools.column.json_data import loads_json


class LocalColumnParser:
    def __init__(self, envelope, registry):
        self.envelope, self.registry = deepcopy(envelope), registry

    def parse(self, text, *, project_id, profile_name=None):
        try:
            if self.envelope.get("project_id") != project_id:
                raise ValueError("Project mismatch.")
            self.registry.get(self.envelope["tool"]).validate(self.envelope)
            return ParseResult("ready", envelope=deepcopy(self.envelope),
                               metadata={"source": "explicit_local_json", "inferred_fields": []})
        except ToolValidationError as exc:
            return ParseResult("invalid_input", errors=exc.errors)
        except (ValueError, KeyError, TypeError):
            return ParseResult("invalid_input", errors=[{
                "code": "invalid_column_request", "message": "需要完整且一致的本地柱Envelope。", "path": []}])


def run_request(envelope, output_root, *, tool_only=False):
    root = Path(__file__).resolve().parents[1]
    if not isinstance(envelope, dict) or envelope.get("tool") not in {"design_column", "check_column_design"}:
        raise ValueError("Column Envelope required.")
    if (tool_only and envelope["tool"] != "check_column_design"
            or not tool_only and envelope["tool"] != "design_column"):
        raise ValueError("Select the matching column workflow mode.")
    catalog = load_plugins(root / "plugins", PluginContext(Path(output_root)))
    workflow = (Workflow("rc_column_actual_check", (WorkflowStep("check", "check_column_design"),)) if tool_only
                else next(workflow for workflow in catalog.workflows if workflow.name == "rc_column_design"))
    controller = AgentController(catalog.registry, LocalColumnParser(envelope, catalog.registry),
                                 AgentState(Path(output_root) / "column-agent"), [workflow])
    return controller.run("完整本地柱请求", project_id=envelope.get("project_id"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-file", required=True, type=Path, help="完整本地Envelope，不推断字段或单位。")
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parents[1] / "data/projects")
    parser.add_argument("--tool-only", action="store_true", help="通过Controller单步校核实配方案或本项目引用。")
    args = parser.parse_args(argv)
    try:
        envelope = loads_json(args.request_file.read_text(encoding="utf-8-sig"))
        result = run_request(envelope, args.output_root, tool_only=args.tool_only)
    except Exception:
        result = {"success": False, "status": "invalid_input", "errors": [{
            "code": "column_request_failed", "message": "本地柱请求文件或执行初始化失败。", "path": []}]}
    output = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(output.encode("utf-8"))
    else:
        sys.stdout.write(output)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
