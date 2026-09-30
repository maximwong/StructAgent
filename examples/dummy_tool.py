"""Run from the repository root: python -m examples.dummy_tool."""

import json

from core import EngineeringTool, ToolRegistry, ToolResult


class DummyTool(EngineeringTool):
    def __init__(self):
        super().__init__(
            name="dummy_tool", version="1.0.0",
            description="Return a validated number without performing engineering calculations.",
            parameters_schema={
                "type": "object", "properties": {"value": {"type": "number"}},
                "required": ["value"], "additionalProperties": False,
            },
            output_schema={
                "type": "object", "properties": {"value": {"type": "number"}},
                "required": ["value"], "additionalProperties": False,
            },
        )

    def _execute(self, data):
        return ToolResult(True, self.name, self.version,
                          result={"value": data["parameters"]["value"]})


def main():
    registry = ToolRegistry()
    registry.register(DummyTool())
    result = registry.get("dummy_tool").execute({
        "project_id": "TOOL-CORE-DEMO", "tool": "dummy_tool",
        "context": {"unit_system": "SI", "design_code": "GB"},
        "parameters": {"value": 6.0},
    })
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
