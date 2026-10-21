"""
Operators for Voxel Point Cloud Management, Mask Modifier Visibility,
and User-Driven Carving.
"""

from __future__ import annotations

import logging
import bpy
from bpy.props import BoolProperty

logger = logging.getLogger("MoziToolKit.Operators.VoxelCloud")

from ..utils.point_cloud import (
    get_associated_parent_mesh,
    get_associated_voxel_cloud,
    is_voxel_cloud_visible,
    set_voxel_cloud_visibility,
)
from ..utils.system import register_menu_item


def _resolve_world_and_cloud_objects(context) -> tuple[Optional[bpy.types.Object], Optional[bpy.types.Object]]:
    """Resolves (world_mesh_obj, voxel_cloud_obj) from current context selection."""
    if context is None:
        return None, None
    active = getattr(context, "active_object", None)
    if active is None:
        selected = getattr(context, "selected_objects", [])
        active = selected[0] if selected else None
    if active is None:
        return None, None

    if getattr(active, "type", "") == "MESH":
        if active.get("mtk_is_voxel_cloud"):
            cloud_obj = active
            world_obj = get_associated_parent_mesh(active)
            return world_obj, cloud_obj

        cloud_obj = get_associated_voxel_cloud(active)
        return active, cloud_obj

    if getattr(active, "type", "") == "EMPTY":
        cloud_obj = get_associated_voxel_cloud(active)
        world_obj = None
        for child in getattr(active, "children", []):
            if getattr(child, "type", "") == "MESH" and not child.get("mtk_is_voxel_cloud"):
                world_obj = child
                break
        return world_obj, cloud_obj

    return None, None


def _enter_carve_mode(
    context: Any,
    world_obj: Optional[bpy.types.Object],
    cloud_obj: bpy.types.Object,
    report_fn: Optional[Any] = None,
) -> bool:
    """Safely transitions active selection to cloud_obj and enters Edit Mode."""
    # 1. Exit any other edit mode cleanly
    if getattr(context, "mode", "OBJECT") != "OBJECT":
        try:
            if hasattr(bpy.ops, "object") and hasattr(bpy.ops.object, "mode_set"):
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass

    # 2. Ensure cloud is unmasked and visible (never hide on carve enter!)
    set_voxel_cloud_visibility(cloud_obj, True)

    # 3. Focus active selection onto the cloud object
    if hasattr(context, "view_layer") and hasattr(context.view_layer, "objects"):
        context.view_layer.objects.active = cloud_obj
        if hasattr(cloud_obj, "select_set"):
            cloud_obj.select_set(True)
        if world_obj and world_obj != cloud_obj and hasattr(world_obj, "select_set"):
            world_obj.select_set(False)

    # 4. Switch to Edit Mode
    try:
        if hasattr(bpy.ops, "object") and hasattr(bpy.ops.object, "mode_set"):
            bpy.ops.object.mode_set(mode="EDIT")
    except Exception as e:
        logger.debug("Could not switch mode to EDIT on voxel cloud: %s", e)

    # 5. Set mesh select mode to Vertex only
    if hasattr(context, "tool_settings") and hasattr(context.tool_settings, "mesh_select_mode"):
        context.tool_settings.mesh_select_mode = (True, False, False)

    # 6. Enable X-Ray in 3D viewport for easy interior voxel box selection
    if hasattr(context, "space_data") and hasattr(context.space_data, "shading"):
        context.space_data.shading.show_xray = True

    if report_fn:
        report_fn(
            {"INFO"},
            f"Entered Voxel Carve Mode on '{cloud_obj.name}'. Delete vertices, then click Rebuild.",
        )
    return True


def _exit_carve_mode(
    context: Any,
    world_obj: Optional[bpy.types.Object],
    cloud_obj: bpy.types.Object,
    report_fn: Optional[Any] = None,
) -> bool:
    """Safely exits Edit Mode and restores active selection to world_obj."""
    if getattr(context, "mode", "OBJECT") != "OBJECT":
        try:
            if hasattr(bpy.ops, "object") and hasattr(bpy.ops.object, "mode_set"):
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass

    # Restore focus to world mesh
    if world_obj and hasattr(context, "view_layer") and hasattr(context.view_layer, "objects"):
        context.view_layer.objects.active = world_obj
        if hasattr(world_obj, "select_set"):
            world_obj.select_set(True)
        if hasattr(cloud_obj, "select_set"):
            cloud_obj.select_set(False)

    if report_fn:
        report_fn(
            {"INFO"},
            f"Exited Voxel Carve Mode. Click 'Rebuild Voxel Mesh' to apply changes.",
        )
    return True


