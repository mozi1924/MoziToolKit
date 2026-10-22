"""
MoziToolKit Material Replacement & Provenance Pipeline.
Executes pure Rust (libmtk) material resolution, UV remapping,
LabPBR 1.3 shader construction, and mesh attribute synchronization.
"""

from __future__ import annotations

import array
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger("MoziToolKit.Material.Pipeline")

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from ...bridge.material import (
    is_material_bridge_available,
    load_baked_atlas_from_json,
    remap_mesh_multi_uvs_paletted,
    reroute_mesh_animation,
    resolve_mesh_material_routes,
    build_material_palette,
)


def __getattr__(name: str) -> Any:
    if name == "HAS_LIBMTK":
        return is_material_bridge_available()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

from ...utils.assets import (
    get_cache_dir,
    check_asset_cache_status,
)
from ...bridge.assets import (
    get_cache_fingerprint,
    precompile_stack,
    invalidate_asset_cache_memory,
    load_atlas_mapping_from_cache,
    load_baked_atlas_from_cache,
    ensure_atlas_textures_extracted,
)
from ...bridge.mesh import (
    _get_mesh,
    inject_face_attribute_string,
    inject_face_attribute_int,
    inject_face_attribute_float,
    inject_face_attribute_float4,
    inject_face_attribute_vector,
    resolve_source_texture_keys,
    resolve_source_texture_keys_paletted,
    inject_face_source_texture_palette,
)
from .builder.atlas_builder import build_atlas_chunk_material
from .matching.presets.registry import build_matching_context
from .cleaner import (
    clean_obsolete_mesh_attributes,
    mesh_has_animation,
    prune_optional_mesh_attributes,
)
from .biome import (
    get_or_load_biome_resolver,
    compute_biome_tint_attributes,
    compute_biome_tint_attributes_paletted,
    apply_biome_tint_attributes,
)
from .constants import (
    ATTR_SOURCE_TEXTURE_KEY,
    ATTR_ATLAS_CHUNK_ID,
    ATTR_UV_TRANSFORM,
    ATTR_UV_ROTATION,
    ATTR_ANIM_TIMING,
    ATTR_ANIM_FRAME_SIZE,
    ATTR_BIOME_TINT_DATA,
    ATTR_BIOME_TINT_COLOR,
)

from .uv_layers import (
    compute_atlas_layout_hash,
    find_local_uv_layer,
    get_stored_layout_hash,
    read_uv_layer,
    resolve_uv_layers,
    set_stored_layout_hash,
)


def animated_textures_enabled(prefs: Optional[Any] = None) -> bool:
    """Read the animated-texture preference with a safe True fallback."""
    raw = getattr(prefs, "enable_animated_textures", True) if prefs is not None else True
    return raw if isinstance(raw, bool) else True


def ensure_stack_precompiled(prefs: Optional[Any] = None) -> Path:
    """Ensure asset caches exist in persistent storage and match configured pack stack."""
    base_cache = get_cache_dir(prefs)
    status = check_asset_cache_status(prefs)
    from ...bridge.assets.compat import compat_stamp_matches

    if status in ("MISSING", "STALE") or (
        status == "READY" and not compat_stamp_matches(base_cache)
    ):
        has_custom_packs = prefs is not None and hasattr(prefs, "resource_packs")
        if not (not has_custom_packs and os.environ.get("MOZI_CACHE_DIR")):
            logger.info("Asset cache is %s; running automated precompilation...", status)
            try:
                precompile_stack(prefs)
                invalidate_asset_cache_memory()
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
) -> Tuple[Path, Path, Optional[str]]:
    """
    Step 1: Ensure assets are precompiled and discover the cache directory and manifest.
    Resource-pack colormaps are resolved inside Rust when the cache is opened.
    """
    base_cache = ensure_stack_precompiled(prefs)
    atlas_dir = ensure_atlas_textures_extracted(prefs)
    manifest_fingerprint = get_cache_fingerprint(prefs)

    return base_cache, atlas_dir, manifest_fingerprint


