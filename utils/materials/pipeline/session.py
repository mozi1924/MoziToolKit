"""
Material Session and Face Cache Utilities.
Provides session-level material deduplication, naming, provenance tracking,
and precomputed material face caches for fast per-face scanning.
"""

from __future__ import annotations

import json
from typing import Optional, Union, Any
import bpy

from .provenance import (
    write_provenance_schema,
    write_face_source_provenance,
    detect_material_mode,
    split_texture_key,
    get_atlas_mapping_from_material,
    get_atlas_mapping_from_mesh,
)
from ..constants import (
    ATTR_ATLAS_CHUNK_ID,
    ATTR_ATLAS_TEXTURE_ID,
    PROP_ATLAS_MAPPING,
    PROP_CREATED_BY,
    PROP_PACK_HASH,
    PROP_SOURCE_FILE,
)


def get_polygon_material_indices(mesh: bpy.types.Mesh) -> list[int]:
    """Fetch all polygon slot indices through Blender's bulk RNA API."""
    indices = [0] * len(mesh.polygons)
    mesh.polygons.foreach_set if False else mesh.polygons.foreach_get("material_index", indices)
    return indices


def name_replaced_material(
    mat: bpy.types.Material,
    texture_info: dict,
    pack_or_hash: Union[str, Any],
) -> None:
    """Assign a compact visible identity and durable provenance metadata."""
    namespace = texture_info["namespace"]
    texture_name = texture_info["texture_name"]
    full_hash = getattr(pack_or_hash, "pack_hash", str(pack_or_hash))
    mat.name = f"mtk:{namespace}:{texture_name}:{full_hash[:12]}"
    mat.use_fake_user = False
    mat["mtk:source_namespace"] = namespace
    mat["mtk:source_texture"] = texture_name
    mat["mtk:material_id"] = f"{namespace}:{texture_name}"
    mat["mtk:pack_hash"] = full_hash
    mat["mtk:pack_hash_short"] = full_hash[:12]
    write_provenance_schema(mat)


def find_existing_replacement(
    texture_info: dict,
    pack_or_hash: Union[str, Any],
) -> Optional[bpy.types.Material]:
    """Find an existing material datablock matching the exact pack hash and texture key."""
    namespace = texture_info["namespace"]
    texture_name = texture_info["texture_name"]
    full_hash = getattr(pack_or_hash, "pack_hash", str(pack_or_hash))
    for material in bpy.data.materials:
        if (
            material.get("mtk:source_namespace") == namespace
            and material.get("mtk:source_texture") == texture_name
            and material.get("mtk:pack_hash") == full_hash
        ):
            return material
    return None


def apply_mesh_face_materials_and_provenance(
    mesh: bpy.types.Mesh,
    face_materials: list[bpy.types.Material | None],
    source_keys: list[str],
    source_origins: list[str],
) -> None:
    """Consolidate material slots and write back durable face-level provenance."""
    unique_materials: list[bpy.types.Material] = []
    mat_slots: dict[bpy.types.Material, int] = {}
    for mat in face_materials:
        if mat is not None and mat not in mat_slots:
            mat_slots[mat] = len(unique_materials)
            unique_materials.append(mat)

    if unique_materials:
        mesh.materials.clear()
        for mat in unique_materials:
            mesh.materials.append(mat)
        mesh.polygons.foreach_set(
            "material_index",
            [mat_slots.get(mat, 0) for mat in face_materials],
        )

    write_face_source_provenance(mesh, source_keys, source_origins)


def cleanup_unused_mtk_datablocks() -> tuple[int, int]:
    """Release only MTK-owned orphan materials/images after a replacement pass.

    Blender does not collect unused datablocks automatically.  Limiting this
    to explicitly MTK-owned data preserves imported/user materials while
    preventing repeated pack replacements from retaining old shader graphs,
    packed textures, and image buffers indefinitely.
    """
    removed_materials = 0
    for material in list(bpy.data.materials):
        if material.users == 0 and material.get(PROP_CREATED_BY) == "MoziToolKit":
            bpy.data.materials.remove(material)
            removed_materials += 1

    removed_images = 0
    for image in list(bpy.data.images):
        is_mtk_image = bool(image.get(PROP_PACK_HASH) or image.get(PROP_SOURCE_FILE))
        if image.users == 0 and is_mtk_image:
            bpy.data.images.remove(image)
            removed_images += 1
    return removed_materials, removed_images


