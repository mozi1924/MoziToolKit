"""
Live Sync Material Manager singleton and Section Material Slot binding utilities.
"""

from __future__ import annotations

from typing import Any, Optional
import bpy

from .constants import (
    MTK_ATLAS_CHUNK_ID,
    MTK_SOURCE_TEXTURE_KEY,
)
from .material_manager import LiveSyncMaterialManager

_GLOBAL_MAT_MANAGER: Optional[LiveSyncMaterialManager] = None
_GLOBAL_MAT_MANAGER_SIG: Optional[tuple] = None


def get_shared_material_manager(
    world_obj: Optional[bpy.types.Object],
    atlas_params: Optional[dict[str, Any]],
) -> LiveSyncMaterialManager:
    """Retrieve or reuse shared LiveSyncMaterialManager instance to avoid re-indexing."""
    global _GLOBAL_MAT_MANAGER, _GLOBAL_MAT_MANAGER_SIG
    obj_ptr = world_obj.as_pointer() if world_obj and hasattr(world_obj, "as_pointer") else id(world_obj)
    mapping_obj = atlas_params.get("mapping") if atlas_params else None
    mapping_id = id(mapping_obj) if mapping_obj else 0
    pack_hash = atlas_params.get("pack_hash", "") if atlas_params else ""
    current_sig = (obj_ptr, mapping_id, pack_hash)

    is_valid = True
    if _GLOBAL_MAT_MANAGER is not None:
        for mat in _GLOBAL_MAT_MANAGER.chunk_materials.values():
            try:
                _ = mat.name
            except (ReferenceError, Exception):
                is_valid = False
                break

    if not is_valid or _GLOBAL_MAT_MANAGER is None or _GLOBAL_MAT_MANAGER_SIG != current_sig:
        _GLOBAL_MAT_MANAGER_SIG = current_sig
        _GLOBAL_MAT_MANAGER = LiveSyncMaterialManager(world_obj=world_obj, atlas_params=atlas_params)

    return _GLOBAL_MAT_MANAGER


def clear_shared_material_manager() -> None:
    """Reset shared material manager singleton."""
    global _GLOBAL_MAT_MANAGER, _GLOBAL_MAT_MANAGER_SIG
    _GLOBAL_MAT_MANAGER = None
    _GLOBAL_MAT_MANAGER_SIG = None


def sync_section_material_slots(
    section_obj: bpy.types.Object,
    mat_manager: LiveSyncMaterialManager,
) -> bool:
    """Mirror the manager's compact slot layout onto one Direct-Mesh section.

    ``ResolvedFaceTexture.slot_index`` is a Blender material-slot index, not
    an atlas ``chunk_id``. Chunk IDs may be sparse (for example, a banner
    chunk can be 7), so assigning a material to ``materials[chunk_id]`` both
    creates empty slots and makes faces point at unrelated block materials.
    Returns True if material slots were changed, False otherwise.
    """
    return mat_manager.sync_material_slots(section_obj)


def rebind_mesh_material_indices(
    mesh: bpy.types.Mesh,
    mat_manager: LiveSyncMaterialManager,
) -> None:
    """Repair/render-bind faces from their persistent chunk identity.

    Older live-sync meshes do not have the chunk attribute, so their
    ``mtk_source_texture_key`` is used once to migrate them. The material
    index itself is never used as an atlas identifier.
    Supports both Object Mode and Edit Mode seamlessly.
    """
    if getattr(mesh, "is_editmode", False):
        import bmesh
        bm = bmesh.from_edit_mesh(mesh)
        chunk_layer = bm.faces.layers.int.get(MTK_ATLAS_CHUNK_ID)
        source_layer = bm.faces.layers.string.get(MTK_SOURCE_TEXTURE_KEY)
        for face in bm.faces:
            chunk_id = face[chunk_layer] if chunk_layer else 0
            if (chunk_layer is None or chunk_id not in mat_manager.chunk_materials) and source_layer:
                raw_key = face[source_layer]
                source_key = raw_key.decode("utf-8", "replace") if isinstance(raw_key, bytes) else str(raw_key or "")
                location = mat_manager.resolver.lookup_texture(source_key) if source_key else None
                if location:
                    chunk_id = int(location.get("chunk_id", 0))
                    if chunk_layer:
                        face[chunk_layer] = chunk_id
            if chunk_id in mat_manager.chunk_materials:
                face.material_index = mat_manager.get_slot_for_chunk(chunk_id)
        bmesh.update_edit_mesh(mesh, loop_triangles=True, destructive=False)
        return

    chunk_attr = mesh.attributes.get(MTK_ATLAS_CHUNK_ID)
    created_chunk_attr = chunk_attr is None
    if not chunk_attr:
        chunk_attr = mesh.attributes.new(MTK_ATLAS_CHUNK_ID, "INT", "FACE")
    source_attr = mesh.attributes.get(MTK_SOURCE_TEXTURE_KEY)

    for poly in mesh.polygons:
        chunk_id = int(chunk_attr.data[poly.index].value)
        if (created_chunk_attr or chunk_id not in mat_manager.chunk_materials) and source_attr:
            raw_key = source_attr.data[poly.index].value
            source_key = raw_key.decode("utf-8", "replace") if isinstance(raw_key, bytes) else str(raw_key or "")
            location = mat_manager.resolver.lookup_texture(source_key) if source_key else None
            if location:
                chunk_id = int(location.get("chunk_id", 0))
                chunk_attr.data[poly.index].value = chunk_id
        if chunk_id in mat_manager.chunk_materials:
            poly.material_index = mat_manager.get_slot_for_chunk(chunk_id)
