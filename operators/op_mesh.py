"""
Mesh and Normal Management Operators for MoziToolKit.
"""

from __future__ import annotations

import math
import bpy
from bpy.props import EnumProperty, FloatProperty

try:
    from ..utils.mesh import (
        SELECTION_ACTION_ITEMS,
        apply_selection,
        bmesh_context,
        is_hard_edge,
        poll_edit_mesh,
        poll_mesh_object,
        set_select_mode,
    )
    from ..utils.system import register_menu_item
except (ImportError, ValueError):
    from utils.mesh import (
        SELECTION_ACTION_ITEMS,
        apply_selection,
        bmesh_context,
        is_hard_edge,
        poll_edit_mesh,
        poll_mesh_object,
        set_select_mode,
    )
    from utils.system import register_menu_item


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
        return poll_edit_mesh(context)

    def execute(self, context):
        set_select_mode(context, "EDGE")
        sharp_angle_rad = math.radians(self.sharp_angle)

        selected_count = 0
        with bmesh_context(context, flush_selection=True) as (obj, bm):
            hard_edges = [edge for edge in bm.edges if is_hard_edge(edge, sharp_angle_rad)]
            apply_selection(bm.edges, hard_edges, self.selection_mode)
            selected_count = len(hard_edges)

        self.report({"INFO"}, f"Selected {selected_count} hard/sharp edge(s)")
        return {"FINISHED"}


@register_menu_item(views=["mesh", "object"], label="Clear Custom Normals")
class MOZI_OT_clear_custom_normals(bpy.types.Operator):
    """Delete custom_normal attribute and clear custom split normals for selected mesh objects"""

    bl_idname = "mozi.clear_custom_normals"
    bl_label = "Clear Custom Normals"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return poll_mesh_object(context)

    def execute(self, context):
        targets = [obj for obj in context.selected_objects if obj and obj.type == "MESH"]
        if not targets and context.active_object and context.active_object.type == "MESH":
            targets = [context.active_object]

        if not targets:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        saved_mode = context.mode
        saved_active = context.view_layer.objects.active

        if saved_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        cleared_count = 0
        try:
            for obj in targets:
                mesh = obj.data
                had_custom = False

                attrs_to_remove = [
                    attr
                    for attr in mesh.attributes
                    if "custom_normal" in attr.name.lower()
                    or "custom normal" in attr.name.lower()
                    or attr.name.lower().replace("_", "").replace(" ", "") == "customnormal"
                ]
                for attr in attrs_to_remove:
                    mesh.attributes.remove(attr)
                    had_custom = True

                if mesh.has_custom_normals:
                    context.view_layer.objects.active = obj
                    bpy.ops.mesh.customdata_custom_splitnormals_clear()
                    had_custom = True

                if had_custom:
                    cleared_count += 1
        finally:
            if saved_active and saved_active.name in context.view_layer.objects:
                context.view_layer.objects.active = saved_active

            if saved_mode != "OBJECT":
                mode_to_set = "EDIT" if saved_mode == "EDIT_MESH" else saved_mode
                try:
                    bpy.ops.object.mode_set(mode=mode_to_set)
                except Exception:
                    pass

        if cleared_count == 0:
            self.report({"INFO"}, "No custom normals found on selected objects.")
        else:
            self.report({"INFO"}, f"Cleared custom normals from {cleared_count} object(s).")

        return {"FINISHED"}


OPERATORS_CLASSES = (
    MOZI_OT_select_hard_edges,
    MOZI_OT_clear_custom_normals,
)
