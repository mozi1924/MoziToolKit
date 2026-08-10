import bpy
import numpy as np
from ...utils.mesh import (
    SELECTION_ACTION_ITEMS,
    SELECTION_SCOPE_ITEMS,
    apply_selection,
    bmesh_context,
    get_target_faces,
    poll_edit_mesh,
    set_select_mode,
)
from ...utils.uv import get_image_from_face
from ...utils.menu_config import register_menu_item


@register_menu_item(views=["mesh", "uv"])
class MOZI_OT_select_transparent_faces(bpy.types.Operator):
    """Select mesh faces mapped to transparent texture pixels"""

    bl_idname = "mozi.select_transparent_faces"
    bl_label = "Select Transparent Faces"
    bl_options = {"REGISTER", "UNDO"}

    alpha_threshold: bpy.props.FloatProperty(
        name="Alpha Threshold",
        description="Alpha threshold to consider transparent (<= threshold)",
        default=0.01,
        min=0.0,
        max=1.0,
        precision=3,
    )

    sample_mode: bpy.props.EnumProperty(
        name="Sample Mode",
        description="Sampling strategy for face transparency",
        items=[
            ("CENTER", "Center", "Sample alpha at the UV geometric center of the face"),
            ("ALL_CORNERS", "All Corners & Center", "Check corners and center (all must be transparent)"),
            ("AVERAGE", "Average", "Average alpha of face UV bounds/corners"),
        ],
        default="CENTER",
    )

    selection_mode: bpy.props.EnumProperty(
        name="Selection Action",
        description="How to modify the current face selection",
        items=SELECTION_ACTION_ITEMS,
        default="SET",
    )

    selection_scope: bpy.props.EnumProperty(
        name="Selection Scope",
        description="Filter which faces to check for transparency",
        items=SELECTION_SCOPE_ITEMS,
        default="ALL",
    )

    @classmethod
    def poll(cls, context):
        return poll_edit_mesh(context)

    def execute(self, context):
        params = {
            "alpha_threshold": self.alpha_threshold,
            "sample_mode": self.sample_mode,
            "selection_mode": self.selection_mode,
            "selection_scope": self.selection_scope,
        }
        from ...pipeline.presets import run_preset_pipeline

        res, ctx = run_preset_pipeline("select_transparent_faces", context, params)
        for level, msg in ctx.reports:
            self.report({level}, msg)

        if not res.is_success:
            return {"CANCELLED"}
        return {"FINISHED"}
