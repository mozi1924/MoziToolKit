"""
MoziToolKit Material Replacement & Provenance Pipeline.
Executes pure Rust (libmtk) material resolution, UV remapping,
LabPBR 1.3 shader construction, and mesh attribute synchronization.
"""

from __future__ import annotations

import array
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

logger = logging.getLogger("MoziToolKit.Material.Pipeline")

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

try:
    from ...bridge.material import (
        is_material_bridge_available,
        load_baked_atlas_from_json,
        remap_mesh_multi_uvs,
        compute_flat_material_props,
        BiomeResolver,
    )
except (ImportError, ValueError):
    from bridge.material import (
        is_material_bridge_available,
        load_baked_atlas_from_json,
        remap_mesh_multi_uvs,
        compute_flat_material_props,
        BiomeResolver,
    )


def __getattr__(name: str) -> Any:
    if name == "HAS_LIBMTK":
        return is_material_bridge_available()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

try:
    from ...bridge.assets import (
        get_cache_dir,
        get_active_cache_package_path,
        get_cache_fingerprint,
        precompile_stack,
        load_atlas_mapping_from_cache,
        load_standalone_mapping_from_cache,
        load_baked_atlas_from_cache,
        ensure_atlas_textures_extracted,
        ensure_standalone_textures_extracted,
        ensure_colormaps_extracted,
    )
    from ...bridge.mesh import (
        _get_mesh,
        inject_face_attribute_string,
        inject_face_attribute_int,
        inject_face_attribute_float,
        inject_face_attribute_float4,
        resolve_source_texture_keys,
        inject_face_source_texture_keys,
    )
    from .builder.atlas_builder import build_atlas_chunk_material
    from .builder.standalone_builder import build_standalone_material
    from .matching.presets.registry import build_matching_context
except (ImportError, ValueError):
    from bridge.assets import (
        get_cache_dir,
        get_active_cache_package_path,
        get_cache_fingerprint,
        precompile_stack,
        load_atlas_mapping_from_cache,
        load_standalone_mapping_from_cache,
        load_baked_atlas_from_cache,
        ensure_atlas_textures_extracted,
        ensure_standalone_textures_extracted,
        ensure_colormaps_extracted,
    )
    from bridge.mesh import (
        _get_mesh,
        inject_face_attribute_string,
        inject_face_attribute_int,
        inject_face_attribute_float,
        inject_face_attribute_float4,
        resolve_source_texture_keys,
        inject_face_source_texture_keys,
    )
    from utils.materials.builder.atlas_builder import build_atlas_chunk_material
    from utils.materials.builder.standalone_builder import build_standalone_material
    from utils.materials.matching.presets.registry import build_matching_context
    from .biome import (
        get_or_load_biome_resolver,
        compute_biome_tint_attributes,
        apply_biome_tint_attributes,
    )
    from .constants import (
        ATTR_SOURCE_TEXTURE_KEY,
        ATTR_MATERIAL_SLOT,
        ATTR_ATLAS_CHUNK_ID,
        ATTR_ATLAS_TEXTURE_ID,
        ATTR_UV_MODE,
        ATTR_UV_TILING_TRANSFORM,
        ATTR_UV_TRANSFORM,
        ATTR_UV_ROTATION,
        ATTR_BIOME_TINT_DATA,
        ATTR_BIOME_TINT_COLOR,
        ATTR_COLORMAP_UV,
        ATTR_MATERIAL_PROPS,
    )
except (ImportError, ValueError):
    from bridge.assets import get_cache_dir, precompile_stack
    from bridge.mesh import (
        _get_mesh,
        inject_face_attribute_string,
        inject_face_attribute_int,
        inject_face_attribute_float,
        inject_face_attribute_float4,
    )
    from utils.materials.builder.atlas_builder import build_atlas_chunk_material
    from utils.materials.builder.standalone_builder import build_standalone_material
    from utils.materials.matching.presets.registry import build_matching_context
    try:
        from utils.materials.biome import (
            get_or_load_biome_resolver,
            compute_biome_tint_attributes,
            apply_biome_tint_attributes,
        )
        from utils.materials.constants import (
            ATTR_SOURCE_TEXTURE_KEY,
            ATTR_MATERIAL_SLOT,
            ATTR_ATLAS_CHUNK_ID,
            ATTR_ATLAS_TEXTURE_ID,
            ATTR_UV_MODE,
            ATTR_UV_TILING_TRANSFORM,
            ATTR_UV_TRANSFORM,
            ATTR_UV_ROTATION,
            ATTR_BIOME_TINT_DATA,
            ATTR_BIOME_TINT_COLOR,
            ATTR_COLORMAP_UV,
            ATTR_MATERIAL_PROPS,
        )
    except Exception:
        pass


