"""Complete local source-bound symmetric column layouts through the generic Controller."""
import argparse
import json
from pathlib import Path
import sys

from agent.controller import AgentController
from agent.state import AgentState
from core.plugin_base import PluginContext
from core.plugin_loader import load_plugins
from examples.column_workflow import LocalColumnParser
from tools.column.json_data import loads_json


def run_request(envelope, output_root, *, tool_only=False):
    expected_tool = "check_column_eccentric" if tool_only else "design_column_eccentric"
    if not isinstance(envelope, dict) or envelope.get("tool") != expected_tool:
        raise ValueError("Select matching source-bound combination workflow")
    catalog = load_plugins(Path(__file__).resolve().parents[1] / "plugins", PluginContext(Path(output_root)))
    name = "rc_column_eccentric_actual_check" if tool_only else "rc_column_eccentric"
    workflow = next(row for row in catalog.workflows if row.name == name)
    controller = AgentController(catalog.registry, LocalColumnParser(envelope, catalog.registry),
        AgentState(Path(output_root) / "column-eccentric-agent"), [workflow])
    return controller.run("完整本地柱单向偏压请求", project_id=envelope.get("project_id"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parents[1] / "data/projects")
    parser.add_argument("--tool-only", action="store_true", help="只读实配方案或本项目多组合引用校核")
    args = parser.parse_args(argv)
    try:
        envelope = loads_json(args.request_file.read_text(encoding="utf-8-sig"))
        result = run_request(envelope, args.output_root, tool_only=args.tool_only)
    except Exception:
        result = {"success": False, "status": "invalid_input", "errors": [{"code": "column_eccentric_request_failed",
            "message": "本地柱单向偏压请求文件或初始化失败。", "path": []}]}
    output = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(output.encode("utf-8"))
    else:
        sys.stdout.write(output)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
