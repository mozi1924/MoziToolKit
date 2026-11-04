"""
MoziToolKit Scene Interchange Hierarchy and Assembly.

Orchestrates Blender scene datablocks, unified empty container architecture,
companion point cloud synchronization, canonical PBR materials, and metadata
custom properties for imported .mtkscene interchange packages.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from ...bridge.world import resolve_dynamic_entity_atlases
from ..mesh.ownership import ORIGIN_SCENE
from ..point_cloud.hierarchy import ensure_voxel_child_cloud
from ..world.assembler import (
    VoxelWorldAssemblyRequest,
    assemble_voxel_world,
    safe_set_custom_prop,
    safe_get_custom_prop,
    persist_dynamic_entity_slots,
)
from .materials import bind_scene_materials

logger = logging.getLogger("MoziToolKit.Scene.Hierarchy")

# Backwards compatibility alias
_safe_set_custom_prop = safe_set_custom_prop


def apply_imported_scene_to_blender(
    data: Dict[str, Any],
    scene_name: Optional[str] = None,
    origin_centered: bool = True,
    target_collection: Optional[Any] = None,
    context: Optional[Any] = None,
    prefs=None,
    enable_animated_textures: bool = True,
) -> Dict[str, Any]:
    """
    Assembles Blender objects for an imported .mtkscene package adhering strictly
    to the Unified World Empty Container architecture:
      Container Root: Empty, `[Scene] <name>`, mtk:is_container=True, mtk:container_type="SCENE"
      ├── World Mesh: Mesh, `[Scene] <name>_Mesh`
      └── Companion Point Cloud: Mesh, `[Scene] <name>_VoxelCloud` (hidden by default)
    """
    if not HAS_BPY:
        return {}

    mesh_data = data.get("mesh_data")
    point_cloud = data.get("point_cloud")
    storage = data.get("storage")
    reader = data.get("reader")
    atlas = data.get("atlas")
    meta = data.get("metadata", {})
    colormaps = data.get("colormaps")
    slot_map = data.get("dynamic_entity_slots")

    s_name = scene_name or "Scene"
    root_name = f"[Scene] {s_name}"

    def material_binder(mesh_obj: Any) -> Any:
        used_chunk_ids = mesh_data.used_materials() if mesh_data and hasattr(mesh_data, "used_materials") else None
        dyn_atlases = resolve_dynamic_entity_atlases(mesh_data) if mesh_data else None
        return bind_scene_materials(
            mesh_obj,
            reader=reader,
            scene_name=s_name,
            atlas=atlas,
            prefs=prefs,
            used_chunk_ids=used_chunk_ids,
            dynamic_entity_atlases=dyn_atlases,
        )

    metadata_props = {
        "mtk:scene_format_version": meta.get("format_version", 1),
        "mtk:voxel_count": meta.get("voxel_count", 0),
        "mtk:bounds": list(meta.get("bounds", [0, 0, 0, 0, 0, 0])),
        "mtk:generator": str(meta.get("generator", "MoziToolKit")),
        "mtk:enable_animated_textures": bool(enable_animated_textures),
    }

    req = VoxelWorldAssemblyRequest(
        container_type="SCENE",
        root_name=root_name,
        mesh_data=mesh_data,
        storage=storage,
        point_cloud=point_cloud,
        atlas=atlas,
        dynamic_entity_slots=slot_map,
        colormaps=colormaps,
        origin_centered=origin_centered,
        target_collection=target_collection,
        context=context,
        prefs=prefs,
        geometry_origin=ORIGIN_SCENE,
        custom_material_binder=material_binder,
        custom_cloud_ensurer=ensure_voxel_child_cloud,
        metadata_props=metadata_props,
    )

    result = assemble_voxel_world(req)
    if not result:
        return {}

    scene_uuid = result["container_id"]
    safe_set_custom_prop(result["root_obj"], "mozi_scene_uuid", str(scene_uuid))
    safe_set_custom_prop(result["mesh_obj"], "mozi_scene_uuid", str(scene_uuid))

    return {
        "root_obj": result["root_obj"],
        "mesh_obj": result["mesh_obj"],
        "cloud_obj": result["cloud_obj"],
        "materials": result["materials"],
        "scene_uuid": scene_uuid,
    }


__all__ = [
    "apply_imported_scene_to_blender",
    "_safe_set_custom_prop",
    "ensure_voxel_child_cloud",
    "bind_scene_materials",
]