def ensure_stack_precompiled(prefs: Optional[Any] = None) -> Path:
    """Ensure asset caches exist in persistent storage."""
    base_cache = get_cache_dir(prefs)
    pkg = get_active_cache_package_path(prefs)

    if pkg is None:
        precompile_stack(prefs)

    return base_cache


# =============================================================================
# Pipeline Step Processors
# =============================================================================

def load_material_cache_context(
    prefs: Optional[Any] = None,
) -> Tuple[Path, Path, Path, Dict[str, Path], Optional[str]]:
    """
    Step 1: Ensure assets are precompiled and discover cache directories, colormaps, and manifest.
    """
    base_cache = ensure_stack_precompiled(prefs)
    atlas_dir = ensure_atlas_textures_extracted(prefs)
    standalone_dir = ensure_standalone_textures_extracted(prefs)
    colormaps = ensure_colormaps_extracted(prefs)
    manifest_fingerprint = get_cache_fingerprint(prefs)

    return base_cache, atlas_dir, standalone_dir, colormaps, manifest_fingerprint


def extract_face_material_context(
    mesh: Any,
) -> Tuple[List[str], List[Tuple[int, int]], array.array, Any, Optional[List[str]]]:
    """
    Step 2: Extract face materials, loop ranges, loop UVs, and existing provenance keys from mesh.
    """
    num_polys = len(mesh.polygons)
    num_loops = len(mesh.loops)

    uv_layer = mesh.uv_layers.active or (mesh.uv_layers[0] if len(mesh.uv_layers) > 0 else None)
    if uv_layer is None:
        uv_layer = mesh.uv_layers.new(name="UVMap")

    loop_uvs = array.array("f", [0.0]) * (num_loops * 2)
    uv_layer.data.foreach_get("uv", loop_uvs)

    existing_prov_keys: Optional[List[str]] = resolve_source_texture_keys(mesh)
    if not existing_prov_keys or len(existing_prov_keys) != num_polys:
        existing_prov_keys = None

    face_materials: List[str] = []
    face_loop_ranges: List[Tuple[int, int]] = []

    for idx, poly in enumerate(mesh.polygons):
        mat_name = "default"
        mat_slot = None
        if poly.material_index < len(mesh.materials):
            mat_slot = mesh.materials[poly.material_index]
            if mat_slot:
                mat_name = mat_slot.name

        mat_lower = mat_name.strip().lower()
        is_mtk_mat = (
            mat_lower.startswith(("mtk:", "mtk_", "mc_atlas", "default"))
            or (mat_slot and bool(mat_slot.get("mtk:material_id") or mat_slot.get("mtk_source_texture_key") or mat_slot.get("mtk_material_mode")))
        )

        if is_mtk_mat and existing_prov_keys:
            candidate = existing_prov_keys[idx]
            if candidate and candidate != "mozi:fallback":
                mat_name = candidate
        elif is_mtk_mat and mat_slot:
            mat_id = mat_slot.get("mtk_source_texture_key") or mat_slot.get("mtk:material_id") or mat_slot.get("mtk:source_texture")
            if mat_id and mat_id != "mozi:fallback":
                mat_name = mat_id

        face_materials.append(mat_name)
        face_loop_ranges.append((poly.loop_start, poly.loop_total))

    return face_materials, face_loop_ranges, loop_uvs, uv_layer, existing_prov_keys


