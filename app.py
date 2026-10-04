"""Start StructAgent's local browser UI using the fixed demo environment."""

import argparse
import json
from pathlib import Path
import sys
import urllib.request
import webbrowser

from agent.controller import AgentController
from agent.parameter_parser import ParameterParser
from agent.parameter_parser import ParseResult
from agent.state import AgentState
from config import load_settings
from core.plugin_base import PluginContext
from core.plugin_loader import load_plugins
from llm import DeepSeekGateway
from ui.server import LocalServer
from ui.service import RunService

ROOT = Path(__file__).resolve().parent
PLUGINS = ROOT / 'plugins'
_NO_MODEL = object()


def controller_factory(root, *, model=_NO_MODEL, plugin_directory=PLUGINS, plugin_options=None):
    catalog = load_plugins(plugin_directory, PluginContext(Path(root), plugin_options or {}))
    profiles = catalog.profiles if model is _NO_MODEL else catalog.explicit_profiles(model)
    parser = ParameterParser(catalog.registry, DeepSeekGateway(load_settings()), profiles)
    return AgentController(catalog.registry, parser, AgentState(root / "agent"), catalog.workflows)


def recover(root):
    load_plugins(PLUGINS, PluginContext(Path(root))).web_binding().recover(root)


def report_controller_factory(root, envelope, *, plugin_directory=PLUGINS, plugin_options=None):
    # The user selects an existing design; no cloud parsing, design or CAD here.
    class SavedRequestParser:
        def parse(self, text, *, project_id, profile_name=None):
            return ParseResult('ready',envelope=envelope)
    catalog = load_plugins(plugin_directory, PluginContext(Path(root), plugin_options or {}))
    workflow = catalog.report_workflow(envelope)
    return AgentController(catalog.registry,SavedRequestParser(),AgentState(root/'agent'),[workflow])


def create_service(root, *, plugin_directory=PLUGINS, plugin_options=None):
    """One composition path for the normal UI and controlled acceptance fixtures."""
    root = Path(root)
    catalog = load_plugins(plugin_directory, PluginContext(root, plugin_options or {}))
    web = catalog.web_binding()
    return RunService(root, lambda root: controller_factory(root, plugin_directory=plugin_directory, plugin_options=plugin_options),
        settings_check=load_settings, recover=web.recover,
        explicit_controller_factory=lambda root, model: controller_factory(root, model=model, plugin_directory=plugin_directory, plugin_options=plugin_options),
        input_form=web.input_form, template_profile=web.template_profile, explicit_profile=web.explicit_profile,
        report_factory=lambda root, envelope: report_controller_factory(root, envelope, plugin_directory=plugin_directory, plugin_options=plugin_options),
        report_source=web.report_source, report_validator=web.report_validator)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output-root", type=Path, default=ROOT / "data/projects")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--plugins", type=Path, default=PLUGINS, help="Installed trusted local plugins directory")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    service = create_service(args.output_root, plugin_directory=args.plugins)
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
