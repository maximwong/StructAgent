"""Second actual engineering plugin; builds objects only, no calculation or IO."""

from core import ToolRegistry
from core.plugin_base import PluginContribution
from tools.column.plugin import register_column_workflow, register_column_combinations
from agent.workflow import Workflow, WorkflowStep
from tools.column.web import column_web_binding


def create_plugin(context):
    registry = ToolRegistry()
    workflow = register_column_workflow(registry, context.output_root)
    check = Workflow('rc_column_actual_check', (WorkflowStep('check', 'check_column_design'),))
    combinations = register_column_combinations(registry, context.output_root)
    combination_check = Workflow('rc_column_combinations_actual_check', (WorkflowStep('check', 'check_column_combinations'),))
    return PluginContribution(registry, (workflow, check, combinations, combination_check),
                              structured_web=(column_web_binding(registry, context.output_root),))
