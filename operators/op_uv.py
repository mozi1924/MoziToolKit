"""
UV Editing and Utility Operators for MoziToolKit.
"""

from __future__ import annotations

import bpy
from bpy.props import FloatProperty, EnumProperty

try:
    from ..utils.mesh import (
        bmesh_context,
        get_face_uv_center,
        poll_edit_mesh,
    )
    from ..utils.system import register_menu_item
except (ImportError, ValueError):
    from utils.mesh import (
        bmesh_context,
        get_face_uv_center,
        poll_edit_mesh,
    )
    from utils.system import register_menu_item


@register_menu_item(views=["uv", "mesh"], label="Scale UV Faces")
class MOZI_OT_scale_uv(bpy.types.Operator):
    """Scale individual UV faces in place around their UV center"""

    bl_idname = "mozi.scale_uv"
    bl_label = "Scale UV Faces"
    bl_options = {"REGISTER", "UNDO"}

    scale_factor: FloatProperty(
        name="Scale Factor",
        description="Scale factor relative to face UV center",
        default=0.8,
        min=0.0,
        max=10.0,
        step=1,
        precision=3,
    )

    selection_scope: EnumProperty(
        name="Selection Scope",
        description="Which faces to scale",
        items=[
            ("AUTO", "Auto (Selected or All)", "Scale selected faces if any, otherwise all faces"),
            ("SELECTED", "Selected Only", "Scale only selected faces"),
            ("ALL", "All Faces", "Scale all faces"),
        ],
        default="AUTO",
    )

    @classmethod
    def poll(cls, context):
        return poll_edit_mesh(context)

    def execute(self, context):
        scaled_faces_count = 0
        with bmesh_context(context) as (obj, bm):
            uv_layer = bm.loops.layers.uv.verify()

            selected_faces = [f for f in bm.faces if f.select]
            if self.selection_scope == "SELECTED":
                target_faces = selected_faces
            elif self.selection_scope == "ALL":
                target_faces = list(bm.faces)
            else:  # AUTO
                target_faces = selected_faces if selected_faces else list(bm.faces)

            if not target_faces:
                self.report({"WARNING"}, "No faces available to scale UV.")
                return {"CANCELLED"}

            for face in target_faces:
                uv_center = get_face_uv_center(face, uv_layer)
                for loop in face.loops:
                    uv = loop[uv_layer].uv
                    loop[uv_layer].uv = uv_center + (uv - uv_center) * self.scale_factor
                scaled_faces_count += 1

        self.report({"INFO"}, f"Scaled UV for {scaled_faces_count} face(s) by factor {self.scale_factor:.3f}")
        return {"FINISHED"}


OPERATORS_CLASSES = (
    MOZI_OT_scale_uv,
)
