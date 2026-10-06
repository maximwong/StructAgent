"""Second actual engineering plugin; builds objects only, no calculation or IO."""

from core import ToolRegistry
from core.plugin_base import PluginContribution
from tools.column.plugin import register_column_workflow


def create_plugin(context):
    registry = ToolRegistry()
    workflow = register_column_workflow(registry, context.output_root)
    return PluginContribution(registry, (workflow,))
