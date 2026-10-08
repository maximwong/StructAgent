"""Column-owned registration and declaration; construction has no side effects."""

from pathlib import Path

from agent.workflow import ResultBinding, Workflow, WorkflowStep
from .check_tool import ColumnCheckTool
from .design_store import ColumnDesignStore
from .design_tool import ColumnDesignTool
from .combination_store import ColumnCombinationStore
from .combination_tools import ColumnCombinationDesignTool, ColumnCombinationCheckTool
from .layout_store import ColumnLayoutStore
from .layout_tools import ColumnLayoutDesignTool, ColumnLayoutCheckTool


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


def register_column_combinations(registry, output_root):
    store = ColumnCombinationStore(Path(output_root) / "column-combination-designs")
    registry.register(ColumnCombinationDesignTool(store))
    registry.register(ColumnCombinationCheckTool(store))
    return Workflow("rc_column_combinations", (
        WorkflowStep("design", "design_column_combinations"),
        WorkflowStep("check", "check_column_combinations", bindings={
            "design_result_ref": ResultBinding("design", ("result", "design_result_ref")),
        }),
    ))


def register_column_layouts(registry, output_root):
    store = ColumnLayoutStore(Path(output_root) / "column-layout-designs")
    registry.register(ColumnLayoutDesignTool(store))
    registry.register(ColumnLayoutCheckTool(store))
    return Workflow("rc_column_layouts", (
        WorkflowStep("design", "design_column_layouts"),
        WorkflowStep("check", "check_column_layouts", bindings={
            "design_result_ref": ResultBinding("design", ("result", "design_result_ref")),
        }),
    ))


def register_column_eccentric(registry, output_root):
    from .eccentric_store import ColumnEccentricStore
    from .eccentric_tools import ColumnEccentricDesignTool, ColumnEccentricCheckTool
    store = ColumnEccentricStore(Path(output_root) / "column-eccentric-designs")
    registry.register(ColumnEccentricDesignTool(store))
    registry.register(ColumnEccentricCheckTool(store))
    return Workflow("rc_column_eccentric", (
        WorkflowStep("design", "design_column_eccentric"),
        WorkflowStep("check", "check_column_eccentric", bindings={
            "design_result_ref": ResultBinding("design", ("result", "design_result_ref")),
        }),
    ))
