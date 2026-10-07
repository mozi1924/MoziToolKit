"""
MoziToolKit Operator: Relink Local Minecraft Save Folder.

Allows relinking an imported Minecraft Save container to a local world folder,
restoring seamless model refresh capability when working across multiple
machines or when a save was moved.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

try:
    import bpy
    from bpy.props import BoolProperty, StringProperty
    from bpy_extras.io_utils import ImportHelper
except ImportError:
    bpy = None
    ImportHelper = object

try:
    from ...utils.system.save_registry import get_save_registry
except (ImportError, ValueError):
    from utils.system.save_registry import get_save_registry

from .utils import resolve_save_container

logger = logging.getLogger("MoziToolKit.Operators.Save.Relink")


class MOZI_OT_relink_save_folder(bpy.types.Operator, ImportHelper):
    """Relink an imported Save container to a local Minecraft world save folder"""

    bl_idname = "mozi.relink_save_folder"
    bl_label = "Relink Save Folder"
    bl_description = "Select the local Minecraft save directory for this world container"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(
        name="World Folder",
        description="Select the Minecraft world save folder containing level.dat or region files",
        subtype="DIR_PATH",
    )  # type: ignore

    filter_folder: BoolProperty(
        default=True,
        options={"HIDDEN"},
    )  # type: ignore

    target_uuid: StringProperty(
        name="Save UUID",
        description="UUID of the save container to relink",
        default="",
        options={"HIDDEN"},
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        if not context:
            return False
        active = getattr(context, "active_object", None)
        root, mesh, _ = resolve_save_container(active)
        target = root or mesh
        if not target or not hasattr(target, "get"):
            return False
        return bool(target.get("mozi_save_uuid") or target.get("mtk:container_id"))

    def invoke(self, context, event):
        if not self.target_uuid:
            active = getattr(context, "active_object", None)
            root, mesh, _ = resolve_save_container(active)
            target = root or mesh
            if target and hasattr(target, "get"):
                self.target_uuid = str(target.get("mozi_save_uuid") or target.get("mtk:container_id") or "")
        return super().invoke(context, event)

    def execute(self, context):
        folder = self.directory or getattr(self, "filepath", "")
        if not folder:
            self.report({"ERROR"}, "Please select a valid folder.")
            return {"CANCELLED"}

        path = Path(folder)
        if path.is_file():
            path = path.parent

        if not path.exists() or not path.is_dir():
            self.report({"ERROR"}, f"Folder does not exist: {path}")
            return {"CANCELLED"}

        # Validate that it looks like a Minecraft world
        has_level = (path / "level.dat").exists()
        has_region = (path / "region").exists() or (path / "dimensions").exists()
        if not (has_level or has_region):
            self.report(
                {"WARNING"},
                f"Selected folder does not appear to contain level.dat or region files: {path.name}",
            )

        save_uuid = self.target_uuid
        if not save_uuid:
            active = getattr(context, "active_object", None)
            root, mesh, _ = resolve_save_container(active)
            target = root or mesh
            if target and hasattr(target, "get"):
                save_uuid = str(target.get("mozi_save_uuid") or target.get("mtk:container_id") or "")

        if not save_uuid:
            self.report({"ERROR"}, "Could not determine save container UUID.")
            return {"CANCELLED"}

        registry = get_save_registry()
        registry.relink_save(save_uuid, path)

        self.report({"INFO"}, f"Successfully relinked world folder to: {path.name}")
        return {"FINISHED"}


OPERATOR_CLASSES = (
    MOZI_OT_relink_save_folder,
)