def remap_face_materials_and_uvs(
    baked_atlas: Any,
    atlas_data: Dict[str, Any],
    face_materials: List[str],
    loop_uvs: array.array,
    face_loop_ranges: List[Tuple[int, int]],
    origin: str,
    existing_prov_keys: Optional[List[str]],
) -> Dict[str, Any]:
    """
    Step 3: Execute pure Rust multi-UV remapping and resolve source texture keys for all faces.
    """
    unique_names = list(dict.fromkeys(face_materials))
    alias_map, grid_spec = build_matching_context(unique_names, origin=origin)

    remap_result = remap_mesh_multi_uvs(
        loop_uvs=loop_uvs,
        face_materials=face_materials,
        face_loop_ranges=face_loop_ranges,
        atlas=baked_atlas,
        alias_map=alias_map,
        grid_spec=grid_spec,
    )

    face_texture_ids: List[int] = remap_result["face_texture_ids"]
    sprites_dict = atlas_data.get("sprites", {})
    id_to_key: Dict[int, str] = {}
    for key, sp in sprites_dict.items():
        tid = sp.get("texture_id")
        if tid is not None:
            id_to_key[int(tid)] = key

    face_source_keys: List[str] = []
    for i, tex_id in enumerate(face_texture_ids):
        resolved_key = id_to_key.get(tex_id)
        if not resolved_key and existing_prov_keys and existing_prov_keys[i] and existing_prov_keys[i] != "mozi:fallback":
            resolved_key = existing_prov_keys[i]
        face_source_keys.append(resolved_key or "mozi:fallback")

    remap_result["face_source_keys"] = face_source_keys
    return remap_result


def assign_atlas_chunk_materials(
    mesh: Any,
    uv_layer: Optional[Any],
    atlas_data: Dict[str, Any],
    atlas_dir: Path,
    face_chunk_ids: List[int],
    atlas_uvs: Optional[List[float]],
    colormaps: Dict[str, Path],
    manifest_fingerprint: Optional[str],
) -> array.array:
    """
    Step 4A: Construct Atlas Chunk materials, assign to mesh material slots, and optionally set Atlas UVs.
    """
    num_polys = len(mesh.polygons)
    poly_mat_indices = array.array("H", [0]) * num_polys

    unique_chunks = sorted(list(set(face_chunk_ids)))
    chunk_to_slot: Dict[int, int] = {}
    mesh.materials.clear()

    chunk_meta_list = atlas_data.get("chunks", [])
    chunk_meta_map: Dict[int, Dict[str, Any]] = {
        c.get("chunk_id", idx): c for idx, c in enumerate(chunk_meta_list)
    }

    for slot_idx, chunk_id in enumerate(unique_chunks):
        cm = chunk_meta_map.get(chunk_id, {})
        cat = cm.get("category", "blocks")
        c_idx = cm.get("category_chunk_index", chunk_id + 1)
        is_anim = cm.get("is_animated", False)
        stem = f"{cat}_anim_chunk_{c_idx:03}" if is_anim else f"{cat}_chunk_{c_idx:03}"

        albedo_file = atlas_dir / f"{stem}.png"
        normal_file = atlas_dir / f"{stem}_n.png" if cm.get("has_normal") else None
        specular_file = atlas_dir / f"{stem}_s.png" if cm.get("has_specular") else None
        overlay_file = atlas_dir / f"{stem}_overlay.png" if cm.get("has_overlay") else None
        chunk_width = float(cm.get("width", 1024))
        chunk_height = float(cm.get("height", 512))

        mat = build_atlas_chunk_material(
            chunk_id=chunk_id,
            albedo_path=albedo_file,
            normal_path=normal_file,
            specular_path=specular_file,
            overlay_path=overlay_file,
            colormaps=colormaps,
            category=cat,
            category_chunk_index=c_idx,
            is_animated=is_anim,
            stack_fingerprint=manifest_fingerprint,
            atlas_width=chunk_width,
            atlas_height=chunk_height,
            tile_width=16.0,
            tile_height=16.0,
            uv_map_name=uv_layer.name if uv_layer else "UVMap",
        )
        mesh.materials.append(mat)
        chunk_to_slot[chunk_id] = slot_idx

    for i, cid in enumerate(face_chunk_ids):
        poly_mat_indices[i] = chunk_to_slot.get(cid, 0)

    if atlas_uvs is not None and uv_layer is not None:
        atlas_uv_np = np.ascontiguousarray(atlas_uvs, dtype=np.float32)
        uv_attr = mesh.attributes.get(uv_layer.name) if hasattr(mesh, "attributes") else None
        if uv_attr is not None and len(uv_attr.data) * 2 == len(atlas_uv_np):
            uv_attr.data.foreach_set("vector", atlas_uv_np)
        else:
            uv_layer.data.foreach_set("uv", atlas_uv_np)

    mat_attr = mesh.attributes.get("material_index") if hasattr(mesh, "attributes") else None
    if mat_attr is not None and len(mat_attr.data) == len(poly_mat_indices):
        mat_attr.data.foreach_set("value", np.ascontiguousarray(poly_mat_indices, dtype=np.int32))
    else:
        mesh.polygons.foreach_set("material_index", poly_mat_indices)
    return poly_mat_indices


