"""
Adaptive Pixel Split Operator for MoziToolKit.

High-performance pixel-density aware polygon subdivision backed strictly by Rust libmtk.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, IntVectorProperty

try:
    from ..bridge.mesh import extract_mesh_data, inject_mesh_data
    from ..bridge.subdivide import adaptive_pixel_split_mesh, calculate_face_target_grid
    from ..utils.mesh.core import (
        SELECTION_SCOPE_ITEMS,
        bmesh_context,
        poll_edit_mesh,
        poll_mesh_object,
    )
    from ..utils.system.menu_registry import register_menu_item
except (ImportError, ValueError):
    from bridge.mesh import extract_mesh_data, inject_mesh_data
    from bridge.subdivide import adaptive_pixel_split_mesh, calculate_face_target_grid
    from utils.mesh.core import (
        SELECTION_SCOPE_ITEMS,
        bmesh_context,
        poll_edit_mesh,
        poll_mesh_object,
    )
    from utils.system.menu_registry import register_menu_item


@register_menu_item(views=["mesh"], label="Adaptive Pixel Split")
class MOZI_OT_adaptive_pixel_split(bpy.types.Operator):
    """Subdivide mesh quad faces according to texture pixel density backed by Rust libmtk"""

    bl_idname = "mozi.adaptive_pixel_split"
    bl_label = "Adaptive Pixel Split"
    bl_options = {"REGISTER", "UNDO"}

    pixels_per_face: FloatProperty(
        name="Pixels Per Face",
        description="Target number of texture pixels per polygon edge (1.0 = 1 face per pixel)",
        default=1.0,
        min=0.1,
        max=64.0,
    )

    max_subdivisions: IntProperty(
        name="Max Subdivisions",
        description="Maximum subdivisions along each axis to prevent vertex explosion",
        default=64,
        min=1,
        max=256,
    )

    auto_resolution: BoolProperty(
        name="Auto Texture Resolution",
        description="Automatically inspect material image texture sizes",
        default=True,
    )

    manual_resolution: IntVectorProperty(
        name="Manual Resolution",
        description="Fallback texture dimensions (Width, Height)",
        default=(16, 16),
        size=2,
        min=1,
    )

    selection_scope: EnumProperty(
        name="Selection Scope",
        description="Faces to process",
        items=SELECTION_SCOPE_ITEMS,
        default="SELECTED",
    )

    weld_dist: FloatProperty(
        name="Weld Distance",
        description="Distance threshold to weld adjacent subdivided boundary vertices",
        default=1e-4,
        min=0.0,
        max=1e-2,
    )

    @classmethod
    def poll(cls, context):
        return poll_edit_mesh(context) or poll_mesh_object(context)

    def execute(self, context):
        target_objs = [o for o in context.selected_objects if o and o.type == "MESH"]
        if not target_objs and context.active_object and context.active_object.type == "MESH":
            target_objs = [context.active_object]

        if not target_objs:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        saved_mode = context.mode
        if saved_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        total_in_faces = 0
        total_out_faces = 0

        try:
            for obj in target_objs:
                mesh_data = extract_mesh_data(obj)
                total_in_faces += mesh_data.face_count

                # Collect texture resolutions per face if auto_resolution is enabled
                face_resolutions = []
                def_res = (self.manual_resolution[0], self.manual_resolution[1])

                if self.auto_resolution and obj.material_slots:
                    for slot_idx in mesh_data.face_materials:
                        res = def_res
                        if slot_idx < len(obj.material_slots):
                            slot = obj.material_slots[slot_idx]
                            if slot.material and slot.material.use_nodes:
                                for node in slot.material.node_tree.nodes:
                                    if node.type == "TEX_IMAGE" and node.image:
                                        img = node.image
                                        if img.size[0] > 0 and img.size[1] > 0:
                                            res = (img.size[0], img.size[1])
                                            break
                        face_resolutions.append(res)
                else:
                    face_resolutions = None

                # Subdivide via Rust core
                subdivided = adaptive_pixel_split_mesh(
                    mesh_data,
                    face_resolutions=face_resolutions,
                    default_resolution=def_res,
                    pixels_per_face=self.pixels_per_face,
                    max_subdivisions=self.max_subdivisions,
                    weld_dist=self.weld_dist,
                )

                inject_mesh_data(obj, subdivided)
                total_out_faces += subdivided.face_count
        finally:
            if saved_mode != "OBJECT":
                try:
                    bpy.ops.object.mode_set(mode=saved_mode)
                except Exception:
                    pass

        self.report(
            {"INFO"},
            f"Adaptive Pixel Split: {total_in_faces} -> {total_out_faces} faces across {len(target_objs)} object(s).",
        )
        return {"FINISHED"}


OPERATOR_CLASSES = (MOZI_OT_adaptive_pixel_split,)
