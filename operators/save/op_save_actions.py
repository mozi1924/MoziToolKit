"""
MoziToolKit Operators for Minecraft Save Container Configuration Actions.
Provides operators to reload Yefira mod selection and reset re-mesh settings.
"""

from __future__ import annotations

import logging
from typing import Optional

try:
    import bpy
except ImportError:
    bpy = None

from ...utils.save import load_yefira_selection
from ...utils.system.save_registry import get_save_registry
from .properties import (
    get_save_properties,
    sync_save_properties_from_object,
)
from .utils import resolve_save_container

logger = logging.getLogger("MoziToolKit.Operators.Save.Actions")


class MOZI_OT_save_load_yefira_selection(bpy.types.Operator if bpy else object):
    """Load latest selection bounds and dimension from yefira_selection.json in the save folder"""

    bl_idname = "mozi.save_load_yefira_selection"
    bl_label = "Load Yefira Selection"
    bl_description = "Read bounding coordinates and dimension from yefira_selection.json in the save folder"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not context:
            return False
        active = getattr(context, "active_object", None)
        root, mesh, _ = resolve_save_container(active)
        target = root or mesh
        if not target or not hasattr(target, "get"):
            return False
        save_uuid = target.get("mozi_save_uuid") or target.get("mtk:container_id")
        if not save_uuid:
            return False
        try:
            reg = get_save_registry()
            world_dir = reg.get_world_dir(str(save_uuid))
            return bool(world_dir and (world_dir / "yefira_selection.json").is_file())
        except Exception:
            return False

    def execute(self, context):
        active = getattr(context, "active_object", None)
        root, mesh, _ = resolve_save_container(active)
        target = root or mesh
        if not target:
            self.report({"WARNING"}, "No valid save container selected.")
            return {"CANCELLED"}

        save_uuid = target.get("mozi_save_uuid") or target.get("mtk:container_id")
        reg = get_save_registry()
        world_dir = reg.get_world_dir(str(save_uuid))
        if not world_dir:
            self.report({"WARNING"}, "Local save directory not linked.")
            return {"CANCELLED"}

        selection = load_yefira_selection(world_dir)
        if not selection:
            self.report({"WARNING"}, "Could not read yefira_selection.json.")
            return {"CANCELLED"}

        props = get_save_properties(target)
        if not props:
            self.report({"ERROR"}, "Failed to access save properties.")
            return {"CANCELLED"}

        props.min_coord = tuple(selection.min_coord)
        props.max_coord = tuple(selection.max_coord)
        dim = selection.dimension.strip().lower()
        if dim in ("overworld", "the_nether", "the_end"):
            props.dimension = dim
        elif "nether" in dim:
            props.dimension = "the_nether"
        elif "end" in dim:
            props.dimension = "the_end"
        props.is_dirty = True

        self.report(
            {"INFO"},
            f"Loaded Yefira selection: {selection.size[0]}×{selection.size[1]}×{selection.size[2]} ({selection.volume:,} blocks)",
        )
        return {"FINISHED"}


class MOZI_OT_save_reset_settings(bpy.types.Operator if bpy else object):
    """Reset re-mesh settings back to the currently loaded model geometry"""

    bl_idname = "mozi.save_reset_settings"
    bl_label = "Reset Settings"
    bl_description = "Discard unapplied re-mesh settings and revert to currently loaded model values"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not context:
            return False
        active = getattr(context, "active_object", None)
        root, mesh, _ = resolve_save_container(active)
        target = root or mesh
        if not target:
            return False
        props = get_save_properties(target, ensure_synced=False)
        return bool(props and getattr(props, "is_dirty", False))

    def execute(self, context):
        active = getattr(context, "active_object", None)
        root, mesh, _ = resolve_save_container(active)
        target = root or mesh
        if not target:
            return {"CANCELLED"}
        props = get_save_properties(target, ensure_synced=False)
        if props:
            sync_save_properties_from_object(props, target)
            props.is_dirty = False
            self.report({"INFO"}, "Reverted settings to current model geometry.")
            return {"FINISHED"}
        return {"CANCELLED"}


OPERATOR_CLASSES = (
    MOZI_OT_save_load_yefira_selection,
    MOZI_OT_save_reset_settings,
)