@register_menu_item(views=["object", "mesh"], label="Toggle Voxel Point Cloud Visibility")
class MOZI_OT_toggle_voxel_cloud(bpy.types.Operator):
    """Toggle visibility of the associated voxel storage point cloud using the Mask modifier."""

    bl_idname = "mozi.toggle_voxel_cloud"
    bl_label = "Toggle Voxel Point Cloud Visibility"
    bl_options = {"REGISTER", "UNDO"}

    action: bpy.props.EnumProperty(
        name="Action",
        description="Action to perform on point cloud visibility",
        items=[
            ("TOGGLE", "Toggle", "Toggle visibility between shown and hidden"),
            ("SHOW", "Show", "Force show voxel point cloud (unmask)"),
            ("HIDE", "Hide", "Force hide voxel point cloud (mask)"),
        ],
        default="TOGGLE",
    )

    enter_edit_mode: BoolProperty(
        name="Enter Edit Mode",
        description="Automatically switch to Edit Mode on the voxel cloud to select and delete blocks",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        world_obj, cloud_obj = _resolve_world_and_cloud_objects(context)
        return cloud_obj is not None

    def execute(self, context):
        world_obj, cloud_obj = _resolve_world_and_cloud_objects(context)
        if cloud_obj is None:
            self.report({"WARNING"}, "No associated Voxel Point Cloud found for active object.")
            return {"CANCELLED"}

        # Backward compatibility: if caller requested enter_edit_mode, enter carve mode directly
        if getattr(self, "enter_edit_mode", False):
            _enter_carve_mode(context, world_obj, cloud_obj, report_fn=self.report)
            return {"FINISHED"}

        action = getattr(self, "action", "TOGGLE")
        currently_visible = is_voxel_cloud_visible(cloud_obj)
        if action == "SHOW":
            new_state = True
        elif action == "HIDE":
            new_state = False
        else:
            new_state = not currently_visible

        # If hiding cloud while currently editing it in 3D viewport, exit cleanly to Object Mode
        if not new_state and getattr(context, "mode", "OBJECT") != "OBJECT":
            if getattr(context, "active_object", None) == cloud_obj:
                _exit_carve_mode(context, world_obj, cloud_obj)

        set_voxel_cloud_visibility(cloud_obj, new_state)

        if new_state:
            self.report({"INFO"}, f"Voxel Cloud '{cloud_obj.name}' is now visible (Mask unmasked).")
        else:
            self.report({"INFO"}, f"Voxel Cloud '{cloud_obj.name}' is now masked and hidden.")

        return {"FINISHED"}


class MOZI_OT_carve_voxel_cloud(bpy.types.Operator):
    """
    Enter or exit Edit Mode on the associated voxel storage point cloud
    for direct vertex selection and carving deletion.
    """

    bl_idname = "mozi.carve_voxel_cloud"
    bl_label = "Carve Voxel Point Cloud"
    bl_description = "Enter or exit Edit Mode on the voxel point cloud to select and delete blocks"
    bl_options = {"REGISTER", "UNDO"}

    action: bpy.props.EnumProperty(
        name="Action",
        description="Carve mode action to perform",
        items=[
            ("TOGGLE", "Toggle", "Toggle between entering and exiting carve mode"),
            ("ENTER", "Enter", "Enter carve edit mode"),
            ("EXIT", "Exit", "Exit carve edit mode back to object mode"),
        ],
        default="TOGGLE",
    )

    @classmethod
    def poll(cls, context):
        world_obj, cloud_obj = _resolve_world_and_cloud_objects(context)
        return cloud_obj is not None

    def execute(self, context):
        world_obj, cloud_obj = _resolve_world_and_cloud_objects(context)
        if cloud_obj is None:
            self.report({"WARNING"}, "No associated Voxel Point Cloud found for active object.")
            return {"CANCELLED"}

        is_currently_carving = (
            getattr(context, "mode", "OBJECT") == "EDIT_MESH"
            and getattr(context, "active_object", None) == cloud_obj
        )

        action = getattr(self, "action", "TOGGLE")
        if action == "ENTER":
            target_enter = True
        elif action == "EXIT":
            target_enter = False
        else:
            target_enter = not is_currently_carving

        if target_enter:
            _enter_carve_mode(context, world_obj, cloud_obj, report_fn=self.report)
        else:
            _exit_carve_mode(context, world_obj, cloud_obj, report_fn=self.report)

        return {"FINISHED"}


OPERATOR_CLASSES = (
    MOZI_OT_toggle_voxel_cloud,
    MOZI_OT_carve_voxel_cloud,
)