def extract_face_material_palette_context(
    mesh: Any,
    uv_layer: Optional[Any] = None,
) -> Tuple[
    List[str],
    Any,
    List[Tuple[int, int]],
    array.array,
    Any,
    List[str],
    Any,
]:
    """
    Extract face material names as a compact palette + per-face indices.

    ``uv_layer`` must be the preserved local UV map for external meshes. When
    omitted, the local map is resolved without creating an atlas map.

    Returns:
        (palette, indices, face_loop_ranges, loop_uvs, uv_layer,
         existing_key_palette, existing_key_indices)

    Uses bulk `foreach_get` plus NumPy indexing; no per-polygon RNA access.
    """
    num_polys = len(mesh.polygons)
    num_loops = len(mesh.loops)

    if uv_layer is None:
        uv_layer = find_local_uv_layer(mesh)
    if uv_layer is None:
        uv_layer = mesh.uv_layers.new(name="UVMap")

    loop_uvs = read_uv_layer(uv_layer, num_loops)

    existing_key_palette, existing_key_indices = resolve_source_texture_keys_paletted(mesh)
    if len(existing_key_indices) != num_polys:
        existing_key_palette, existing_key_indices = [], np.empty(0, dtype=np.uint32)

    # Bulk-extract polygon slot indices and loop ranges.
    poly_mats = np.empty(num_polys, dtype=np.int32)
    mesh.polygons.foreach_get("material_index", poly_mats)
    loop_starts = np.empty(num_polys, dtype=np.int32)
    loop_totals = np.empty(num_polys, dtype=np.int32)
    mesh.polygons.foreach_get("loop_start", loop_starts)
    mesh.polygons.foreach_get("loop_total", loop_totals)

    # Read each material slot once (usually only a handful).
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

    palette, indices = build_material_palette(
        slot_names,
        slot_is_mtk,
        slot_source_ids,
        poly_mats,
        existing_key_palette,
        existing_key_indices,
    )

    face_loop_ranges: List[Tuple[int, int]] = list(zip(loop_starts.tolist(), loop_totals.tolist()))

    return (
        palette,
        indices,
        face_loop_ranges,
        loop_uvs,
        uv_layer,
        existing_key_palette,
        existing_key_indices,
    )


def remap_face_materials_and_uvs_paletted(
    baked_atlas: Any,
    face_material_palette: List[str],
    face_material_indices: Any,
    loop_uvs: array.array,
    face_loop_ranges: List[Tuple[int, int]],
    origin: str,
    existing_key_palette: Optional[List[str]],
    existing_key_indices: Any,
    enable_animated_textures: bool = False,
) -> Dict[str, Any]:
    """Palette-native Step 3: Rust remap + compact source-key provenance."""
    alias_map, grid_spec = build_matching_context(face_material_palette, origin=origin)
    return remap_mesh_multi_uvs_paletted(
        loop_uvs=loop_uvs,
        face_material_palette=face_material_palette,
        face_material_indices=face_material_indices,
        face_loop_ranges=face_loop_ranges,
        atlas=baked_atlas,
        alias_map=alias_map,
        grid_spec=grid_spec,
        existing_key_palette=existing_key_palette if existing_key_palette else None,
        existing_key_indices=(
            existing_key_indices
            if existing_key_indices is not None and len(existing_key_indices)
            else None
        ),
        enable_animated_textures=enable_animated_textures,
    )


