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
from ...bridge.world import (
    get_world_session_dynamic_entity_atlases,
    resolve_dynamic_entity_atlases,
)
from ...utils.mesh.ownership import find_voxel_cloud, is_point_cloud
from ...utils.system.dependencies import get_prefs

logger = logging.getLogger("MoziToolKit.Operators.Scene.Export")


def _resolve_export_dynamic_entities(active_obj: Any, cloud_obj: Any) -> Optional[dict[int, bytes]]:
    """Resolves dynamic entity atlas buffers (0xFFF0) from sessions, properties, or Blender images."""
    if not HAS_BPY:
        return None

    # 1. Probe session key on active, cloud, or parent container
    session_key = (
        active_obj.get("mtk:session_key")
        if hasattr(active_obj, "get")
        else None
    ) or (
        cloud_obj.get("mtk:session_key")
        if hasattr(cloud_obj, "get")
        else None
    )
    if not session_key and hasattr(active_obj, "parent") and active_obj.parent:
        session_key = active_obj.parent.get("mtk:session_key") if hasattr(active_obj.parent, "get") else None

    if session_key:
        atlases = get_world_session_dynamic_entity_atlases(session_key)
        if atlases:
            return atlases

    # 2. Check if active or parent has dynamic entity image attached
    from ...utils.materials.builder.dynamic_entities import (
        DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID,
        DYNAMIC_CHUNK_END,
        DYNAMIC_CHUNK_START,
        dynamic_entities_image_name,
    )

    result: dict[int, bytes] = {}
    for cid in range(DYNAMIC_CHUNK_START, DYNAMIC_CHUNK_START + 1):  # 0xFFF0
        img_name = dynamic_entities_image_name(cid)
        img = bpy.data.images.get(img_name)
        if img is not None and len(img.pixels) == 1024 * 1024 * 4:
            try:
                import numpy as np

                floats = np.empty(len(img.pixels), dtype=np.float32)
                img.pixels.foreach_get(floats)
                # Reshape and flip back to canonical top-down Y layout
                pixels_2d = (floats.reshape(1024, 1024, 4) * 255.0).clip(0, 255).astype(np.uint8)
                pixels_top_down = np.ascontiguousarray(pixels_2d[::-1, :, :])
                result[cid] = pixels_top_down.tobytes()
            except Exception as e:
                logger.debug("Could not read dynamic entity pixels from Blender image: %s", e)

    return result if result else None


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
        dyn_entities = _resolve_export_dynamic_entities(active, cloud_obj)

        try:
            meta = export_scene_package(
                output_path=self.filepath,
                point_cloud=point_cloud,
                prefs=prefs,
                max_atlas_size=self.max_atlas_size,
                dynamic_entity_atlases=dyn_entities,
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
