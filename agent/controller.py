"""Generic sequential orchestration via Registry, schemas, ToolResult and durable state."""

from copy import deepcopy
import time

from core import ToolResult, ToolValidationError
from core.validation import make_validator, validate_json
from .parameter_parser import ParseResult


def error(code, message, path=()):
    return {"code": code, "message": message, "path": list(path)}


class AgentController:
    def __init__(self, registry, parser, state, workflows):
        self.registry, self.parser, self.state = registry, parser, state
        self.workflows = {}
        for workflow in deepcopy(list(workflows)):
            workflow.validate(registry)
            entry_tool = workflow.steps[0].tool
            if entry_tool in self.workflows:
                raise ValueError("A parsed tool must identify one unambiguous workflow.")
            self.workflows[entry_tool] = workflow

    def capabilities(self):
        return self.registry.list_tools()

    def _record(self, snapshot, step, status):
        snapshot["current_task"] = step
        snapshot["steps"][step] = status
        snapshot["events"].append({"step": step, "status": status, "time": time.time()})
        self.state.save(snapshot)

    def _finish(self, snapshot, status, errors=(), *, database_state="FAILED"):
        snapshot.update(status=status, success=status == "completed")
        snapshot["errors"].extend(deepcopy(list(errors)))
        snapshot["steps"] = {k: "skipped" if v == "pending" else v for k, v in snapshot["steps"].items()}
        self.state.save(snapshot, database_state)
        return deepcopy(snapshot)

    def run(self, text, *, project_id, profile_name=None):
        if not isinstance(project_id, str) or not project_id.strip():
            return {"success": False, "status": "invalid_input", "errors": [error("invalid_project", "Project identity is required.")]}
        snapshot = None
        try:
            snapshot = self.state.begin(project_id)
            self._record(snapshot, "parse", "running")
            parsed = self.parser.parse(text, project_id=project_id, profile_name=profile_name)
            if not isinstance(parsed, ParseResult):
                raise ValueError("Parser must return ParseResult.")
            if parsed.status not in {"ready", "needs_input", "invalid_input", "invalid_output", "error"}:
                raise ValueError("Unknown parser status.")
            if parsed.status == "ready" and (parsed.errors or parsed.missing_fields):
                raise ValueError("A ready parser result cannot contain errors or missing fields.")
            snapshot["parse_result"] = parsed.to_dict()
            if parsed.status != "ready":
                self._record(snapshot, "parse", "needs_input" if parsed.status == "needs_input" else "failed")
                return self._finish(snapshot, parsed.status, parsed.errors)
            envelope = deepcopy(parsed.envelope)
            if not isinstance(envelope, dict) or envelope.get("project_id") != project_id:
                raise ValueError("Parsed project identity differs from the request.")
            workflow = self.workflows.get(envelope.get("tool"))
            if workflow is None:
                self._record(snapshot, "parse", "failed")
                return self._finish(snapshot, "failed", [error("workflow_unavailable", "No registered workflow for the parsed tool.")])
            self.registry.get(envelope["tool"]).validate(envelope)
            snapshot["workflow"] = workflow.name
            snapshot["steps"].update({step.name: "pending" for step in workflow.steps})
            self._record(snapshot, "parse", "completed")
            results = {}
            for index, step in enumerate(workflow.steps):
                self._record(snapshot, step.name, "running")
                tool = self.registry.get(step.tool)
                if index == 0:
                    request = deepcopy(envelope)
                else:
                    parameters = deepcopy(step.parameters)
                    try:
                        for parameter, binding in step.bindings.items():
                            value = results[binding.step]
                            for segment in binding.path:
                                value = value[segment]
                            parameters[parameter] = deepcopy(value)
                    except (KeyError, IndexError, TypeError):
                        self._record(snapshot, step.name, "failed")
                        return self._finish(snapshot, "failed", [error("result_binding_failed", "A required prior result field is missing.", (step.name,))])
                    request = {"project_id": project_id, "tool": step.tool,
                               "context": deepcopy(envelope["context"]), "parameters": parameters}
                tool.validate(request)
                # Persist the external-effect intent BEFORE calling a plugin. A crash cannot be
                # confused with a cleanly completed workflow or automatically replayed.
                snapshot["external_started"] = step.external_effects
                snapshot["tool_calls"].append({"step": step.name, "tool": tool.name, "version": tool.version, "status": "running"})
                self.state.save(snapshot)
                result = tool.execute(request)
                if not isinstance(result, ToolResult) or result.tool != tool.name or result.version != tool.version:
                    raise ValueError("Tool returned an inconsistent result envelope.")
                data = result.to_dict()
                if "recovery_required" in result.metadata and type(result.metadata["recovery_required"]) is not bool:
                    raise ValueError("recovery_required metadata must be a boolean.")
                if result.success:
                    validate_json(result.result, make_validator(tool.output_schema))
                path = self.state.publish_result(snapshot["run_id"], step.name, data)
                snapshot["tool_calls"][-1].update(status="completed" if result.success else "failed", result_path=path)
                snapshot["warnings"].extend(w for w in result.warnings if w not in snapshot["warnings"])
                recovery_required = result.metadata.get("recovery_required") is True or (
                    not result.success and step.external_effects and result.metadata.get("recovery_required") is not False)
                snapshot["external_started"] = recovery_required
                if not result.success or recovery_required:
                    self._record(snapshot, step.name, "failed")
                    return self._finish(snapshot, "recovery_required" if recovery_required else "failed",
                        result.errors or [error("recovery_required", "Tool reported pending external recovery.")],
                        database_state="RECOVERY_REQUIRED" if recovery_required else "FAILED")
                results[step.name] = data
                snapshot["artifacts"].extend(deepcopy(result.artifacts))
                self._record(snapshot, step.name, "completed")
            return self._finish(snapshot, "completed", database_state="COMPLETED")
        except KeyboardInterrupt:
            return self._abort(snapshot, "interrupted", [error("interrupted", "Workflow interrupted; no steps are automatically replayed.")])
        except ToolValidationError as exc:
            return self._abort(snapshot, "failed", exc.errors)
        except Exception as exc:
            # Raw exception messages may include parser input, provider internals or credentials.
            return self._abort(snapshot, "failed", [error("workflow_error", f"Workflow stopped ({type(exc).__name__}). Inspect the last durable step.")])

    def _abort(self, snapshot, status, errors):
        if snapshot is None:
            return {"success": False, "status": "error", "errors": list(errors), "state_saved": False}
        recovery = snapshot["external_started"]
        for key, value in snapshot["steps"].items():
            if value == "running":
                snapshot["steps"][key] = "interrupted" if status == "interrupted" else "failed"
                snapshot["events"].append({"step": key, "status": snapshot["steps"][key], "time": time.time()})
        if snapshot["tool_calls"] and snapshot["tool_calls"][-1]["status"] == "running":
            snapshot["tool_calls"][-1]["status"] = "interrupted" if status == "interrupted" else "failed"
        try:
            return self._finish(snapshot, "recovery_required" if recovery else status, errors,
                                database_state="RECOVERY_REQUIRED" if recovery else "INTERRUPTED" if status == "interrupted" else "FAILED")
        except Exception:
            # Do not execute further tools after losing durable state. Report this explicitly.
            snapshot.update(success=False, status="recovery_required" if recovery else "error", state_saved=False)
            snapshot["errors"] = list(errors) + [error("state_save_failed", "Cannot save workflow state; inspect the previous durable record before retrying.")]
            return deepcopy(snapshot)