def assign_standalone_materials(
    mesh: Any,
    uv_layer: Optional[Any],
    standalone_mapping_path: Optional[Path] = None,
    standalone_dir: Optional[Path] = None,
    face_source_keys: Optional[List[str]] = None,
    local_uvs: Optional[List[float]] = None,
    colormaps: Optional[Dict[str, Path]] = None,
    manifest_fingerprint: Optional[str] = None,
    standalone_data: Optional[Dict[str, Any]] = None,
    prefs: Optional[Any] = None,
) -> array.array:
    """
    Step 4B: Construct Standalone block materials, assign to mesh material slots, and optionally set local UVs.
    Supports in-memory standalone mapping without loose files on disk.
    """
    if face_source_keys is None:
        face_source_keys = []

    sa_data = standalone_data
    if sa_data is None:
        sa_data = load_standalone_mapping_from_cache(prefs)

    if sa_data is None and standalone_mapping_path is not None and standalone_mapping_path.exists():
        try:
            sa_data = json.loads(standalone_mapping_path.read_text(encoding="utf-8"))
        except Exception:
            sa_data = None

    if sa_data is None:
        if standalone_mapping_path is not None and not standalone_mapping_path.exists():
            raise FileNotFoundError(f"Standalone mapping missing at {standalone_mapping_path} and no active .mtkcache found")
        sa_data = {}

    sa_textures = sa_data.get("textures", {})
    num_polys = len(mesh.polygons)
    poly_mat_indices = array.array("H", [0]) * num_polys

    unique_keys = list(dict.fromkeys(face_source_keys))
    key_to_slot: Dict[str, int] = {}
    mesh.materials.clear()

    base_sa_dir = standalone_dir or (get_cache_dir(prefs) / "standalone")

    for slot_idx, key in enumerate(unique_keys):
        if not key:
            continue
        tex_entry = sa_textures.get(key)
        if tex_entry:
            files = tex_entry.get("files", {})
            albedo_rel = files.get("albedo", "textures/mtk_fallback.png")
            albedo_p = base_sa_dir / albedo_rel
            normal_p = (base_sa_dir / files["normal"]) if "normal" in files else None
            specular_p = (base_sa_dir / files["specular"]) if "specular" in files else None
            overlay_p = (base_sa_dir / files["overlay"]) if "overlay" in files else None
            is_anim = tex_entry.get("is_animated", False)
        else:
            albedo_p = base_sa_dir / "textures" / "mtk_fallback.png"
            normal_p = None
            specular_p = None
            overlay_p = None
            is_anim = False

        mat = build_standalone_material(
            texture_key=key,
            albedo_path=albedo_p,
            normal_path=normal_p,
            specular_path=specular_p,
            overlay_path=overlay_p,
            colormaps=colormaps,
            is_animated=is_anim,
            stack_fingerprint=manifest_fingerprint,
            uv_map_name=uv_layer.name if uv_layer else "UVMap",
        )
        mesh.materials.append(mat)
        key_to_slot[key] = slot_idx

    for i, key in enumerate(face_source_keys):
        poly_mat_indices[i] = key_to_slot.get(key, 0)

    if local_uvs is not None and uv_layer is not None:
        local_uv_np = np.ascontiguousarray(local_uvs, dtype=np.float32)
        uv_attr = mesh.attributes.get(uv_layer.name) if hasattr(mesh, "attributes") else None
        if uv_attr is not None and len(uv_attr.data) * 2 == len(local_uv_np):
            uv_attr.data.foreach_set("vector", local_uv_np)
        else:
            uv_layer.data.foreach_set("uv", local_uv_np)

    mat_attr = mesh.attributes.get("material_index") if hasattr(mesh, "attributes") else None
    if mat_attr is not None and len(mat_attr.data) == len(poly_mat_indices):
        mat_attr.data.foreach_set("value", np.ascontiguousarray(poly_mat_indices, dtype=np.int32))
    else:
        mesh.polygons.foreach_set("material_index", poly_mat_indices)
    return poly_mat_indices


