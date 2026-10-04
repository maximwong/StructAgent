"""Non-engineering numeric echo fixture for independent plugin/Controller tests."""

from agent.parameter_parser import LanguageProfile
from agent.workflow import Workflow, WorkflowStep
from core import EngineeringTool, ToolRegistry, ToolResult
from core.plugin_base import PluginContribution

VALUE = {'type': 'object', 'properties': {'value': {'type': 'number'}},
         'required': ['value'], 'additionalProperties': False}


class EchoTool(EngineeringTool):
    def __init__(self, name):
        super().__init__(name=name, version='1.0.0', description='Test only: echo a number, no engineering calculation.',
                         parameters_schema=VALUE, output_schema=VALUE)

    def _execute(self, data):
        return ToolResult(True, self.name, self.version, result=dict(value=data['parameters']['value']))


class EchoProfile(LanguageProfile):
    def __init__(self, tool, name):
        super().__init__(name, tool, 'Test only: the text is one explicit number.', VALUE, {},
                         dict(unit_system='SI', design_code='GB'))

    def inspect(self, text):
        return {'value': float(text)}


def contribution(context, tool='echo_value', workflow='echo_workflow', profile='echo_v1'):
    registry = ToolRegistry(); registry.register(EchoTool(tool))
    return PluginContribution(registry, (Workflow(workflow, (WorkflowStep('echo', tool),)),),
                              (EchoProfile(tool, profile),))
