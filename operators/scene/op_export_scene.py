"""
Operator for exporting an MTK Scene Interchange package (.mtkscene).
"""

from __future__ import annotations

import json
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
    get_world_session_dynamic_entity_slots,
    resolve_dynamic_entity_atlases,
    resolve_dynamic_entity_slots,
)
from ...utils.mesh.ownership import find_voxel_cloud, is_point_cloud
from ...utils.system.dependencies import get_prefs

logger = logging.getLogger("MoziToolKit.Operators.Scene.Export")


def _resolve_export_dynamic_entities(active_obj: Any, cloud_obj: Any) -> Optional[dict[int, bytes]]:
    """Resolves dynamic entity atlas buffers (0xFFF0) via bridge.world.resolve_dynamic_entity_atlases."""
    if not HAS_BPY:
        return None

    # 1. Probe session key on active, cloud, or parent container
    session_key = (
        active_obj.get("mtk:session_key") or active_obj.get("mozi_save_uuid")
        if hasattr(active_obj, "get")
        else None
    ) or (
        cloud_obj.get("mtk:session_key") or cloud_obj.get("mozi_save_uuid")
        if hasattr(cloud_obj, "get")
        else None
    )
    if not session_key and hasattr(active_obj, "parent") and active_obj.parent:
        p = active_obj.parent
        session_key = (p.get("mtk:session_key") or p.get("mozi_save_uuid")) if hasattr(p, "get") else None

    if session_key:
        atlases = get_world_session_dynamic_entity_atlases(session_key)
        if atlases:
            return atlases

    # 2. Check mesh data on active or cloud object via bridge.world.resolve_dynamic_entity_atlases
    mesh_data = getattr(active_obj, "data", None)
    if mesh_data is not None:
        atlases = resolve_dynamic_entity_atlases(mesh_data)
        if atlases:
            return atlases

    cloud_data = getattr(cloud_obj, "data", None)
    if cloud_data is not None:
        atlases = resolve_dynamic_entity_atlases(cloud_data)
        if atlases:
            return atlases

    # 3. Fallback: extract from resident Blender dynamic entity images
    from ...utils.materials.builder.dynamic_entities import extract_resident_dynamic_entity_atlases
    return extract_resident_dynamic_entity_atlases()


def _decode_dynamic_entity_slots_payload(raw: Any) -> Optional[dict[str, tuple[int, int]]]:
    """Decodes a JSON dynamic-entity slot payload stored on a Blender object."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    slots: dict[str, tuple[int, int]] = {}
    for key, value in data.items():
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            try:
                slots[str(key)] = (int(value[0]), int(value[1]))
            except (TypeError, ValueError):
                continue
    return slots or None


def _embedded_dynamic_entity_slots(obj: Any) -> Optional[dict[str, tuple[int, int]]]:
    if obj is None or not hasattr(obj, "get"):
        return None
    return _decode_dynamic_entity_slots_payload(obj.get("mtk:dynamic_entity_slots"))


def _resolve_export_enable_ctm(active_obj: Any, cloud_obj: Any, prefs: Any) -> bool:
    """Resolve CTM enablement from the imported container, then preferences."""
    parent = getattr(active_obj, "parent", None) if active_obj is not None else None
    for obj in (active_obj, cloud_obj, parent):
        if obj is None or not hasattr(obj, "get"):
            continue
        raw = obj.get("mtk_enable_ctm")
        if isinstance(raw, bool):
            return raw
    raw_pref = getattr(prefs, "enable_ctm", True) if prefs is not None else True
    return bool(raw_pref) if isinstance(raw_pref, bool) else True


def _resolve_export_dynamic_entity_slots(active_obj: Any, cloud_obj: Any) -> Optional[dict[str, tuple[int, int]]]:
    """Resolves dynamic entity slot mapping via bridge.world.resolve_dynamic_entity_slots."""
    if not HAS_BPY:
        return None

    session_key = (
        active_obj.get("mtk:session_key") or active_obj.get("mozi_save_uuid")
        if hasattr(active_obj, "get")
        else None
    ) or (
        cloud_obj.get("mtk:session_key") or cloud_obj.get("mozi_save_uuid")
        if hasattr(cloud_obj, "get")
        else None
    )
    if not session_key and hasattr(active_obj, "parent") and active_obj.parent:
        p = active_obj.parent
        session_key = (p.get("mtk:session_key") or p.get("mozi_save_uuid")) if hasattr(p, "get") else None

    if session_key:
        slots = get_world_session_dynamic_entity_slots(session_key)
        if slots:
            return slots

    # Save/scene imports persist slots on the container hierarchy; use them when the
    # live VoxelWorld session has been evicted or was never registered (save imports).
    parent = getattr(active_obj, "parent", None) if active_obj is not None else None
    grandparent = getattr(parent, "parent", None) if parent is not None else None
    for obj in (active_obj, cloud_obj, parent, grandparent):
        slots = _embedded_dynamic_entity_slots(obj)
        if slots:
            return slots

    mesh_data = getattr(active_obj, "data", None)
    if mesh_data is not None:
        slots = resolve_dynamic_entity_slots(mesh_data)
        if slots:
            return slots

    cloud_data = getattr(cloud_obj, "data", None)
    if cloud_data is not None:
        slots = resolve_dynamic_entity_slots(cloud_data)
        if slots:
            return slots

    return None


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

    enable_ctm: BoolProperty(  # type: ignore
        name="Connected Textures (CTM)",
        description="Include connected-texture rules and sub-tiles in the exported scene package",
        default=True,
    )

    def draw(self, context):
        from ...i18n import tr

        layout = self.layout
        box = layout.box()
        box.label(text=tr("Scene Export Options"), icon="SCENE_DATA")
        box.prop(self, "max_atlas_size", text=tr("Max Atlas Size"))
        box.prop(self, "enable_ctm", text=tr("Connected Textures (CTM)"))

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
        dyn_slots = _resolve_export_dynamic_entity_slots(active, cloud_obj)
        ui_enable_ctm = getattr(self, "enable_ctm", None)
        if isinstance(ui_enable_ctm, bool):
            enable_ctm = ui_enable_ctm
        else:
            enable_ctm = _resolve_export_enable_ctm(active, cloud_obj, prefs)

        try:
            meta = export_scene_package(
                output_path=self.filepath,
                point_cloud=point_cloud,
                prefs=prefs,
                max_atlas_size=self.max_atlas_size,
                dynamic_entity_atlases=dyn_entities,
                dynamic_entity_slots=dyn_slots,
                enable_ctm=enable_ctm,
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