def inject_mesh_provenance_attributes(
    mesh: Any,
    face_source_keys: List[str],
    poly_mat_indices: array.array,
    face_chunk_ids: List[int],
    face_texture_ids: Optional[List[int]] = None,
    face_uv_transforms: Optional[List[List[float]]] = None,
    face_uv_rotations: Optional[List[float]] = None,
    mode: str = "ATLAS",
) -> None:
    """
    Step 5: Delegate provenance and shader driver attribute injection directly to bridge/mesh.py.
    """
    num_polys = len(mesh.polygons)
    mode_upper = mode.strip().upper()

    inject_face_attribute_string(mesh, "mtk_source_texture_key", face_source_keys)
    inject_face_attribute_int(mesh, "mtk_material_slot", poly_mat_indices)
    inject_face_attribute_int(mesh, "mtk_atlas_chunk_id", face_chunk_ids)

    if face_texture_ids is not None:
        inject_face_attribute_int(mesh, "mtk_atlas_texture_id", [int(x) for x in face_texture_ids])
        inject_face_attribute_int(mesh, "mtk_uv_mode", [0 if mode_upper == "ATLAS" else 1] * num_polys)

    if face_uv_transforms is not None:
        flat_transforms: List[float] = []
        for tf in face_uv_transforms:
            flat_transforms.extend(tf)
        inject_face_attribute_float4(mesh, "mtk_uv_tiling_transform", flat_transforms)
        inject_face_attribute_float4(mesh, "mtk_uv_transform", flat_transforms)

    if face_uv_rotations is not None:
        inject_face_attribute_float(mesh, "mtk_uv_rotation", face_uv_rotations)

    # Inject packed material properties (Emission, Thin Wall, Transmission, Sticker Threshold)
    if face_source_keys:
        clean_keys = [
            k.decode("utf-8", errors="ignore") if isinstance(k, (bytes, bytearray)) else str(k or "")
            for k in (face_source_keys[:num_polys] if len(face_source_keys) >= num_polys else face_source_keys + [""] * (num_polys - len(face_source_keys)))
        ]
        flat_props = compute_flat_material_props(clean_keys)
        inject_face_attribute_float4(mesh, ATTR_MATERIAL_PROPS, flat_props)