def assign_atlas_chunk_materials(
    mesh: Any,
    uv_layer: Optional[Any],
    atlas_data: Dict[str, Any],
    atlas_dir: Path,
    face_chunk_ids: List[int],
    atlas_uvs: Optional[List[float]],
    manifest_fingerprint: Optional[str],
    force_rebuild_materials: bool = False,
    material_namespace: Optional[str] = None,
) -> array.array:
    """
    Step 4A: Construct Atlas Chunk materials, assign to mesh material slots, and optionally set Atlas UVs.
    """
    num_polys = len(mesh.polygons)
    if isinstance(face_chunk_ids, (list, tuple)):
        chunk_arr = np.asarray(face_chunk_ids, dtype=np.int32)
    else:
        chunk_arr = np.frombuffer(face_chunk_ids, dtype=np.int32)
    if chunk_arr.size != num_polys:
        chunk_arr = np.resize(chunk_arr, num_polys)

    unique_chunks = np.unique(chunk_arr)
    chunk_to_slot: Dict[int, int] = {}
    mesh.materials.clear()

    chunk_meta_list = atlas_data.get("chunks", [])
    chunk_meta_map: Dict[int, Dict[str, Any]] = {
        c.get("chunk_id", idx): c for idx, c in enumerate(chunk_meta_list)
    }

    for slot_idx, chunk_id_raw in enumerate(unique_chunks):
        chunk_id = int(chunk_id_raw)
        cm = chunk_meta_map.get(chunk_id, {})
        cat = cm.get("category", "blocks")
        c_idx = cm.get("category_chunk_index", chunk_id + 1)
        is_anim = cm.get("is_animated", False)
        stem = f"{cat}_anim_chunk_{c_idx:03}" if is_anim else f"{cat}_chunk_{c_idx:03}"

        albedo_file = atlas_dir / f"{stem}.png"
        normal_file = atlas_dir / f"{stem}_n.png" if cm.get("has_normal") else None
        orm_file = atlas_dir / f"{stem}_orm.png" if cm.get("has_orm") else None
        aux_file = atlas_dir / f"{stem}_aux.png" if cm.get("has_aux") else None
        overlay_file = atlas_dir / f"{stem}_overlay.png" if cm.get("has_overlay") else None
        chunk_width = float(cm.get("width", 1024))
        chunk_height = float(cm.get("height", 512))
        uv_map_name = uv_layer.name if uv_layer else "UVMap"
        material_name = None
        if material_namespace == "EXT":
            # External meshes sample MTK_Atlas instead of the native UVMap. Use a
            # separate material namespace so they never share (and fight over) the
            # global chunk materials used by MTK-generated meshes.
            if is_anim:
                material_name = f"MTK:Atlas:Ext:anim:{cat}:{c_idx:03}"
            else:
                material_name = f"MTK:Atlas:Ext:{cat}:{c_idx:03}"

        mat = build_atlas_chunk_material(
            chunk_id=chunk_id,
            albedo_path=albedo_file,
            normal_path=normal_file,
            orm_path=orm_file,
            aux_path=aux_file,
            overlay_path=overlay_file,
            category=cat,
            category_chunk_index=c_idx,
            is_animated=is_anim,
            stack_fingerprint=manifest_fingerprint,
            atlas_width=chunk_width,
            atlas_height=chunk_height,
            tile_width=16.0,
            tile_height=16.0,
            uv_map_name=uv_map_name,
            material_name=material_name,
            force_rebuild=force_rebuild_materials,
        )
        mesh.materials.append(mat)
        chunk_to_slot[chunk_id] = slot_idx

    # `unique_chunks` is sorted, so searchsorted yields exactly the slot index.
    poly_mat_indices = np.searchsorted(unique_chunks, chunk_arr).astype(np.int32)

    if atlas_uvs is not None and uv_layer is not None:
        if isinstance(atlas_uvs, (list, tuple)):
            atlas_uv_np = np.ascontiguousarray(atlas_uvs, dtype=np.float32)
        else:
            atlas_uv_np = np.frombuffer(atlas_uvs, dtype=np.float32)
        uv_attr = mesh.attributes.get(uv_layer.name) if hasattr(mesh, "attributes") else None
        if uv_attr is not None and len(uv_attr.data) * 2 == atlas_uv_np.size:
            uv_attr.data.foreach_set("vector", atlas_uv_np)
        else:
            uv_layer.data.foreach_set("uv", atlas_uv_np)

    mat_attr = mesh.attributes.get("material_index") if hasattr(mesh, "attributes") else None
    if mat_attr is not None and len(mat_attr.data) == poly_mat_indices.size:
        mat_attr.data.foreach_set("value", poly_mat_indices)
    else:
        mesh.polygons.foreach_set("material_index", poly_mat_indices)
    return poly_mat_indices




