"""
Operator to select hard and sharp edges on mesh objects.
"""

from __future__ import annotations

import math
import numpy as np
import bpy
from bpy.props import EnumProperty, FloatProperty

try:
    from ...utils.mesh import (
        SELECTION_ACTION_ITEMS,
        apply_selection,
        bmesh_context,
        poll_edit_mesh,
        poll_mesh_object,
        set_select_mode,
    )
    from ...utils.system import register_menu_item
    from ...bridge.mesh import analyze_mesh_hard_edges
except (ImportError, ValueError):
    from utils.mesh import (
        SELECTION_ACTION_ITEMS,
        apply_selection,
        bmesh_context,
        poll_edit_mesh,
        poll_mesh_object,
        set_select_mode,
    )
    from utils.system import register_menu_item
    from bridge.mesh import analyze_mesh_hard_edges


@register_menu_item(views=["mesh"], label="Select Hard & Sharp Edges")
class MOZI_OT_select_hard_edges(bpy.types.Operator):
    """Select boundary edges, sharp marked edges, and edges exceeding sharp angle threshold"""

    bl_idname = "mozi.select_hard_edges"
    bl_label = "Select Hard & Sharp Edges"
    bl_options = {"REGISTER", "UNDO"}

    sharp_angle: FloatProperty(
        name="Sharp Angle",
        description="Angle in degrees above which edges are considered sharp",
        default=30.0,
        min=0.0,
        max=180.0,
        unit="ROTATION",
    )

    selection_mode: EnumProperty(
        name="Selection Action",
        description="How to modify the current edge selection",
        items=SELECTION_ACTION_ITEMS,
        default="SET",
    )

    @classmethod
    def poll(cls, context):
        return poll_edit_mesh(context) or poll_mesh_object(context)

    def execute(self, context):
        set_select_mode(context, "EDGE")
        sharp_angle_rad = math.radians(self.sharp_angle)

        is_edit = (getattr(context, "mode", "OBJECT") == "EDIT_MESH")
        obj = context.active_object or (context.selected_objects[0] if context.selected_objects else None)
        if not obj or obj.type != "MESH":
            self.report({"WARNING"}, "No active mesh object.")
            return {"CANCELLED"}

        mesh = obj.data
        if is_edit and hasattr(obj, "update_from_editmode"):
            obj.update_from_editmode()

        mask = analyze_mesh_hard_edges(mesh, sharp_angle_rad=sharp_angle_rad)
        if mask is None or len(mask) != len(mesh.edges):
            self.report({"ERROR"}, "Failed to analyze hard edges via Rust libmtk.")
            return {"CANCELLED"}

        selected_count = int(np.count_nonzero(mask))
        if is_edit:
            with bmesh_context(context, flush_selection=True) as (_, bm):
                bm.edges.ensure_lookup_table()
                hard_indices = set(np.where(mask != 0)[0].tolist())
                if self.selection_mode == "SET":
                    for i, e in enumerate(bm.edges):
                        e.select = i in hard_indices
                elif self.selection_mode == "ADD":
                    for i in hard_indices:
                        bm.edges[i].select = True
                elif self.selection_mode == "SUBTRACT":
                    for i in hard_indices:
                        bm.edges[i].select = False
        else:
            if self.selection_mode == "SET":
                mesh.edges.foreach_set("select", mask)
            elif self.selection_mode == "ADD":
                current_sel = np.empty(len(mesh.edges), dtype=np.uint8)
                mesh.edges.foreach_get("select", current_sel)
                mesh.edges.foreach_set("select", np.bitwise_or(current_sel, mask))
            elif self.selection_mode == "SUBTRACT":
                current_sel = np.empty(len(mesh.edges), dtype=np.uint8)
                mesh.edges.foreach_get("select", current_sel)
                mesh.edges.foreach_set("select", np.bitwise_and(current_sel, ~mask))
            mesh.update()

        self.report({"INFO"}, f"Selected {selected_count} hard/sharp edge(s)")
        return {"FINISHED"}
