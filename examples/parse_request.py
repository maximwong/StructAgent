"""Parse only: python -m examples.parse_request --template office_floor_demo_v1 --text ..."""

import argparse
import json
from pathlib import Path
import sys

from agent.parameter_parser import ParameterParser
from config import ConfigurationError, load_settings
from core import ToolRegistry
from core.persistence import write_json
from llm import DeepSeekGateway
from tools.floor import FloorDesignTool
from tools.floor.language_profile import FloorDemoProfile


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="DeepSeek工程参数解析；不执行设计或CAD。")
    parser.add_argument("--template", choices=("office_floor_demo_v1",), required=True)
    parser.add_argument("--project-id", default="CSU-DEMO-001")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--text-file", type=Path, help="UTF-8文件；适用于中文终端输入。")
    parser.add_argument("--output", type=Path, help="保存解析结果，后续Controller接收ready的Envelope。")
    args = parser.parse_args()
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(json.dumps({"status": "error", "errors": [{"code": "configuration_error", "message": str(exc)}]}, ensure_ascii=False))
        return 1
    text = args.text_file.read_text(encoding="utf-8-sig") if args.text_file else args.text
    # Reject accidentally pasted credentials before sending user text to the model or printing it.
    if settings.api_key in text or settings.api_key in args.project_id:
        print('{"status":"error","errors":[{"code":"credential_in_input","message":"Remove the API key from design input."}]}')
        return 1
    registry = ToolRegistry()
    registry.register(FloorDesignTool())
    language_parser = ParameterParser(registry, DeepSeekGateway(settings), [FloorDemoProfile()])
    result = language_parser.parse(text, project_id=args.project_id, profile_name=args.template).to_dict()
    if args.output:
        write_json(args.output, result, exclusive=True)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
