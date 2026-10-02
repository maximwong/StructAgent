"""Run the registered workflow or inspect its durable status, without a UI dependency."""

import argparse
import json
from pathlib import Path
import sys

from agent.controller import AgentController
from agent.parameter_parser import ParameterParser
from agent.state import AgentState
from config import ConfigurationError, load_settings
from core import ToolRegistry
from llm import DeepSeekGateway
from tools.floor.language_profile import FloorDemoProfile
from tools.floor.plugin import register_floor_workflow


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="自然语言→参数校验→Registry设计→Registry CAD→持久状态。")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--text-file", type=Path)
    source.add_argument("--status", metavar="RUN_ID", help="读取既有运行状态；不调用API或CAD。")
    parser.add_argument("--template", choices=("office_floor_demo_v1",))
    parser.add_argument("--project-id", default="CSU-DEMO-001")
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parents[1] / "data/projects")
    parser.add_argument("--cad-timeout", type=float, default=240)
    args = parser.parse_args()
    try:
        state = AgentState(args.output_root / "agent")
        if args.status:
            result = state.get(args.status)
        else:
            settings = load_settings()
            text = args.text_file.read_text(encoding="utf-8-sig") if args.text_file else args.text
            if settings.api_key in text or settings.api_key in args.project_id:
                raise ConfigurationError("Remove the API key from the design input or project identity.")
            registry = ToolRegistry()
            workflow = register_floor_workflow(registry, args.output_root, cad_timeout=args.cad_timeout)
            parameter_parser = ParameterParser(registry, DeepSeekGateway(settings), [FloorDemoProfile()])
            controller = AgentController(registry, parameter_parser, state, [workflow])
            result = controller.run(text, project_id=args.project_id, profile_name=args.template)
    except (ConfigurationError, OSError, ValueError, KeyError) as exc:
        message = str(exc) if isinstance(exc, ConfigurationError) else "Cannot initialize workflow or read requested input/status."
        result = {"success": False, "status": "error", "errors": [{"code": "setup_failed", "message": message}]}
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