def resolve_and_apply_biome_tint(
    mesh_or_obj: Any,
    mesh: Any,
    face_source_keys: List[str],
    biome: str,
    base_cache: Path,
    prefs: Optional[Any] = None,
) -> None:
    """
    Step 6: Compute and apply biome tint attributes and colormap UVs based on current preset.
    """
    biome_resolver = get_or_load_biome_resolver(cache_dir=base_cache, prefs=prefs)

    is_custom = biome.upper() == "CUSTOM"
    if is_custom:
        custom_temp = float(getattr(mesh_or_obj, "mtk_biome_temp", mesh_or_obj.get("mtk_biome_temp", 0.8) if hasattr(mesh_or_obj, "get") else 0.8))
        custom_humidity = float(getattr(mesh_or_obj, "mtk_biome_humidity", mesh_or_obj.get("mtk_biome_humidity", 0.4) if hasattr(mesh_or_obj, "get") else 0.4))
        has_custom_grass = bool(getattr(mesh_or_obj, "mtk_biome_use_custom_grass", mesh_or_obj.get("mtk_biome_use_custom_grass", False) if hasattr(mesh_or_obj, "get") else False))
        has_custom_foliage = bool(getattr(mesh_or_obj, "mtk_biome_use_custom_foliage", mesh_or_obj.get("mtk_biome_use_custom_foliage", False) if hasattr(mesh_or_obj, "get") else False))
        has_custom_dry_foliage = bool(getattr(mesh_or_obj, "mtk_biome_use_custom_dry_foliage", mesh_or_obj.get("mtk_biome_use_custom_dry_foliage", False) if hasattr(mesh_or_obj, "get") else False))
        custom_grass = list(getattr(mesh_or_obj, "mtk_biome_grass_color", mesh_or_obj.get("mtk_biome_grass_color", (0.28, 0.51, 0.10, 1.0)) if hasattr(mesh_or_obj, "get") else (0.28, 0.51, 0.10, 1.0)))
        custom_foliage = list(getattr(mesh_or_obj, "mtk_biome_foliage_color", mesh_or_obj.get("mtk_biome_foliage_color", (0.18, 0.41, 0.03, 1.0)) if hasattr(mesh_or_obj, "get") else (0.18, 0.41, 0.03, 1.0)))
        custom_dry_foliage = list(getattr(mesh_or_obj, "mtk_biome_dry_foliage_color", mesh_or_obj.get("mtk_biome_dry_foliage_color", (0.37, 0.18, 0.06, 1.0)) if hasattr(mesh_or_obj, "get") else (0.37, 0.18, 0.06, 1.0)))
        custom_water = list(getattr(mesh_or_obj, "mtk_biome_water_color", mesh_or_obj.get("mtk_biome_water_color", (0.05, 0.18, 0.78, 1.0)) if hasattr(mesh_or_obj, "get") else (0.05, 0.18, 0.78, 1.0)))
    else:
        custom_temp = None
        custom_humidity = None
        has_custom_grass = False
        has_custom_foliage = False
        has_custom_dry_foliage = False
        custom_grass = None
        custom_foliage = None
        custom_dry_foliage = None
        custom_water = None

    packed_tint_data, tint_colors, colormap_uvs = compute_biome_tint_attributes(
        face_source_keys,
        biome_preset=biome,
        resolver=biome_resolver,
        custom_temp=custom_temp,
        custom_humidity=custom_humidity,
        custom_grass=custom_grass,
        custom_foliage=custom_foliage,
        custom_dry_foliage=custom_dry_foliage,
        custom_water=custom_water,
        has_custom_grass=has_custom_grass,
        has_custom_foliage=has_custom_foliage,
        has_custom_dry_foliage=has_custom_dry_foliage,
    )
    apply_biome_tint_attributes(mesh, packed_tint_data, tint_colors, colormap_uvs)

    if hasattr(mesh_or_obj, "__setitem__"):
        try:
            mesh_or_obj["mtk:biome_preset"] = biome
        except Exception:
            pass


# =============================================================================
# Primary Public Pipeline Orchestrators
# =============================================================================

