import copy
import json
import unittest

from core import (
    EngineeringTool, ToolDefinitionError, ToolNotFoundError,
    ToolRegistry, ToolResult, ToolValidationError,
)
from examples.dummy_tool import DummyTool


NUMBER_OBJECT = {
    "type": "object", "properties": {"value": {"type": "number"}},
    "required": ["value"], "additionalProperties": False,
}


def envelope(name="probe_tool", value=6):
    return {"project_id": "TEST-001", "tool": name,
            "context": {"unit_system": "SI", "design_code": "GB"},
            "parameters": {"value": value}}


class ProbeTool(EngineeringTool):
    def __init__(self, name="probe_tool", action=None, parameters_schema=None,
                 output_schema=None, version="1.0", description="Test tool"):
        super().__init__(name=name, version=version, description=description,
                         parameters_schema=NUMBER_OBJECT if parameters_schema is None else parameters_schema,
                         output_schema=NUMBER_OBJECT if output_schema is None else output_schema)
        self.action = action
        self.calls = 0

    def _execute(self, data):
        self.calls += 1
        if self.action:
            return self.action(self, data)
        return ToolResult(True, self.name, self.version, result=data["parameters"])


class RegistryTests(unittest.TestCase):
    def test_dummy_end_to_end_and_discovery(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        info, = registry.list_tools()
        self.assertEqual(set(info), {"name", "version", "description", "input_schema", "output_schema"})
        self.assertEqual(info["input_schema"]["properties"]["tool"]["const"], "dummy_tool")
        result = registry.get("dummy_tool").execute(envelope("dummy_tool"))
        self.assertTrue(result.success)
        self.assertEqual(result.result, {"value": 6})
        self.assertEqual(json.loads(json.dumps(result.to_dict(), allow_nan=False)), result.to_dict())

    def test_second_tool_needs_only_registration(self):
        registry = ToolRegistry()
        for tool in (DummyTool(), ProbeTool(name="another_tool")):
            registry.register(tool)
            self.assertTrue(registry.get(tool.name).execute(envelope(tool.name)).success)
        self.assertEqual([item["name"] for item in registry.list_tools()], ["dummy_tool", "another_tool"])

    def test_duplicate_does_not_replace_existing_tool(self):
        registry = ToolRegistry()
        original = ProbeTool()
        registry.register(original)
        with self.assertRaises(ToolDefinitionError):
            registry.register(ProbeTool(version="2.0"))
        self.assertIs(registry.get(original.name), original)

    def test_missing_tool_and_invalid_registration(self):
        registry = ToolRegistry()
        self.assertEqual(registry.list_tools(), [])
        with self.assertRaises(ToolNotFoundError):
            registry.get("not_installed")
        with self.assertRaises(ToolDefinitionError):
            registry.register(object())

    def test_discovery_is_a_detached_snapshot(self):
        registry = ToolRegistry()
        tool = ProbeTool()
        registry.register(tool)
        info = registry.list_tools()[0]
        info["input_schema"]["properties"]["parameters"]["properties"]["value"]["type"] = "boolean"
        info["output_schema"].clear()
        self.assertTrue(tool.execute(envelope()).success)
        self.assertFalse(tool.execute(envelope(value=True)).success)
        self.assertEqual(tool.output_schema, NUMBER_OBJECT)


class ExecutionTests(unittest.TestCase):
    def test_bad_definitions_fail_before_registration(self):
        for kwargs in ({"name": "bad name"}, {"version": " "}, {"description": ""},
                       {"parameters_schema": {"type": "number"}},
                       {"output_schema": {"type": "object", "required": "invalid"}}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ToolDefinitionError):
                ProbeTool(**kwargs)

    def test_definition_does_not_retain_callers_schema(self):
        schema = copy.deepcopy(NUMBER_OBJECT)
        tool = ProbeTool(parameters_schema=schema, output_schema=schema)
        schema["properties"]["value"]["type"] = "boolean"
        self.assertTrue(tool.execute(envelope()).success)
        self.assertFalse(tool.execute(envelope(value=False)).success)

    def test_missing_fields_never_execute(self):
        paths = [(field,) for field in ("project_id", "tool", "context", "parameters")]
        paths += [("context", "unit_system"), ("context", "design_code"), ("parameters", "value")]
        tool = ProbeTool()
        for path in paths:
            with self.subTest(path=path):
                data = envelope()
                target = data
                for key in path[:-1]:
                    target = target[key]
                del target[path[-1]]
                result = tool.execute(data)
                self.assertFalse(result.success)
                self.assertTrue(result.errors)
        self.assertEqual(tool.calls, 0)

    def test_wrong_routing_blank_project_and_extra_fields(self):
        tool = ProbeTool()
        for change in ({"tool": "other_tool"}, {"project_id": " "}, {"extra": 1},
                       {"parameters": {"value": 3, "extra": 4}},
                       {"context": {"unit_system": "", "design_code": "GB"}}):
            with self.subTest(change=change):
                self.assertFalse(tool.execute({**envelope(), **change}).success)
        self.assertEqual(tool.calls, 0)

    def test_boolean_strings_and_nonfinite_numbers_are_rejected(self):
        tool = ProbeTool()
        for value in (True, False, "6", float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value):
                result = tool.execute(envelope(value=value))
                self.assertFalse(result.success)
                self.assertEqual(result.errors[0]["path"], ["parameters", "value"])
        self.assertEqual(tool.calls, 0)

    def test_non_json_context_and_cycles_are_rejected(self):
        tool = ProbeTool()
        for value in (object(), (1, 2), {1: "nonstring key"}):
            data = envelope()
            data["context"]["extra"] = value
            self.assertFalse(tool.execute(data).success)
        data = envelope()
        data["context"]["cycle"] = data
        self.assertFalse(tool.execute(data).success)
        self.assertEqual(tool.calls, 0)

    def test_direct_validate_is_valueerror_compatible(self):
        with self.assertRaises(ValueError) as ctx:
            ProbeTool().validate(envelope(value=True))
        self.assertIsInstance(ctx.exception, ToolValidationError)
        self.assertEqual(ctx.exception.errors[0]["path"], ["parameters", "value"])

    def test_tool_cannot_mutate_callers_input(self):
        def mutate(tool, data):
            data["parameters"]["value"] += 1
            data["context"]["unit_system"] = "changed"
            return ToolResult(True, tool.name, tool.version, result=data["parameters"])
        data = envelope()
        original = copy.deepcopy(data)
        result = ProbeTool(action=mutate).execute(data)
        self.assertEqual(data, original)
        self.assertEqual(result.result, {"value": 7})

    def test_exception_becomes_failure_and_tool_can_run_again(self):
        def explode(tool, data):
            raise RuntimeError("adapter failed")
        tool = ProbeTool(action=explode)
        result = tool.execute(envelope())
        self.assertFalse(result.success)
        self.assertEqual(result.errors[0]["code"], "execution_error")
        self.assertIn("adapter failed", result.errors[0]["message"])
        tool.action = None
        self.assertTrue(tool.execute(envelope()).success)

    def test_keyboard_interrupt_is_not_swallowed(self):
        def cancel(tool, data):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            ProbeTool(action=cancel).execute(envelope())

    def test_bad_outputs_are_failures(self):
        actions = [
            lambda t, d: {"success": True},
            lambda t, d: ToolResult(True, "wrong_tool", t.version, result={"value": 1}),
            lambda t, d: ToolResult(True, t.name, "wrong_version", result={"value": 1}),
            lambda t, d: ToolResult(True, t.name, t.version, result={"value": True}),
            lambda t, d: ToolResult(True, t.name, t.version, result={}),
        ]
        for action in actions:
            with self.subTest(action=action):
                result = ProbeTool(action=action).execute(envelope())
                self.assertFalse(result.success)
                self.assertEqual(result.errors[0]["code"], "output_validation_error")

    def test_domain_failure_does_not_require_success_output(self):
        tool = ProbeTool(action=lambda t, d: ToolResult.failure(
            t.name, t.version, "design_failed", "No valid design.", ["parameters", "value"]))
        result = tool.execute(envelope())
        self.assertFalse(result.success)
        self.assertEqual(result.errors[0]["code"], "design_failed")
        self.assertEqual(result.result, {})

    def test_local_schema_references_survive_envelope_wrapping(self):
        schema = {"type": "object", "$defs": {"positive": {"type": "number", "exclusiveMinimum": 0}},
                  "properties": {"value": {"$ref": "#/$defs/positive"}}, "required": ["value"]}
        tool = ProbeTool(parameters_schema=schema, output_schema=schema)
        self.assertTrue(tool.execute(envelope(value=2)).success)
        self.assertFalse(tool.execute(envelope(value=0)).success)

    def test_external_schema_references_fail_without_retrieval(self):
        schema = {"type": "object", "properties": {"value": {"$ref": "https://example.invalid/schema"}}}
        tool = ProbeTool(parameters_schema=schema)
        result = tool.execute(envelope())
        self.assertFalse(result.success)
        self.assertIn("locally", result.errors[0]["message"])
        self.assertEqual(tool.calls, 0)


class ResultTests(unittest.TestCase):
    def test_result_fields_and_serialization_are_detached(self):
        result = ToolResult(True, "test", "1", result={"value": 1}, warnings=["review"],
                            artifacts=[{"type": "json", "path": "result.json"}], metadata={"run": "1"})
        exported = result.to_dict()
        self.assertEqual(set(exported), {"success", "tool", "version", "result", "warnings", "errors", "artifacts", "metadata"})
        exported["result"]["value"] = 99
        self.assertEqual(result.result["value"], 1)
        other = ToolResult(True, "test", "1")
        result.warnings.append("another")
        self.assertEqual(other.warnings, [])

    def test_inconsistent_or_non_json_results_cannot_be_created(self):
        for kwargs in ({"success": 1}, {"success": False},
                       {"errors": [{"code": "failure", "message": "failed", "path": []}]},
                       {"result": {"value": float("nan")}}, {"metadata": {"value": object()}},
                       {"artifacts": [{"type": "dwg"}]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ToolValidationError):
                ToolResult(**{"success": True, "tool": "test", "version": "1", **kwargs})


if __name__ == "__main__":
    unittest.main()
