"""
Mesh Face Culling Operator for MoziToolKit.

High-performance spatial-hashing based occlusion culling for imported external geometries backed strictly by Rust libmtk.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, FloatProperty

try:
    from ..bridge.cull import cull_mesh_faces
    from ..bridge.mesh import extract_mesh_data, inject_mesh_data
    from ..utils.mesh.core import (
        poll_edit_mesh,
        poll_mesh_object,
    )
    from ..utils.system.menu_registry import register_menu_item
except (ImportError, ValueError):
    from bridge.cull import cull_mesh_faces
    from bridge.mesh import extract_mesh_data, inject_mesh_data
    from utils.mesh.core import (
        poll_edit_mesh,
        poll_mesh_object,
    )
    from utils.system.menu_registry import register_menu_item


@register_menu_item(views=["mesh", "object"], label="Cull Occluded Faces")
class MOZI_OT_cull_mesh_faces(bpy.types.Operator):
    """Cull interior contacting faces and duplicate polygons from selected meshes via Rust libmtk"""

    bl_idname = "mozi.cull_mesh_faces"
    bl_label = "Cull Occluded Faces"
    bl_options = {"REGISTER", "UNDO"}

    tolerance: FloatProperty(
        name="Distance Tolerance",
        description="Maximum distance threshold to consider faces contacting/coplanar",
        default=1e-3,
        min=1e-6,
        max=1e-1,
    )

    cull_coplanar_opposite: BoolProperty(
        name="Cull Interior Contacting Faces",
        description="Remove back-to-back faces between adjacent blocks",
        default=True,
    )

    cull_duplicates: BoolProperty(
        name="Cull Duplicate Overlapping Faces",
        description="Remove identical overlapping faces with identical normal",
        default=True,
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

        total_in = 0
        total_culled = 0
        total_out = 0

        try:
            for obj in target_objs:
                mesh_data = extract_mesh_data(obj)
                culled_mesh, stats = cull_mesh_faces(
                    mesh_data,
                    tolerance=self.tolerance,
                    cull_coplanar_opposite=self.cull_coplanar_opposite,
                    cull_duplicates=self.cull_duplicates,
                )

                culled_count = stats.get("culled_faces", 0)
                if culled_count > 0:
                    inject_mesh_data(culled_mesh, obj, update_topology=True)
                total_in += stats.get("initial_faces", 0)
                total_culled += culled_count
                total_out += stats.get("remaining_faces", 0)
        finally:
            if saved_mode != "OBJECT":
                try:
                    bpy.ops.object.mode_set(mode=saved_mode)
                except Exception:
                    pass

        self.report(
            {"INFO"},
            f"Face Culling: Culled {total_culled} faces ({total_in} -> {total_out}) across {len(target_objs)} object(s).",
        )
        return {"FINISHED"}


OPERATOR_CLASSES = (MOZI_OT_cull_mesh_faces,)