def inject_mesh_provenance_attributes(
    mesh: Any,
    face_source_keys: Optional[List[str]] = None,
    face_chunk_ids: Any = None,
    face_uv_transforms: Optional[Any] = None,
    face_uv_rotations: Optional[Any] = None,
    face_anim_timing: Optional[Any] = None,
    face_anim_frame_size: Optional[Any] = None,
    face_source_key_palette: Optional[List[str]] = None,
    face_source_key_indices: Optional[Any] = None,
) -> None:
    """Step 5: Inject provenance and shader-driver attributes.

    Accepts either per-face string lists or the compact palette + index form and
    buffer-protocol metrics (numpy arrays / Rust memoryviews).
    """
    num_polys = len(mesh.polygons)

    if face_source_key_palette is not None and face_source_key_indices is not None:
        inject_face_source_texture_palette(
            mesh, face_source_key_palette, face_source_key_indices
        )
    elif face_source_keys is not None:
        inject_face_attribute_string(mesh, ATTR_SOURCE_TEXTURE_KEY, face_source_keys)

    if face_chunk_ids is not None:
        inject_face_attribute_int(mesh, ATTR_ATLAS_CHUNK_ID, face_chunk_ids)

    if face_uv_transforms is not None:
        if isinstance(face_uv_transforms, (list, tuple)):
            flat_transforms = np.ascontiguousarray(face_uv_transforms, dtype=np.float32).ravel()
        else:
            flat_transforms = np.frombuffer(face_uv_transforms, dtype=np.float32)
        inject_face_attribute_float4(mesh, ATTR_UV_TRANSFORM, flat_transforms)

    if face_uv_rotations is not None:
        inject_face_attribute_float(mesh, ATTR_UV_ROTATION, face_uv_rotations)

    # Per-face animation timing/metrics consumed by MC_Animation_Scheduler_Default
    # and MC_Animated_UV_Mapping.
    if face_anim_timing is not None:
        if isinstance(face_anim_timing, (list, tuple)):
            timing = np.ascontiguousarray(face_anim_timing, dtype=np.float32).ravel()
        else:
            timing = np.frombuffer(face_anim_timing, dtype=np.float32)
        if timing.size >= num_polys * 3:
            timing = timing[: num_polys * 3]
            if face_anim_frame_size is None:
                sizes = np.tile(np.array([16.0, 16.0, 0.0], dtype=np.float32), num_polys)
            elif isinstance(face_anim_frame_size, (list, tuple)):
                sizes = np.ascontiguousarray(face_anim_frame_size, dtype=np.float32).ravel()
            else:
                sizes = np.frombuffer(face_anim_frame_size, dtype=np.float32)
            if sizes.size >= num_polys * 3:
                sizes = sizes[: num_polys * 3]
                inject_face_attribute_vector(mesh, ATTR_ANIM_TIMING, timing)
                inject_face_attribute_vector(mesh, ATTR_ANIM_FRAME_SIZE, sizes)

    clean_obsolete_mesh_attributes(mesh)


