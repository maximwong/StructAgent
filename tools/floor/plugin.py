"""Floor composition/configuration; the generic controller never imports this module."""

from pathlib import Path

from agent.workflow import ResultBinding, Workflow, WorkflowStep
from .cad_adapter import FloorCADAdapter
from .cad_tool import FloorCADTool
from .design_store import FloorDesignStore
from .design_tool import FloorDesignTool


def register_floor_workflow(registry, output_root, *, cad_timeout=240, cad_backend=None):
    root = Path(output_root)
    store = FloorDesignStore(root / "designs")
    registry.register(FloorDesignTool(store=store))
    registry.register(FloorCADTool(store, FloorCADAdapter(root / "cad", timeout_seconds=cad_timeout, backend=cad_backend)))
    return Workflow("floor_design", (
        WorkflowStep("design", "design_floor_system"),
        WorkflowStep("cad", "generate_floor_cad", external_effects=True,
                     bindings={"design_result_ref": ResultBinding("design", ("metadata", "design_result_ref"))}),
    ))
