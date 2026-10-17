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
        resolve_mesh_material_routes,
        reroute_mesh_animation,
        compute_flat_material_props,
        compute_flat_material_props_buffer,
        BiomeResolver,
    )
except (ImportError, ValueError):
    from bridge.material import (
        is_material_bridge_available,
        load_baked_atlas_from_json,
        remap_mesh_multi_uvs,
        resolve_mesh_material_routes,
        reroute_mesh_animation,
        compute_flat_material_props,
        compute_flat_material_props_buffer,
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
        check_asset_cache_status,
        invalidate_asset_cache_memory,
        reload_atlas_images,
        load_atlas_mapping_from_cache,
        load_baked_atlas_from_cache,
        ensure_atlas_textures_extracted,
        ensure_colormaps_extracted,
    )
    from ...bridge.mesh import (
        _get_mesh,
        inject_face_attribute_string,
        inject_face_attribute_int,
        inject_face_attribute_float,
        inject_face_attribute_float4,
        inject_face_attribute_vector,
        resolve_source_texture_keys,
        inject_face_source_texture_keys,
    )
    from .builder.atlas_builder import build_atlas_chunk_material
    from .matching.presets.registry import build_matching_context
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
    from bridge.assets import (
        get_cache_dir,
        get_active_cache_package_path,
        get_cache_fingerprint,
        precompile_stack,
        check_asset_cache_status,
        invalidate_asset_cache_memory,
        reload_atlas_images,
        load_atlas_mapping_from_cache,
        load_baked_atlas_from_cache,
        ensure_atlas_textures_extracted,
        ensure_colormaps_extracted,
    )
    from bridge.mesh import (
        _get_mesh,
        inject_face_attribute_string,
        inject_face_attribute_int,
        inject_face_attribute_float,
        inject_face_attribute_float4,
        inject_face_attribute_vector,
        resolve_source_texture_keys,
        inject_face_source_texture_keys,
    )
    from utils.materials.builder.atlas_builder import build_atlas_chunk_material
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

if "ATTR_MATERIAL_PROPS" not in globals():
    ATTR_SOURCE_TEXTURE_KEY = "mtk_source_texture_key"
    ATTR_MATERIAL_SLOT = "mtk_material_slot"
    ATTR_ATLAS_CHUNK_ID = "mtk_atlas_chunk_id"
    ATTR_ATLAS_TEXTURE_ID = "mtk_atlas_texture_id"
    ATTR_UV_MODE = "mtk_uv_mode"
    ATTR_UV_TILING_TRANSFORM = "mtk_uv_tiling_transform"
    ATTR_UV_TRANSFORM = "mtk_uv_transform"
    ATTR_UV_ROTATION = "mtk_uv_rotation"
    ATTR_BIOME_TINT_DATA = "mtk_biome_tint_data"
    ATTR_BIOME_TINT_COLOR = "mtk_biome_tint_color"
    ATTR_COLORMAP_UV = "mtk_colormap_uv"
    ATTR_MATERIAL_PROPS = "mtk_material_props"


def animated_textures_enabled(prefs: Optional[Any] = None) -> bool:
    """Read the animated-texture preference with a safe True fallback."""
    raw = getattr(prefs, "enable_animated_textures", True) if prefs is not None else True
    return raw if isinstance(raw, bool) else True


def ensure_stack_precompiled(prefs: Optional[Any] = None) -> Path:
    """Ensure asset caches exist in persistent storage and match configured pack stack."""
    base_cache = get_cache_dir(prefs)
    status = check_asset_cache_status(prefs)
    if status in ("MISSING", "STALE"):
        logger.info("Asset cache is %s; running automated precompilation...", status)
        try:
            precompile_stack(prefs)
            invalidate_asset_cache_memory()
            try:
                reload_atlas_images(prefs)
            except Exception:
                pass
        except Exception as e:
            logger.warning("Automated precompilation in ensure_stack_precompiled failed: %s", e)
    return base_cache


# =============================================================================
# Pipeline Step Processors
# =============================================================================

def _load_atlas_data_and_baked_atlas(atlas_dir: Path, prefs: Optional[Any] = None) -> Tuple[Dict[str, Any], Any]:
    """Load atlas mapping JSON plus the native BakedAtlas used for Rust routing."""
    atlas_data = load_atlas_mapping_from_cache(prefs)
    baked_atlas = load_baked_atlas_from_cache(prefs)
    if atlas_data is None:
        atlas_mapping_path = atlas_dir / "atlas_mapping.json"
        if not atlas_mapping_path.exists():
            raise FileNotFoundError(
                f"Atlas mapping missing at {atlas_mapping_path} and no active .mtkcache found"
            )
        atlas_json_str = atlas_mapping_path.read_text(encoding="utf-8")
        atlas_data = json.loads(atlas_json_str)
        baked_atlas = load_baked_atlas_from_json(atlas_json_str)
    elif baked_atlas is None:
        baked_atlas = load_baked_atlas_from_json(json.dumps(atlas_data))
    return atlas_data, baked_atlas


