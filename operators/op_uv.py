"""
UV Editing and Utility Operators for MoziToolKit.
"""

from __future__ import annotations

import bpy
from bpy.props import FloatProperty, EnumProperty

try:
    from ..bridge import batch_analyze_transparent_faces
    from ..utils.mesh import (
        SELECTION_ACTION_ITEMS,
        SELECTION_SCOPE_ITEMS,
        apply_selection,
        bmesh_context,
        find_face_image,
        get_face_uv_center,
        get_target_faces,
        poll_edit_mesh,
        set_select_mode,
    )
    from ..utils.system import register_menu_item
except (ImportError, ValueError):
    from bridge import batch_analyze_transparent_faces
    from utils.mesh import (
        SELECTION_ACTION_ITEMS,
        SELECTION_SCOPE_ITEMS,
        apply_selection,
        bmesh_context,
        find_face_image,
        get_face_uv_center,
        get_target_faces,
        poll_edit_mesh,
        set_select_mode,
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


@register_menu_item(views=["mesh", "uv"], label="Select Transparent Faces")
class MOZI_OT_select_transparent_faces(bpy.types.Operator):
    """Select mesh faces mapped to transparent texture pixels"""

    bl_idname = "mozi.select_transparent_faces"
    bl_label = "Select Transparent Faces"
    bl_options = {"REGISTER", "UNDO"}

    alpha_threshold: FloatProperty(
        name="Alpha Threshold",
        description="Alpha threshold to consider transparent (<= threshold)",
        default=0.01,
        min=0.0,
        max=1.0,
        precision=3,
    )

    sample_mode: EnumProperty(
        name="Sample Mode",
        description="Sampling strategy for face transparency",
        items=[
            ("CENTER", "Center", "Sample alpha at the UV geometric center of the face"),
            ("ALL_CORNERS", "All Corners & Center", "Check corners and center (all must be transparent)"),
            ("AVERAGE", "Average", "Average alpha of face UV bounds/corners"),
        ],
        default="CENTER",
    )

    selection_mode: EnumProperty(
        name="Selection Action",
        description="How to modify the current face selection",
        items=SELECTION_ACTION_ITEMS,
        default="SET",
    )

    selection_scope: EnumProperty(
        name="Selection Scope",
        description="Filter which faces to check for transparency",
        items=SELECTION_SCOPE_ITEMS,
        default="ALL",
    )

    @classmethod
    def poll(cls, context):
        return poll_edit_mesh(context)

    def execute(self, context):
        set_select_mode(context, "FACE")

        transparent_faces_count = 0
        with bmesh_context(context, flush_selection=True) as (obj, bm):
            uv_layer = bm.loops.layers.uv.verify()
            target_faces = get_target_faces(bm, self.selection_scope)
            if not target_faces:
                self.report({"WARNING"}, "No faces found in specified selection scope.")
                return {"CANCELLED"}

            # Group faces by Image
            image_groups: dict[bpy.types.Image, list[tuple[bpy.types.BMFace, list[tuple[float, float]]]]] = {}
            for face in target_faces:
                img = find_face_image(face, obj, context)
                if not img or img.size[0] <= 0 or img.size[1] <= 0:
                    continue
                uvs = [(loop[uv_layer].uv.x, loop[uv_layer].uv.y) for loop in face.loops]
                if not uvs:
                    continue
                if img not in image_groups:
                    image_groups[img] = []
                image_groups[img].append((face, uvs))

            transparent_faces = []
            for img, face_data in image_groups.items():
                w, h = img.size[0], img.size[1]
                pixels = img.pixels[:]
                faces_list = [fd[0] for fd in face_data]
                uvs_list = [fd[1] for fd in face_data]
                results = batch_analyze_transparent_faces(
                    uvs_list,
                    w,
                    h,
                    pixels,
                    mode=self.sample_mode,
                    threshold=self.alpha_threshold,
                    invert_y=False,
                )
                for face, is_trans in zip(faces_list, results):
                    if is_trans:
                        transparent_faces.append(face)

            transparent_faces_count = len(transparent_faces)
            apply_selection(bm.faces, transparent_faces, self.selection_mode)

        self.report({"INFO"}, f"Selected {transparent_faces_count} transparent face(s)")
        return {"FINISHED"}


OPERATORS_CLASSES = (
    MOZI_OT_scale_uv,
    MOZI_OT_select_transparent_faces,
)
