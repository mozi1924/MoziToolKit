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
    obj_ptr = world_obj.as_pointer() if world_obj and hasattr(world_obj, "as_pointer") else (id(world_obj) if world_obj else 0)
    mapping_obj = atlas_params.get("mapping") if atlas_params else None
    mapping_id = id(mapping_obj) if mapping_obj else 0
    pack_hash = str(atlas_params.get("pack_hash", "")) if atlas_params else ""
    current_sig = (obj_ptr, mapping_id, pack_hash)

    if _GLOBAL_MAT_MANAGER is not None and _GLOBAL_MAT_MANAGER_SIG == current_sig:
        return _GLOBAL_MAT_MANAGER

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


def validate_and_sync_scene_materials(
    target_obj: Optional[bpy.types.Object],
    pack_stack: Optional[Any] = None,
) -> bool:
    """
    Phase 1 Handshake & Rebuild Material Validator.
    Checks if the scene object's bound materials match the active ResourcePackStack hash.
    If outdated (e.g. user re-compiled atlas in preferences or switched packs since .blend was saved),
    re-instantiates the shared material manager and updates material slots & face indices cleanly.
    Returns True if materials were refreshed/upgraded, False if already up-to-date.
    """
    if not target_obj:
        return False

    try:
        from ..materials.pipeline.provenance import get_effective_pack_hash, is_material_hash_valid
        from ..materials.pack.pack_stack import get_configured_pack_stack
    except (ImportError, ValueError):
        from utils.materials.pipeline.provenance import get_effective_pack_hash, is_material_hash_valid
        from utils.materials.pack.pack_stack import get_configured_pack_stack

    if pack_stack is None:
        try:
            pack_stack = get_configured_pack_stack()
        except Exception:
            pack_stack = None

    target_pack_hash = get_effective_pack_hash(pack_stack) if pack_stack else ""

    # Check slot 0 material or bound atlas material on target_obj
    existing_mat = None
    if getattr(target_obj, "data", None) and hasattr(target_obj.data, "materials") and target_obj.data.materials:
        for slot_mat in target_obj.data.materials:
            if slot_mat:
                existing_mat = slot_mat
                break

    is_valid = True
    if existing_mat:
        mat_hash = get_effective_pack_hash(existing_mat)
        if target_pack_hash and mat_hash and mat_hash != target_pack_hash:
            is_valid = False
        elif not is_material_hash_valid(existing_mat, target_pack_hash):
            is_valid = False

    if not is_valid or _GLOBAL_MAT_MANAGER is None:
        clear_shared_material_manager()
        try:
            from ..mc_baker import refresh_shared_baker_sources
            refresh_shared_baker_sources(force_precompile_if_missing=True)
        except Exception:
            pass

        from ..materials.yefira.atlas_integration import extract_atlas_parameters
        atlas_params = extract_atlas_parameters(mat=None, pack_stack=pack_stack)

        mat_manager = get_shared_material_manager(world_obj=target_obj, atlas_params=atlas_params)
        sync_section_material_slots(target_obj, mat_manager)

        # Synchronize child sections if hierarchical mode
        for child in getattr(target_obj, "children", []):
            if child.data and isinstance(child.data, bpy.types.Mesh):
                sync_section_material_slots(child, mat_manager)
                rebind_mesh_material_indices(child.data, mat_manager)

        return True

    return False