def load_material_cache_context(
    prefs: Optional[Any] = None,
) -> Tuple[Path, Path, Dict[str, Path], Optional[str]]:
    """
    Step 1: Ensure assets are precompiled and discover cache directories, colormaps, and manifest.
    """
    base_cache = ensure_stack_precompiled(prefs)
    atlas_dir = ensure_atlas_textures_extracted(prefs)
    colormaps = ensure_colormaps_extracted(prefs)
    manifest_fingerprint = get_cache_fingerprint(prefs)

    return base_cache, atlas_dir, colormaps, manifest_fingerprint


def extract_face_material_context(
    mesh: Any,
) -> Tuple[List[str], List[Tuple[int, int]], array.array, Any, Optional[List[str]]]:
    """
    Step 2: Extract face materials, loop ranges, loop UVs, and existing provenance keys from mesh.

    Uses bulk `foreach_get` plus NumPy object-array indexing instead of per-polygon
    RNA access. This is the hot path for large external meshes (hundreds of
    thousands of faces).
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

    # Bulk-extract polygon slot indices and loop ranges.
    poly_mats = np.empty(num_polys, dtype=np.int32)
    mesh.polygons.foreach_get("material_index", poly_mats)
    loop_starts = np.empty(num_polys, dtype=np.int32)
    loop_totals = np.empty(num_polys, dtype=np.int32)
    mesh.polygons.foreach_get("loop_start", loop_starts)
    mesh.polygons.foreach_get("loop_total", loop_totals)

    # Read each material slot once (there are usually only a handful).
    slot_names: List[str] = []
    slot_is_mtk: List[bool] = []
    slot_source_ids: List[str] = []
    for mat_slot in mesh.materials:
        if not mat_slot:
            slot_names.append("default")
            slot_is_mtk.append(True)
            slot_source_ids.append("")
            continue

        mat_name = str(getattr(mat_slot, "name", "default") or "default")
        mat_lower = mat_name.strip().lower()
        slot_id = (
            mat_slot.get("mtk_source_texture_key")
            or mat_slot.get("mtk:material_id")
            or mat_slot.get("mtk:source_texture")
            or ""
        )
        is_mtk = mat_lower.startswith(("mtk:", "mtk_", "mc_atlas", "default")) or bool(
            mat_slot.get("mtk:material_id")
            or mat_slot.get("mtk_source_texture_key")
            or mat_slot.get("mtk_material_mode")
        )
        slot_names.append(mat_name)
        slot_is_mtk.append(is_mtk)
        slot_source_ids.append(str(slot_id) if slot_id else "")

    num_slots = len(slot_names)
    if num_slots > 0:
        valid_slot = (poly_mats >= 0) & (poly_mats < num_slots)
        safe_mats = np.where(valid_slot, poly_mats, 0)
        slot_names_arr = np.array(slot_names, dtype=object)
        face_names = slot_names_arr[safe_mats]
        face_is_mtk = np.array(slot_is_mtk, dtype=bool)[safe_mats] & valid_slot
        face_names = np.where(valid_slot, face_names, "default")

        if existing_prov_keys is not None:
            existing_arr = np.array(existing_prov_keys, dtype=object)
            valid_prov = (existing_arr != "") & (existing_arr != "mozi:fallback")
            face_names = np.where(face_is_mtk & valid_prov, existing_arr, face_names)
        else:
            slot_ids_arr = np.array(slot_source_ids, dtype=object)
            slot_ids = slot_ids_arr[safe_mats]
            valid_ids = slot_ids != ""
            face_names = np.where(face_is_mtk & valid_ids, slot_ids, face_names)
    else:
        face_names = np.full(num_polys, "default", dtype=object)

    face_materials: List[str] = face_names.tolist()
    face_loop_ranges: List[Tuple[int, int]] = list(zip(loop_starts.tolist(), loop_totals.tolist()))

    return face_materials, face_loop_ranges, loop_uvs, uv_layer, existing_prov_keys


def remap_face_materials_and_uvs(
    baked_atlas: Any,
    atlas_data: Dict[str, Any],
    face_materials: List[str],
    loop_uvs: array.array,
    face_loop_ranges: List[Tuple[int, int]],
    origin: str,
    existing_prov_keys: Optional[List[str]],
    enable_animated_textures: bool = False,
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
        enable_animated_textures=enable_animated_textures,
    )

    face_texture_ids: List[int] = remap_result["face_texture_ids"]
    # Build the texture-id -> canonical key table from BOTH the static Frame-0
    # sprites and the dedicated animated sprites. Animated faces receive texture
    # ids from `anim_sprites`, so omitting that map silently degrades their
    # provenance to `mozi:fallback` and breaks later animation reconciliation.
    id_to_key: Dict[int, str] = {}
    for bucket_name in ("sprites", "anim_sprites"):
        for key, sp in atlas_data.get(bucket_name, {}).items():
            tid = sp.get("texture_id")
            if tid is not None:
                id_to_key[int(tid)] = key

    face_source_keys: List[str] = []
    if face_texture_ids:
        tex_ids = np.asarray(face_texture_ids, dtype=np.int64)
        max_id = int(tex_ids.max()) if tex_ids.size else -1
        if id_to_key and 0 <= max_id <= 1_000_000:
            table = np.full(max_id + 1, "", dtype=object)
            for tid, key in id_to_key.items():
                if 0 <= tid <= max_id:
                    table[tid] = key
            keys_arr = table[tex_ids]
        elif id_to_key:
            keys_arr = np.fromiter(
                (id_to_key.get(int(tid), "") for tid in tex_ids),
                dtype=object,
                count=len(tex_ids),
            )
        else:
            keys_arr = np.full(len(tex_ids), "", dtype=object)

        if existing_prov_keys and len(existing_prov_keys) == len(tex_ids):
            existing_arr = np.asarray(existing_prov_keys, dtype=object)
            missing = keys_arr == ""
            valid_fallback = missing & (existing_arr != "") & (existing_arr != "mozi:fallback")
            keys_arr = np.where(valid_fallback, existing_arr, keys_arr)

        keys_arr[keys_arr == ""] = "mozi:fallback"
        face_source_keys = keys_arr.tolist()

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




def inject_mesh_provenance_attributes(
    mesh: Any,
    face_source_keys: List[str],
    poly_mat_indices: array.array,
    face_chunk_ids: List[int],
    face_texture_ids: Optional[List[int]] = None,
    face_uv_transforms: Optional[List[List[float]]] = None,
    face_uv_rotations: Optional[List[float]] = None,
    face_anim_timing: Optional[List[List[float]]] = None,
    face_anim_frame_size: Optional[List[List[float]]] = None,
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
        flat_transforms = np.asarray(face_uv_transforms, dtype=np.float32).ravel()
        inject_face_attribute_float4(mesh, "mtk_uv_tiling_transform", flat_transforms)
        inject_face_attribute_float4(mesh, "mtk_uv_transform", flat_transforms)

    if face_uv_rotations is not None:
        inject_face_attribute_float(mesh, "mtk_uv_rotation", face_uv_rotations)

    # Inject per-face animation timing/metrics consumed by MC_Animation_Scheduler_Default
    # and MC_Animated_UV_Mapping. Static faces receive safe neutral defaults so the
    # attributes are never absent on an animated-capable material.
    if face_anim_timing is not None and len(face_anim_timing) >= num_polys:
        timing = face_anim_timing[:num_polys]
        sizes = face_anim_frame_size[:num_polys] if face_anim_frame_size is not None and len(face_anim_frame_size) >= num_polys else [[16.0, 16.0, 0.0]] * num_polys
        inject_face_attribute_vector(
            mesh, "mtk_anim_timing", [float(v) for t in timing for v in t]
        )
        inject_face_attribute_vector(
            mesh, "mtk_anim_frame_size", [float(v) for s in sizes for v in s]
        )
        inject_face_attribute_float(mesh, "mtk_anim_total_frames", [float(t[0]) for t in timing])
        inject_face_attribute_float(mesh, "mtk_anim_frametime", [float(t[1]) for t in timing])
        inject_face_attribute_float(mesh, "mtk_anim_interpolate", [float(t[2]) for t in timing])
        inject_face_attribute_float(mesh, "mtk_anim_frame_width", [float(s[0]) for s in sizes])
        inject_face_attribute_float(mesh, "mtk_anim_frame_height", [float(s[1]) for s in sizes])

    # Inject packed material properties (Emission, Thin Wall, Transmission, Sticker Threshold)
    if face_source_keys:
        keys = (
            face_source_keys[:num_polys]
            if len(face_source_keys) >= num_polys
            else face_source_keys + [""] * (num_polys - len(face_source_keys))
        )
        flat_props = compute_flat_material_props_buffer(keys)
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

    if biome.upper() == "WORLD":
        from .biome.updater import resolve_and_apply_world_biome_tint
        if resolve_and_apply_world_biome_tint(
            mesh_or_obj=mesh_or_obj,
            mesh=mesh,
            face_source_keys=face_source_keys,
            prefs=prefs,
            base_cache=base_cache,
        ):
            return

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
        mode: Material mode (defaults to "ATLAS").
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

    mode_upper = "ATLAS"

    # Step 1: Load cache context & precompiled assets
    base_cache, atlas_dir, colormaps, manifest_fingerprint = load_material_cache_context(prefs)

    atlas_data, baked_atlas = _load_atlas_data_and_baked_atlas(atlas_dir, prefs)
    anim_enabled = animated_textures_enabled(prefs)

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
        enable_animated_textures=anim_enabled,
    )

    # Step 4: Construct and assign materials
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

    # Step 5: Inject mesh provenance attributes (delegated to bridge/mesh.py)
    inject_mesh_provenance_attributes(
        mesh=mesh,
        face_source_keys=remap["face_source_keys"],
        poly_mat_indices=poly_mat_indices,
        face_chunk_ids=remap["face_chunk_ids"],
        face_texture_ids=remap["face_texture_ids"],
        face_uv_transforms=remap["face_uv_transforms"],
        face_uv_rotations=remap.get("face_uv_rotations", [0.0] * len(mesh.polygons)),
        face_anim_timing=remap.get("face_anim_timing"),
        face_anim_frame_size=remap.get("face_anim_frame_size"),
        mode=mode_upper,
    )

    # Step 6: Compute & apply biome tint attributes
    resolve_and_apply_biome_tint(mesh_or_obj, mesh, remap["face_source_keys"], biome, base_cache, prefs)

    if hasattr(mesh, "__setitem__"):
        try:
            mesh["mtk_enable_animated_textures"] = bool(anim_enabled)
        except Exception:
            pass

    mesh.update()
    animated_faces = sum(1 for flag in remap.get("face_is_animated", []) if flag)
    return {
        "success": True,
        "mode": mode_upper,
        "biome": biome,
        "face_count": len(mesh.polygons),
        "materials_count": len(mesh.materials),
        "unmapped_faces": remap["unmapped_faces"],
        "animated_faces": animated_faces,
        "enable_animated_textures": bool(anim_enabled),
    }


def restore_materials_from_provenance(
    mesh_or_obj: Any,
    mode: str = "ATLAS",
    biome: Optional[str] = None,
    prefs: Optional[Any] = None,
    reconcile_animation: bool = False,
    enable_animated_textures: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Reconstructs Blender material slots, nodes, and assignments purely from mesh face provenance attributes.

    Args:
        mesh_or_obj: Blender mesh or object with mtk_source_texture_key attributes.
        mode: Target reconstruction mode ("ATLAS").
        biome: Optional biome preset to restore. Defaults to object property or "PLAINS".
        prefs: Add-on preferences reference.
        reconcile_animation: When True, re-resolve static/animated chunk routing from
            source keys and re-project existing atlas UVs to the new sprite. This is
            required when the user toggles animated textures after a previous replacement.
        enable_animated_textures: Optional explicit animation preference override.
            Defaults to the add-on preference.
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
        return {
            "success": False,
            "message": "Mesh lacks required mtk_source_texture_key / mtk_source_texture_idx attribute for provenance.",
        }

    effective_biome = biome
    if not effective_biome and hasattr(mesh_or_obj, "get"):
        effective_biome = mesh_or_obj.get("mtk:biome_preset", "PLAINS")
    if not effective_biome:
        effective_biome = "PLAINS"

    anim_enabled = (
        bool(enable_animated_textures)
        if enable_animated_textures is not None
        else animated_textures_enabled(prefs)
    )

    # Step 1: Load cache context and atlas routing data
    base_cache, atlas_dir, colormaps, manifest_fingerprint = load_material_cache_context(prefs)
    atlas_data, baked_atlas = _load_atlas_data_and_baked_atlas(atlas_dir, prefs)

    uv_layer = mesh.uv_layers.active if hasattr(mesh, "uv_layers") and mesh.uv_layers else None
    if uv_layer is None and hasattr(mesh, "uv_layers") and len(mesh.uv_layers) > 0:
        uv_layer = mesh.uv_layers[0]

    chunk_attr = mesh.attributes.get("mtk_atlas_chunk_id") if hasattr(mesh, "attributes") else None
    if chunk_attr is not None and len(chunk_attr.data) == num_polys:
        if hasattr(chunk_attr.data, "foreach_get"):
            chunk_ids_np = np.empty(num_polys, dtype=np.int32)
            chunk_attr.data.foreach_get("value", chunk_ids_np)
            face_chunk_ids = [int(x) for x in chunk_ids_np]
        else:
            face_chunk_ids = [int(elem.value) for elem in chunk_attr.data]
    else:
        face_chunk_ids = [0] * num_polys

    face_texture_ids: Optional[List[int]] = None
    atlas_uvs: Optional[List[float]] = None
    face_anim_timing: Optional[List[List[float]]] = None
    face_anim_frame_size: Optional[List[List[float]]] = None
    animation_reconciled = False

    if reconcile_animation and uv_layer is not None:
        # Existing UVs are Atlas UVs, so decode them from the previous sprite and
        # re-project them into the new static/animated sprite in Rust.
        num_loops = len(mesh.loops)
        loop_uvs = array.array("f", [0.0]) * (num_loops * 2)
        uv_layer.data.foreach_get("uv", loop_uvs)

        if hasattr(mesh.polygons, "foreach_get"):
            starts = np.empty(num_polys, dtype=np.int32)
            totals = np.empty(num_polys, dtype=np.int32)
            mesh.polygons.foreach_get("loop_start", starts)
            mesh.polygons.foreach_get("loop_total", totals)
            face_loop_ranges = list(zip(starts.tolist(), totals.tolist()))
        else:
            face_loop_ranges = [(int(p.loop_start), int(p.loop_total)) for p in mesh.polygons]

        reroute = reroute_mesh_animation(
            loop_uvs=loop_uvs,
            face_loop_ranges=face_loop_ranges,
            face_texture_keys=face_source_keys,
            face_old_chunk_ids=face_chunk_ids,
            atlas=baked_atlas,
            enable_animated_textures=anim_enabled,
        )
        face_chunk_ids = [int(x) for x in reroute["face_chunk_ids"]]
        face_texture_ids = [int(x) for x in reroute["face_texture_ids"]]
        atlas_uvs = reroute["atlas_uvs"]
        face_anim_timing = reroute.get("face_anim_timing")
        face_anim_frame_size = reroute.get("face_anim_frame_size")
        animation_reconciled = True

    # Step 2: Reconstruct material slots (optionally reusing re-projected atlas UVs)
    poly_mat_indices = assign_atlas_chunk_materials(
        mesh=mesh,
        uv_layer=uv_layer,
        atlas_data=atlas_data,
        atlas_dir=atlas_dir,
        face_chunk_ids=face_chunk_ids,
        atlas_uvs=atlas_uvs,
        colormaps=colormaps,
        manifest_fingerprint=manifest_fingerprint,
    )

    # Step 3: Sync material slot / animation attributes (delegated to bridge/mesh.py)
    inject_mesh_provenance_attributes(
        mesh=mesh,
        face_source_keys=face_source_keys,
        poly_mat_indices=poly_mat_indices,
        face_chunk_ids=face_chunk_ids,
        face_texture_ids=face_texture_ids,
        face_anim_timing=face_anim_timing,
        face_anim_frame_size=face_anim_frame_size,
        mode="ATLAS",
    )

    if animation_reconciled and hasattr(mesh, "__setitem__"):
        try:
            mesh["mtk_enable_animated_textures"] = bool(anim_enabled)
        except Exception:
            pass

    # Step 4: Re-apply biome tint attributes
    resolve_and_apply_biome_tint(mesh_or_obj, mesh, face_source_keys, effective_biome, base_cache, prefs)

    mesh.update()
    animated_faces = sum(1 for flag in (face_anim_timing or []) if flag and flag[0] > 1.0)
    return {
        "success": True,
        "restored_faces": num_polys,
        "biome": effective_biome,
        "materials_count": len(mesh.materials),
        "animated_faces": animated_faces,
        "animation_reconciled": animation_reconciled,
        "enable_animated_textures": bool(anim_enabled),
    }


# Backwards compatibility aliases
_inject_face_attribute_string = inject_face_attribute_string
_inject_face_attribute_int = inject_face_attribute_int
_inject_face_attribute_float = inject_face_attribute_float
_inject_face_attribute_float4 = inject_face_attribute_float4
