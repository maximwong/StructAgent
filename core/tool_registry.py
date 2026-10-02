"""Explicit tool registration; no tool-specific dispatch or auto-discovery."""

from .exceptions import ToolDefinitionError, ToolNotFoundError
from .tool_base import EngineeringTool


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, EngineeringTool] = {}

    def register(self, tool: EngineeringTool) -> None:
        if not isinstance(tool, EngineeringTool):
            raise ToolDefinitionError("Only EngineeringTool instances can be registered.")
        if tool.name in self._tools:
            raise ToolDefinitionError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> EngineeringTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"Tool not registered: {name}") from exc

    def list_tools(self) -> list[dict]:
        return [tool.describe() for tool in self._tools.values()]
