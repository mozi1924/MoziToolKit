"""
Operator for exporting an MTK Scene Interchange package (.mtkscene).
"""

from __future__ import annotations

import logging
from pathlib import Path

try:
    import bpy
    from bpy.props import BoolProperty, IntProperty, StringProperty
    from bpy_extras.io_utils import ExportHelper
    HAS_BPY = True
except ImportError:
    bpy = None
    ExportHelper = object
    BoolProperty = IntProperty = StringProperty = lambda **kwargs: None
    HAS_BPY = False

from ...bridge.point_cloud import extract_voxel_point_cloud
from ...bridge.scene import export_scene_package
from ...utils.mesh.ownership import find_voxel_cloud
from ...utils.system.dependencies import get_prefs

logger = logging.getLogger("MoziToolKit.Operators.Scene.Export")


class MOZI_OT_export_scene(bpy.types.Operator, ExportHelper):
    """Export selected world mesh or companion point cloud to an MTK Scene package (.mtkscene)"""

    bl_idname = "mozi.export_scene"
    bl_label = "Export MTK Scene (.mtkscene)"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".mtkscene"
    filter_glob: StringProperty(  # type: ignore
        default="*.mtkscene",
        options={"HIDDEN"},
    )

    max_atlas_size: IntProperty(  # type: ignore
        name="Max Atlas Size",
        description="Maximum dimension (width and height) for the cropped Scene Mini-Atlas",
        default=2048,
        min=256,
        max=8192,
    )

    @classmethod
    def poll(cls, context):
        if not HAS_BPY or context is None:
            return False
        active = getattr(context, "active_object", None)
        if active is None:
            if hasattr(cls, "poll_message_set"):
                cls.poll_message_set("Select an MTK world mesh, scene container, or companion point cloud")
            return False
        cloud = find_voxel_cloud(active)
        if cloud is None:
            if hasattr(cls, "poll_message_set"):
                cls.poll_message_set("Active object has no companion Voxel Point Cloud")
            return False
        return True

    def execute(self, context):
        if not HAS_BPY:
            return {"CANCELLED"}

        active = context.active_object
        cloud_obj = find_voxel_cloud(active)
        if cloud_obj is None:
            self.report({"ERROR"}, "No companion Voxel Point Cloud found on active object.")
            return {"CANCELLED"}

        point_cloud = extract_voxel_point_cloud(cloud_obj)
        if point_cloud is None or point_cloud.is_empty():
            self.report({"ERROR"}, "Companion Voxel Point Cloud is empty or unavailable.")
            return {"CANCELLED"}

        prefs = get_prefs(context)

        try:
            meta = export_scene_package(
                output_path=self.filepath,
                point_cloud=point_cloud,
                prefs=prefs,
                max_atlas_size=self.max_atlas_size,
            )
            v_count = meta.get("voxel_count", 0)
            res = meta.get("atlas_resolution", [0, 0])
            self.report(
                {"INFO"},
                f"Exported MTK Scene '{Path(self.filepath).name}' ({v_count} voxels, mini-atlas {res[0]}x{res[1]}).",
            )
            return {"FINISHED"}
        except Exception as e:
            logger.exception("Failed exporting scene package: %s", e)
            self.report({"ERROR"}, f"Failed exporting scene package: {e}")
            return {"CANCELLED"}
