"""First installed plugin: reuse existing tools, adapters, profiles and presentation."""

from pathlib import Path

from agent.workflow import Workflow, WorkflowStep
from core import ToolRegistry
from core.plugin_base import PluginContribution, PluginWebBinding
from tools.floor.plugin import register_floor_workflow
from tools.floor.design_store import FloorDesignStore
from tools.floor.report_tool import FloorReportTool
from tools.floor.report_adapter import FloorReportAdapter
from tools.floor.language_profile import FloorDemoProfile
from tools.floor.explicit_profile import FloorExplicitProfile
from tools.floor.input_form import floor_input_form
from tools.floor.reaction_tools import FloorReactionTool
from tools.floor.report_presentation import floor_report_source, validate_floor_report
from .recovery import recover


def create_plugin(context):
    root = Path(context.output_root)
    registry = ToolRegistry()
    workflow = register_floor_workflow(registry, root,
        cad_timeout=context.options.get('cad_timeout', 240), cad_backend=context.options.get('cad_backend'))
    registry.register(FloorReportTool(FloorDesignStore(root/'designs'), registry,
        FloorReportAdapter(root/'reports'), root/'revisions'))
    report = Workflow('artifact_report', (WorkflowStep('report', 'generate_floor_report'),))
    reaction_workflows=[]
    for walls in (False,True):
        tool=FloorReactionTool(FloorDesignStore(root/'designs'),root/'reaction-results',walls=walls)
        registry.register(tool)
        reaction_workflows.append(Workflow(tool.name,(WorkflowStep('analysis',tool.name),)))
    return PluginContribution(registry, (workflow, report,*reaction_workflows), (FloorDemoProfile(),),
        PluginWebBinding('office_floor_demo_v1', 'floor_explicit_v1', FloorExplicitProfile,
            floor_input_form, report.name, floor_report_source, validate_floor_report, recover))
