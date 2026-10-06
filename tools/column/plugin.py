"""Column-owned registration and declaration; construction has no side effects."""

from pathlib import Path

from agent.workflow import ResultBinding, Workflow, WorkflowStep
from .check_tool import ColumnCheckTool
from .design_store import ColumnDesignStore
from .design_tool import ColumnDesignTool


def register_column_workflow(registry, output_root):
    store = ColumnDesignStore(Path(output_root) / "column-designs")
    registry.register(ColumnDesignTool(store))
    registry.register(ColumnCheckTool(store))
    return Workflow("rc_column_design", (
        WorkflowStep("design", "design_column"),
        WorkflowStep("check", "check_column_design", bindings={
            "design_result_ref": ResultBinding("design", ("result", "design_result_ref")),
        }),
    ))