def build_material_face_cache(obj: bpy.types.Object, mesh: bpy.types.Mesh) -> tuple[list, dict]:
    """Precompute all material-level data used by the hot per-face loops.

    A large Minecraft mesh commonly has hundreds of thousands of faces but
    only tens or hundreds of source materials. Adapter detection walks node
    trees and atlas mappings, so precomputing it avoids heavy per-polygon RNA calls.
    """
    from ..matching import (
        extract_material_texture_keys,
        material_source_origin,
        is_ice_cube_internal_face_material,
    )
    mesh_mapping = get_atlas_mapping_from_mesh(mesh)
    chunk_attr = mesh.attributes.get(ATTR_ATLAS_CHUNK_ID) or mesh.attributes.get("atlas_chunk_id")
    texture_attr = mesh.attributes.get(ATTR_ATLAS_TEXTURE_ID) or mesh.attributes.get("atlas_texture_id")
    slot_materials = [slot.material for slot in obj.material_slots]
    cache = {}
    for material in slot_materials:
        if material is None or material in cache:
            continue
        mapping = get_atlas_mapping_from_material(material) or mesh_mapping
        locations = {}
        if mapping:
            for texture_name, location in mapping.get("textures", {}).items():
                if location is None:
                    continue
                try:
                    locations[(int(location.get("chunk_id", -1)), int(location.get("texture_id", -1)))] = location
                except (TypeError, ValueError):
                    continue
        cache[material] = {
            "mapping": mapping,
            "mode": detect_material_mode(material),
            "is_internal": is_ice_cube_internal_face_material(material),
            "origin": material_source_origin(material),
            "locations": locations,
            "chunk_attr": chunk_attr,
            "texture_attr": texture_attr,
            "candidates": extract_material_texture_keys(material),
            "chunks": {
                int(chunk["chunk_id"]): chunk
                for chunk in (mapping or {}).get("chunks", [])
                if "chunk_id" in chunk
            },
            "animation": None,
            "animation_loaded": False,
        }
    return slot_materials, cache


def cached_face_texture_info(
    mesh: bpy.types.Mesh,
    poly_idx: int,
    material: bpy.types.Material,
    state: dict,
    source_key: str,
) -> tuple[str, list[str], Optional[dict]]:
    """Fast path for face matching, retaining full decoder as fallback."""
    mode = state["mode"]
    provenance = None
    if source_key:
        namespace, texture_name = split_texture_key(source_key)
        if texture_name:
            candidates = [texture_name]
            if "/" in texture_name:
                basename = texture_name.rsplit("/", 1)[-1]
                if basename and basename != texture_name:
                    candidates.append(basename)
            provenance = (namespace, candidates)

    if mode not in ("ATLAS_CHUNK", "ATLAS_UNIFIED", "MINEWAYS_ATLAS"):
        if provenance:
            return *provenance, None
        namespace, candidates = state["candidates"]
        return namespace, candidates, None

    if mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED"):
        chunk_attr = state["chunk_attr"]
        texture_attr = state["texture_attr"]
        try:
            chunk_id = int(chunk_attr.data[poly_idx].value) if chunk_attr else int(material.get("mtk:atlas_chunk_id", -1))
            texture_id = int(texture_attr.data[poly_idx].value) if texture_attr else -1
        except (IndexError, TypeError, ValueError):
            chunk_id, texture_id = -1, -1
        location = state["locations"].get((chunk_id, texture_id))
        if location:
            if provenance:
                return *provenance, location
            namespace, texture_name = split_texture_key(location.get("texture_key", ""))
            if texture_name:
                return namespace, [texture_name], location

    from ..matching import extract_face_texture_info
    return extract_face_texture_info(mesh, poly_idx, material, state["mapping"])


def apply_generic_procedural_atlas_material(
    obj: bpy.types.Object,
    atlas_materials: dict[int, bpy.types.Material],
    mapping_data: dict,
) -> bool:
    """Apply default Atlas material and provenance to a generic polygon-free procedural object."""
    primary_mat = atlas_materials.get(0) or (list(atlas_materials.values())[0] if atlas_materials else None)
    if not primary_mat:
        return False
    if not obj.data.materials:
        obj.data.materials.append(primary_mat)
    else:
        obj.data.materials[0] = primary_mat
    for mod in obj.modifiers:
        if mod.type == 'NODES' and mod.node_group:
            for n in mod.node_group.nodes:
                if n.type == 'SET_MATERIAL' and "Material" in n.inputs:
                    n.inputs["Material"].default_value = primary_mat
    obj.data["mtk:atlas_mapping"] = json.dumps(mapping_data, separators=(",", ":"))
    write_provenance_schema(obj.data)
    return True
