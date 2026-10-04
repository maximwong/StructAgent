"""Start StructAgent's local browser UI using the fixed demo environment."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import webbrowser

from agent.controller import AgentController
from agent.parameter_parser import ParameterParser
from agent.parameter_parser import ParseResult
from agent.state import AgentState
from agent.workflow import Workflow, WorkflowStep
from config import load_settings
from core import ToolRegistry
from llm import DeepSeekGateway
from tools.floor.language_profile import FloorDemoProfile
from tools.floor.explicit_profile import FloorExplicitProfile
from tools.floor.input_form import floor_input_form
from tools.floor.plugin import register_floor_workflow, register_floor_report_workflow
from tools.floor.report_presentation import floor_report_source, validate_floor_report
from ui.server import LocalServer
from ui.service import RunService

ROOT = Path(__file__).resolve().parent
_NO_MODEL = object()


def controller_factory(root, *, model=_NO_MODEL):
    registry = ToolRegistry()
    workflow = register_floor_workflow(registry, root)
    profiles = [FloorDemoProfile()] if model is _NO_MODEL else [FloorExplicitProfile(model)]
    parser = ParameterParser(registry, DeepSeekGateway(load_settings()), profiles)
    return AgentController(registry, parser, AgentState(root / "agent"), [workflow])


def recover(root):
    result = subprocess.run([sys.executable, "-m", "examples.cad_recovery", "--output-root", str(root)],
                            cwd=ROOT, capture_output=True, timeout=40,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode != 0 or json.loads(result.stdout).get("success") is not True:
        raise ValueError("Recovery was not confirmed.")


def report_controller_factory(root, envelope):
    # The user selects an existing design; no cloud parsing, design or CAD here.
    class SavedRequestParser:
        def parse(self, text, *, project_id, profile_name=None):
            return ParseResult('ready',envelope=envelope)
    registry = ToolRegistry()
    register_floor_report_workflow(registry,root)
    workflow = Workflow('artifact_report',(WorkflowStep('report','generate_floor_report'),))
    return AgentController(registry,SavedRequestParser(),AgentState(root/'agent'),[workflow])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output-root", type=Path, default=ROOT / "data/projects")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    service = RunService(args.output_root, controller_factory, settings_check=load_settings, recover=recover,
                         explicit_controller_factory=lambda root, model: controller_factory(root, model=model),
                         input_form=floor_input_form,report_factory=report_controller_factory,
                         report_source=floor_report_source,report_validator=validate_floor_report)
    try:
        server = LocalServer(service, args.port)
    except OSError:
        if not args.no_browser:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/health", timeout=2) as response:
                    if json.load(response).get("application") == "StructAgent":
                        webbrowser.open(f"http://127.0.0.1:{args.port}")
                        return 0
            except (OSError, ValueError):
                pass
        raise ValueError("本机端口已被占用，请关闭原程序或选择其他端口。") from None
    if not args.no_browser:
        webbrowser.open(server.url)
    if sys.stdout:
        print(f"StructAgent: {server.url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass  # Workflow threads finish normally; closing a browser never cancels CAD.
    finally:
        server.server_close()
        if service.thread:
            service.thread.join()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else "无法启动本机界面，请检查运行目录权限。"
        if sys.stderr:
            print(message, file=sys.stderr)
        else:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "StructAgent 启动失败", 0x10)
        raise SystemExit(1)
