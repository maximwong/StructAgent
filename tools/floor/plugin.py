"""Floor composition/configuration; the generic controller never imports this module."""

from pathlib import Path

from agent.workflow import ResultBinding, Workflow, WorkflowStep
from agent.revision import BoundedRevisionTool, RevisionSpec
from .cad_adapter import FloorCADAdapter
from .cad_tool import FloorCADTool
from .design_store import FloorDesignStore
from .design_tool import FloorDesignTool
from .check_tool import FloorCheckTool
from .revision_tool import FloorRevisionProposalTool, CHANGES_SCHEMA
from .schemas import CONTEXT_SCHEMA, EXPLICIT_PARAMETERS


def register_floor_workflow(registry, output_root, *, cad_timeout=240, cad_backend=None):
    root = Path(output_root)
    store = FloorDesignStore(root / "designs")
    registry.register(FloorDesignTool(store=store))
    registry.register(FloorCheckTool(store))
    registry.register(FloorCADTool(store, FloorCADAdapter(root / "cad", timeout_seconds=cad_timeout, backend=cad_backend)))
    return Workflow("floor_design", (
        WorkflowStep("design", "design_floor_system"),
        WorkflowStep("check", "check_floor_design",
                     bindings={"design_result_ref": ResultBinding("design", ("metadata", "design_result_ref"))}),
        WorkflowStep("cad", "generate_floor_cad", external_effects=True,
                         bindings={"design_result_ref": ResultBinding("check", ("result", "design_result_ref"))}),
    ))


def register_floor_revision_workflow(registry, output_root, *, cad_timeout=240, cad_backend=None):
    """Explicit opt-in composition. Ordinary floor workflow keeps its existing behavior."""
    register_floor_workflow(registry, output_root, cad_timeout=cad_timeout, cad_backend=cad_backend)
    registry.register(FloorRevisionProposalTool())
    registry.register(BoundedRevisionTool(name='design_floor_with_revisions',
        description='在用户明确列出的尺寸候选内受限重设计，最多4轮；最终独立校核通过才允许出图。',
        registry=registry,root=Path(output_root)/'revisions',
        spec=RevisionSpec('design_floor_system','check_floor_design','propose_floor_revision',
            ('metadata','design_result_ref'),'design_result_ref',('result','design_result_ref'),
            ('design_rejected','design_check_failed')),
        initial_schema=EXPLICIT_PARAMETERS,changes_schema=CHANGES_SCHEMA,context_schema=CONTEXT_SCHEMA))
    return Workflow('floor_revision',(
        WorkflowStep('revision','design_floor_with_revisions'),
        WorkflowStep('cad','generate_floor_cad',external_effects=True,
            bindings={'design_result_ref':ResultBinding('revision',('result','final_reference'))}),
    ))
