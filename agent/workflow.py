"""Declarative, application-owned tool workflows. Never supplied by the LLM."""

from dataclasses import dataclass, field
import re

from core.validation import ensure_json


@dataclass(frozen=True)
class ResultBinding:
    step: str
    path: tuple[str | int, ...]


@dataclass(frozen=True)
class WorkflowStep:
    name: str
    tool: str
    parameters: dict = field(default_factory=dict)
    bindings: dict[str, ResultBinding] = field(default_factory=dict)
    external_effects: bool = False


@dataclass(frozen=True)
class Workflow:
    name: str
    steps: tuple[WorkflowStep, ...]

    def validate(self, registry):
        def identifier(value):
            return isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]*", value)

        if not identifier(self.name) or not self.steps:
            raise ValueError("Workflow name and steps are required.")
        seen = {"parse"}
        for index, step in enumerate(self.steps):
            if not identifier(step.name) or step.name in seen or type(step.external_effects) is not bool:
                raise ValueError("Workflow step names must be unique identifiers, excluding parse.")
            registry.get(step.tool)
            if not isinstance(step.parameters, dict) or not isinstance(step.bindings, dict):
                raise ValueError("Step parameters and bindings must be objects.")
            ensure_json(step.parameters)
            if index == 0 and (step.parameters or step.bindings):
                raise ValueError("The first step uses only the validated parser envelope.")
            if set(step.parameters) & set(step.bindings):
                raise ValueError("Static and bound parameters cannot overlap.")
            for parameter, binding in step.bindings.items():
                if (not identifier(parameter) or not isinstance(binding, ResultBinding)
                        or binding.step not in seen - {"parse"} or not isinstance(binding.path, (tuple, list)) or not binding.path
                        or any(type(p) not in (str, int) or isinstance(p, int) and p < 0 for p in binding.path)):
                    raise ValueError("Bindings must read an earlier tool result using an explicit field path.")
            seen.add(step.name)
