"""Local plugin contributions; professional behavior stays in plugin callbacks."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .tool_registry import ToolRegistry


@dataclass(frozen=True)
class PluginContext:
    output_root: Path
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PluginWebBinding:
    template_profile: str
    explicit_profile: str
    explicit_factory: Callable
    input_form: Callable
    report_workflow: str
    report_source: Callable
    report_validator: Callable
    recover: Callable


@dataclass(frozen=True)
class StructuredWebOperation:
    id: str
    name: str
    workflow: str
    tool: str


@dataclass(frozen=True)
class StructuredWebBinding:
    id: str
    name: str
    operations: tuple
    form: Callable
    request: Callable
    presentation: Callable


@dataclass(frozen=True)
class PluginContribution:
    registry: ToolRegistry
    workflows: tuple
    profiles: tuple = ()
    web: PluginWebBinding | None = None
    structured_web: tuple = ()