def resolve_and_apply_biome_tint(
    mesh_or_obj: Any,
    mesh: Any,
    face_source_keys: Optional[List[str]],
    biome: str,
    base_cache: Path,
    prefs: Optional[Any] = None,
    source_key_palette: Optional[Sequence[str]] = None,
    source_key_indices: Optional[Any] = None,
) -> None:
    """
    Step 6: Compute and apply biome tint attributes and colormap UVs based on current preset.

    Palette + index inputs keep the 1M-face path free of per-face Python strings.
    The list-based path remains only for WORLD (per-voxel 3D biome sampling) and
    callers that have not migrated yet.
    """
    biome_resolver = get_or_load_biome_resolver(cache_dir=base_cache, prefs=prefs)
    is_world = biome.upper() == "WORLD"

    if is_world:
        if face_source_keys is None and source_key_palette is not None and source_key_indices is not None:
            face_source_keys = np.asarray(source_key_palette, dtype=object)[source_key_indices].tolist()
        from .biome.updater import resolve_and_apply_world_biome_tint
        if resolve_and_apply_world_biome_tint(
            mesh_or_obj=mesh_or_obj,
            mesh=mesh,
            face_source_keys=face_source_keys or [],
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

    if not is_world and source_key_palette is not None and source_key_indices is not None:
        packed_tint_data, tint_colors = compute_biome_tint_attributes_paletted(
            source_key_palette,
            source_key_indices,
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
    else:
        if face_source_keys is None:
            return
        packed_tint_data, tint_colors = compute_biome_tint_attributes(
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
    apply_biome_tint_attributes(mesh, packed_tint_data, tint_colors)

    if hasattr(mesh_or_obj, "__setitem__"):
        try:
            mesh_or_obj["mtk:biome_preset"] = biome
        except Exception:
            pass


def _needs_animation_reconcile(mesh: Any, prefs: Optional[Any] = None) -> bool:
    """Decide whether static/animated routing must be re-resolved."""
    anim_enabled = animated_textures_enabled(prefs)
    stored = mesh.get("mtk_enable_animated_textures", None) if hasattr(mesh, "get") else None
    if stored is not None:
        return bool(stored) != anim_enabled
    return not (hasattr(mesh, "attributes") and "mtk_anim_timing" in mesh.attributes)


def _is_legacy_single_uv_atlas_mesh(mesh: Any) -> bool:
    """
    Detect meshes produced by the removed single-UV atlas pipeline.

    They keep already-baked atlas UVs in their sole UV layer and have no
    recoverable local layout, so they must be re-imported.
    """
    if mesh is None or not hasattr(mesh, "uv_layers"):
        return False
    try:
        if len(mesh.uv_layers) != 1:
            return False
    except Exception:
        return False
    try:
        if mesh.get(LOCAL_UV_LAYER_PROP) or mesh.get(ATLAS_UV_LAYER_PROP):
            return False
    except Exception:
        pass
    attributes = getattr(mesh, "attributes", None)
    if attributes is None:
        return False
    try:
        has_provenance = (
            "mtk_source_texture_key" in attributes
            or "mtk_source_texture_idx" in attributes
        )
        has_atlas_routing = "mtk_atlas_chunk_id" in attributes
    except Exception:
        return False
    return bool(has_provenance and has_atlas_routing)


def _is_external_object(obj: Any) -> bool:
    """Best-effort ownership check used to pick the external material namespace."""
    if obj is None:
        return False
    from ..mesh.ownership import ORIGIN_EXTERNAL, classify_origin
    try:
        return classify_origin(obj) == ORIGIN_EXTERNAL
    except Exception:
        return False


def replace_materials(
    mesh_or_obj: Any,
    mode: str = "ATLAS",
    origin: str = "AUTO",
    biome: str = "PLAINS",
    prefs: Optional[Any] = None,
    force_remap: bool = False,
    reconcile_animation: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Executes end-to-end material replacement on a Blender mesh object using libmtk Rust backend.

    External meshes keep their original local UV map and receive a separate
    ``MTK_Atlas`` UV map. When the atlas layout is unchanged (same sprite rects,
    routing and chunk geometry), the existing atlas UVs are reused and only the
    materials/textures are rebound. When the layout changes, atlas UVs are
    re-mapped from the preserved local UVs.

    Args:
        mesh_or_obj: A `bpy.types.Object` (type MESH) or `bpy.types.Mesh`.
        mode: Material mode (defaults to "ATLAS").
        origin: Format heuristic - "AUTO", "MINEWAYS", "JMC2OBJ", "ICE_CUBE", "GENERIC".
        biome: Biome preset name (e.g. "PLAINS", "BADLANDS", "DESERT").
        prefs: Add-on preferences reference.
        force_remap: Re-map atlas UVs from local UVs even when the layout matches.
        reconcile_animation: Override animation routing reconciliation. Defaults
            to comparing the stored routing marker with the current preference.

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
    base_cache, atlas_dir, manifest_fingerprint = load_material_cache_context(prefs)

    atlas_data, baked_atlas = _load_atlas_data_and_baked_atlas(atlas_dir, prefs)
    anim_enabled = animated_textures_enabled(prefs)
    num_polys = len(mesh.polygons)
    current_layout_hash = compute_atlas_layout_hash(atlas_data)
    stored_layout_hash = get_stored_layout_hash(mesh)

    # Step 2: Reject meshes from the removed single-UV atlas pipeline and resolve
    # the preserved local UV map plus the atlas UV map.
    if _is_legacy_single_uv_atlas_mesh(mesh):
        return {
            "success": False,
            "message": (
                "Mesh uses the removed single-UV atlas layout. Re-import external imports "
                "to preserve their local UV map; MTK voxel meshes must use Rebuild Voxel Mesh."
            ),
        }

    local_uv_layer, atlas_uv_layer, atlas_created = resolve_uv_layers(
        mesh,
        create_atlas=True,
        activate=True,
    )
    if atlas_uv_layer is None:
        return {"success": False, "message": "Mesh has no UV map to store Atlas coordinates."}
    if local_uv_layer is None:
        return {
            "success": False,
            "message": (
                "Mesh has no preserved local UV map. Re-import external imports to enable "
                "lossless re-mapping; MTK voxel meshes must use Rebuild Voxel Mesh."
            ),
        }

    provenance_palette, provenance_indices = resolve_source_texture_keys_paletted(mesh)
    has_provenance = len(provenance_indices) == num_polys and len(provenance_palette) > 0
    same_layout = bool(stored_layout_hash) and stored_layout_hash == current_layout_hash

    # Fast path: keep the existing atlas UVs and only rebind materials.
    if (
        not force_remap
        and has_provenance
        and atlas_uv_layer is not None
        and not atlas_created
        and same_layout
    ):
        needs_reconcile = (
            _needs_animation_reconcile(mesh, prefs)
            if reconcile_animation is None
            else bool(reconcile_animation)
        )
        try:
            restored = restore_materials_from_provenance(
                mesh_or_obj,
                mode=mode,
                biome=biome,
                prefs=prefs,
                reconcile_animation=needs_reconcile,
                enable_animated_textures=anim_enabled,
                atlas_uv_layer=atlas_uv_layer,
                layout_hash=current_layout_hash,
                material_namespace="EXT",
            )
        except Exception as exc:
            logger.warning("Atlas UV reuse raised %s; re-mapping from local UVs.", exc)
            restored = {"success": False, "message": str(exc)}
        if restored.get("success"):
            set_stored_layout_hash(mesh, current_layout_hash)
            # Normalize the restore summary to the replace_materials contract.
            restored["face_count"] = num_polys
            restored["materials_count"] = len(mesh.materials)
            restored["unmapped_faces"] = 0
            restored["mode"] = mode_upper
            restored["reused_atlas_uvs"] = True
            restored["atlas_uv_layer"] = getattr(atlas_uv_layer, "name", "")
            restored["local_uv_layer"] = getattr(local_uv_layer, "name", "")
            return restored

        logger.warning(
            "Atlas UV reuse failed (%s); re-mapping from local UVs.",
            restored.get("message"),
        )

    # Step 3: Extract face materials & local UVs as palette + indices
    (
        face_material_palette,
        face_material_indices,
        face_loop_ranges,
        loop_uvs,
        _local_uv_layer,
        existing_key_palette,
        existing_key_indices,
    ) = extract_face_material_palette_context(mesh, uv_layer=local_uv_layer)

    # Step 4: Palette-native Rust multi-UV remapping + source-key provenance
    remap = remap_face_materials_and_uvs_paletted(
        baked_atlas=baked_atlas,
        face_material_palette=face_material_palette,
        face_material_indices=face_material_indices,
        loop_uvs=loop_uvs,
        face_loop_ranges=face_loop_ranges,
        origin=origin,
        existing_key_palette=existing_key_palette,
        existing_key_indices=existing_key_indices,
        enable_animated_textures=anim_enabled,
    )

    # Step 5: Construct and assign materials into the atlas UV map
    layout_changed = bool(stored_layout_hash) and stored_layout_hash != current_layout_hash
    assign_atlas_chunk_materials(
        mesh=mesh,
        uv_layer=atlas_uv_layer,
        atlas_data=atlas_data,
        atlas_dir=atlas_dir,
        face_chunk_ids=remap["face_chunk_ids"],
        atlas_uvs=remap["atlas_uvs"],
        manifest_fingerprint=manifest_fingerprint,
        force_rebuild_materials=layout_changed,
        material_namespace="EXT",
    )
    set_stored_layout_hash(mesh, current_layout_hash)

    # Step 6: Inject mesh provenance attributes (palette + zero-copy buffers)
    inject_mesh_provenance_attributes(
        mesh=mesh,
        face_source_key_palette=remap["source_key_palette"],
        face_source_key_indices=remap["face_source_key_indices"],
        face_chunk_ids=remap["face_chunk_ids"],
        face_uv_transforms=remap["face_uv_transforms"],
        face_uv_rotations=remap.get("face_uv_rotations"),
        face_anim_timing=remap.get("face_anim_timing"),
        face_anim_frame_size=remap.get("face_anim_frame_size"),
    )

    # Step 7: Compute & apply biome tint attributes through the palette-native
    # path. No per-face Python strings are materialized for uniform presets.
    resolve_and_apply_biome_tint(
        mesh_or_obj,
        mesh,
        None,
        biome,
        base_cache,
        prefs,
        source_key_palette=remap["source_key_palette"],
        source_key_indices=np.frombuffer(
            remap["face_source_key_indices"], dtype=np.uint32
        ),
    )

    if hasattr(mesh, "__setitem__"):
        try:
            mesh["mtk_enable_animated_textures"] = bool(anim_enabled)
        except Exception:
            pass

    mesh.update()
    prune_optional_mesh_attributes(
        mesh,
        keep_animation=mesh_has_animation(mesh),
        keep_block_coords=not _is_external_object(mesh_or_obj),
    )
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
        "reused_atlas_uvs": False,
        "local_uv_layer": getattr(local_uv_layer, "name", ""),
        "atlas_uv_layer": getattr(atlas_uv_layer, "name", ""),
    }


def restore_materials_from_provenance(
    mesh_or_obj: Any,
    mode: str = "ATLAS",
    biome: Optional[str] = None,
    prefs: Optional[Any] = None,
    reconcile_animation: bool = False,
    enable_animated_textures: Optional[bool] = None,
    atlas_uv_layer: Optional[Any] = None,
    layout_hash: Optional[str] = None,
    material_namespace: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Reconstructs Blender material slots, nodes, and assignments purely from mesh face provenance attributes.

    This is the same-layout fast path used by :func:`replace_materials`; it requires
    an existing ``MTK_Atlas`` UV map and never re-maps UVs from local coordinates.

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
        atlas_uv_layer: Optional pre-resolved Atlas UV layer. Resolved automatically
            when omitted.
        layout_hash: Optional precomputed atlas layout hash. Computed from the active
            cache when omitted.
        material_namespace: Optional material-name namespace. ``"EXT"`` selects the
            external ``MTK:Atlas:Ext:*`` materials; resolved from mesh ownership
            when omitted.
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
    face_source_palette, face_source_indices = resolve_source_texture_keys_paletted(mesh)
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
    base_cache, atlas_dir, manifest_fingerprint = load_material_cache_context(prefs)
    atlas_data, baked_atlas = _load_atlas_data_and_baked_atlas(atlas_dir, prefs)

    current_layout_hash = layout_hash or compute_atlas_layout_hash(atlas_data)
    stored_layout_hash = get_stored_layout_hash(mesh)
    if stored_layout_hash and current_layout_hash and stored_layout_hash != current_layout_hash:
        return {
            "success": False,
            "message": (
                "Atlas layout changed since the last replacement. Re-run Replace Material "
                "to re-map atlas UVs from the preserved local UV map."
            ),
        }

    if not hasattr(mesh, "uv_layers") or len(mesh.uv_layers) == 0:
        return {"success": False, "message": "Mesh has no UV map to restore Atlas coordinates into."}

    _local_uv_layer, resolved_atlas_uv, _ = resolve_uv_layers(
        mesh, create_atlas=False, activate=True
    )
    if atlas_uv_layer is None:
        atlas_uv_layer = resolved_atlas_uv
    if atlas_uv_layer is None:
        return {
            "success": False,
            "message": "Mesh has no MTK_Atlas UV map. Run Replace Material to create it.",
        }

    if material_namespace is None and _is_external_object(mesh_or_obj):
        material_namespace = "EXT"

    chunk_attr = mesh.attributes.get("mtk_atlas_chunk_id") if hasattr(mesh, "attributes") else None
    if chunk_attr is not None and len(chunk_attr.data) == num_polys:
        if hasattr(chunk_attr.data, "foreach_get"):
            chunk_ids_np = np.empty(num_polys, dtype=np.int32)
            chunk_attr.data.foreach_get("value", chunk_ids_np)
            face_chunk_ids = [int(x) for x in chunk_ids_np]
        else:
            face_chunk_ids = [int(elem.value) for elem in chunk_attr.data]
    else:
        # No chunk attribute: derive routing from the preserved source keys.
        if baked_atlas is None:
            return {
                "success": False,
                "message": "Atlas data is required to reconstruct missing mtk_atlas_chunk_id.",
            }
        routes = resolve_mesh_material_routes(
            face_source_keys,
            baked_atlas,
            enable_animated_textures=anim_enabled,
        )
        face_chunk_ids = [int(cid) for cid in routes["chunk_ids"]]
        unmapped = int(routes.get("unmapped_faces", 0))
        if unmapped:
            logger.warning(
                "Restore resolved %d/%d chunk routes from provenance; %d faces are unmapped",
                num_polys - unmapped,
                num_polys,
                unmapped,
            )

    atlas_uvs: Optional[List[float]] = None
    face_anim_timing: Optional[List[List[float]]] = None
    face_anim_frame_size: Optional[List[List[float]]] = None
    animation_reconciled = False

    if reconcile_animation and atlas_uv_layer is not None:
        # Existing UVs are Atlas UVs, so decode them from the previous sprite and
        # re-project them into the new static/animated sprite in Rust.
        num_loops = len(mesh.loops)
        loop_uvs = read_uv_layer(atlas_uv_layer, num_loops)

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
        atlas_uvs = reroute["atlas_uvs"]
        face_anim_timing = reroute.get("face_anim_timing")
        face_anim_frame_size = reroute.get("face_anim_frame_size")
        animation_reconciled = True

    # Step 2: Reconstruct material slots (optionally reusing re-projected atlas UVs)
    assign_atlas_chunk_materials(
        mesh=mesh,
        uv_layer=atlas_uv_layer,
        atlas_data=atlas_data,
        atlas_dir=atlas_dir,
        face_chunk_ids=face_chunk_ids,
        atlas_uvs=atlas_uvs,
        manifest_fingerprint=manifest_fingerprint,
        material_namespace=material_namespace,
    )

    # Step 3: Sync material slot / animation attributes (delegated to bridge/mesh.py)
    inject_mesh_provenance_attributes(
        mesh=mesh,
        face_source_keys=face_source_keys,
        face_source_key_palette=face_source_palette or None,
        face_source_key_indices=face_source_indices if len(face_source_indices) == num_polys else None,
        face_chunk_ids=face_chunk_ids,
        face_anim_timing=face_anim_timing,
        face_anim_frame_size=face_anim_frame_size,
    )

    if animation_reconciled and hasattr(mesh, "__setitem__"):
        try:
            mesh["mtk_enable_animated_textures"] = bool(anim_enabled)
        except Exception:
            pass

    # Step 4: Re-apply biome tint attributes
    resolve_and_apply_biome_tint(mesh_or_obj, mesh, face_source_keys, effective_biome, base_cache, prefs)

    set_stored_layout_hash(mesh, current_layout_hash)
    mesh.update()
    prune_optional_mesh_attributes(
        mesh,
        keep_animation=mesh_has_animation(mesh),
        keep_block_coords=not _is_external_object(mesh_or_obj),
    )
    animated_faces = sum(1 for flag in (face_anim_timing or []) if flag and flag[0] > 1.0)
    return {
        "success": True,
        "restored_faces": num_polys,
        "biome": effective_biome,
        "materials_count": len(mesh.materials),
        "animated_faces": animated_faces,
        "animation_reconciled": animation_reconciled,
        "enable_animated_textures": bool(anim_enabled),
        "atlas_uv_layer": getattr(atlas_uv_layer, "name", ""),
    }


# Backwards compatibility aliases
_inject_face_attribute_string = inject_face_attribute_string
_inject_face_attribute_int = inject_face_attribute_int
_inject_face_attribute_float = inject_face_attribute_float
_inject_face_attribute_float4 = inject_face_attribute_float4