def replace_materials(
    mesh_or_obj: Any,
    mode: str = "ATLAS",
    origin: str = "AUTO",
    biome: str = "PLAINS",
    prefs: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Executes end-to-end material replacement on a Blender mesh object using libmtk Rust backend.

    Args:
        mesh_or_obj: A `bpy.types.Object` (type MESH) or `bpy.types.Mesh`.
        mode: Material mode - "ATLAS" or "STANDALONE".
        origin: Format heuristic - "AUTO", "MINEWAYS", "JMC2OBJ", "ICE_CUBE", "GENERIC".
        biome: Biome preset name (e.g. "PLAINS", "BADLANDS", "DESERT").
        prefs: Add-on preferences reference.

    Returns:
        Summary dict containing processed face count, material slots, unmapped count, etc.
    """
    if not HAS_BPY:
        raise RuntimeError("Blender (bpy) is required to execute replace_materials.")
    if not is_material_bridge_available():
        raise RuntimeError("libmtk material bridge is not installed or available.")

    mesh = _get_mesh(mesh_or_obj)
    if mesh is None or len(mesh.polygons) == 0:
        return {"success": False, "message": "Mesh has no geometry or polygons."}

    # Step 1: Load cache context & precompiled assets
    base_cache, atlas_dir, standalone_dir, colormaps, manifest_fingerprint = load_material_cache_context(prefs)

    atlas_data = load_atlas_mapping_from_cache(prefs)
    baked_atlas = load_baked_atlas_from_cache(prefs)
    if atlas_data is None:
        atlas_mapping_path = atlas_dir / "atlas_mapping.json"
        if not atlas_mapping_path.exists():
            raise FileNotFoundError(f"Atlas mapping missing at {atlas_mapping_path} and no active .mtkcache found")
        atlas_json_str = atlas_mapping_path.read_text(encoding="utf-8")
        atlas_data = json.loads(atlas_json_str)
        baked_atlas = load_baked_atlas_from_json(atlas_json_str)
    elif baked_atlas is None:
        baked_atlas = load_baked_atlas_from_json(json.dumps(atlas_data))

    # Step 2: Extract face materials & UVs
    face_materials, face_loop_ranges, loop_uvs, uv_layer, existing_prov_keys = extract_face_material_context(mesh)

    # Step 3: Multi-UV remapping & source key resolution
    remap = remap_face_materials_and_uvs(
        baked_atlas=baked_atlas,
        atlas_data=atlas_data,
        face_materials=face_materials,
        loop_uvs=loop_uvs,
        face_loop_ranges=face_loop_ranges,
        origin=origin,
        existing_prov_keys=existing_prov_keys,
    )

    # Step 4: Construct and assign materials
    mode_upper = mode.strip().upper()
    if mode_upper == "ATLAS":
        poly_mat_indices = assign_atlas_chunk_materials(
            mesh=mesh,
            uv_layer=uv_layer,
            atlas_data=atlas_data,
            atlas_dir=atlas_dir,
            face_chunk_ids=remap["face_chunk_ids"],
            atlas_uvs=remap["atlas_uvs"],
            colormaps=colormaps,
            manifest_fingerprint=manifest_fingerprint,
        )
    else:
        poly_mat_indices = assign_standalone_materials(
            mesh=mesh,
            uv_layer=uv_layer,
            standalone_mapping_path=standalone_dir / "standalone_mapping.json",
            standalone_dir=standalone_dir,
            face_source_keys=remap["face_source_keys"],
            local_uvs=remap["local_uvs"],
            colormaps=colormaps,
            manifest_fingerprint=manifest_fingerprint,
            prefs=prefs,
        )

    # Step 5: Inject mesh provenance attributes (delegated to bridge/mesh.py)
    inject_mesh_provenance_attributes(
        mesh=mesh,
        face_source_keys=remap["face_source_keys"],
        poly_mat_indices=poly_mat_indices,
        face_chunk_ids=remap["face_chunk_ids"],
        face_texture_ids=remap["face_texture_ids"],
        face_uv_transforms=remap["face_uv_transforms"],
        face_uv_rotations=remap.get("face_uv_rotations", [0.0] * len(mesh.polygons)),
        mode=mode_upper,
    )

    # Step 6: Compute & apply biome tint attributes
    resolve_and_apply_biome_tint(mesh_or_obj, mesh, remap["face_source_keys"], biome, base_cache, prefs)

    mesh.update()
    return {
        "success": True,
        "mode": mode_upper,
        "biome": biome,
        "face_count": len(mesh.polygons),
        "materials_count": len(mesh.materials),
        "unmapped_faces": remap["unmapped_faces"],
    }


def restore_materials_from_provenance(
    mesh_or_obj: Any,
    mode: str = "ATLAS",
    biome: Optional[str] = None,
    prefs: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Reconstructs Blender material slots, nodes, and assignments purely from mesh face provenance attributes.
    Bypasses UV remapping, texture matching, and pack parsing entirely.

    Args:
        mesh_or_obj: Blender mesh or object with mtk_source_texture_key attributes.
        mode: Target reconstruction mode ("ATLAS" or "STANDALONE").
        biome: Optional biome preset to restore. Defaults to object property or "PLAINS".
        prefs: Add-on preferences reference.
    """
    if not HAS_BPY:
        raise RuntimeError("Blender (bpy) is required to execute restore_materials_from_provenance.")
    if not is_material_bridge_available():
        raise RuntimeError("libmtk material bridge is not installed or available.")

    mesh = _get_mesh(mesh_or_obj)
    if mesh is None or len(mesh.polygons) == 0:
        return {"success": False, "message": "Mesh has no geometry or polygons."}

    num_polys = len(mesh.polygons)
    face_source_keys = resolve_source_texture_keys(mesh)
    if not face_source_keys or len(face_source_keys) != num_polys:
        return {"success": False, "message": "Mesh lacks required mtk_source_texture_key / mtk_source_texture_idx attribute for provenance."}

    chunk_attr = mesh.attributes.get("mtk_atlas_chunk_id") if hasattr(mesh, "attributes") else None
    face_chunk_ids = [elem.value for elem in chunk_attr.data] if chunk_attr else [0] * num_polys

    effective_biome = biome
    if not effective_biome and hasattr(mesh_or_obj, "get"):
        effective_biome = mesh_or_obj.get("mtk:biome_preset", "PLAINS")
    if not effective_biome:
        effective_biome = "PLAINS"

    # Step 1: Load cache context
    base_cache, atlas_dir, standalone_dir, colormaps, manifest_fingerprint = load_material_cache_context(prefs)

    uv_layer = mesh.uv_layers.active if hasattr(mesh, "uv_layers") and mesh.uv_layers else None
    if uv_layer is None and hasattr(mesh, "uv_layers") and len(mesh.uv_layers) > 0:
        uv_layer = mesh.uv_layers[0]

    # Step 2: Reconstruct material slots
    mode_upper = mode.strip().upper()
    if mode_upper == "ATLAS":
        atlas_data = load_atlas_mapping_from_cache(prefs)
        if atlas_data is None:
            atlas_mapping_path = atlas_dir / "atlas_mapping.json"
            if not atlas_mapping_path.exists():
                raise FileNotFoundError(f"Atlas mapping missing at {atlas_mapping_path} and no active .mtkcache found")
            atlas_data = json.loads(atlas_mapping_path.read_text(encoding="utf-8"))
        poly_mat_indices = assign_atlas_chunk_materials(
            mesh=mesh,
            uv_layer=uv_layer,
            atlas_data=atlas_data,
            atlas_dir=atlas_dir,
            face_chunk_ids=face_chunk_ids,
            atlas_uvs=None,
            colormaps=colormaps,
            manifest_fingerprint=manifest_fingerprint,
        )
    else:
        poly_mat_indices = assign_standalone_materials(
            mesh=mesh,
            uv_layer=uv_layer,
            standalone_mapping_path=standalone_dir / "standalone_mapping.json",
            standalone_dir=standalone_dir,
            face_source_keys=face_source_keys,
            local_uvs=None,
            colormaps=colormaps,
            manifest_fingerprint=manifest_fingerprint,
            prefs=prefs,
        )

    # Step 3: Sync material slot attribute (delegated to bridge/mesh.py)
    inject_mesh_provenance_attributes(
        mesh=mesh,
        face_source_keys=face_source_keys,
        poly_mat_indices=poly_mat_indices,
        face_chunk_ids=face_chunk_ids,
        mode=mode_upper,
    )

    # Step 4: Re-apply biome tint attributes
    resolve_and_apply_biome_tint(mesh_or_obj, mesh, face_source_keys, effective_biome, base_cache, prefs)

    mesh.update()
    return {
        "success": True,
        "restored_faces": num_polys,
        "biome": effective_biome,
        "materials_count": len(mesh.materials),
    }


# Backwards compatibility aliases
_inject_face_attribute_string = inject_face_attribute_string
_inject_face_attribute_int = inject_face_attribute_int
_inject_face_attribute_float = inject_face_attribute_float
_inject_face_attribute_float4 = inject_face_attribute_float4
