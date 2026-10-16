"""
Instant Biome Updater for Atlas and Standalone Material Modes.
Updates mesh face attributes or material shader nodes in < 1ms without rerunning the texture replacement pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Any
import bpy

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

from ..constants import (
    ATTR_ATLAS_CHUNK_ID,
    ATTR_ATLAS_TEXTURE_ID,
    ATTR_BIOME_TINT_DATA,
    ATTR_BIOME_TINT_COLOR,
    ATTR_COLORMAP_UV,
    ATTR_SOURCE_TEXTURE_KEY,
    ATTR_SOURCE_TEXTURE_IDX,
    PROP_CREATED_BY,
    PROP_ATLAS_MAPPING,
    PROP_PACK_HASH,
)
from .biome import (
    get_biome_colors,
    BiomeResolver,
    TINT_TYPE_NONE,
    TINT_TYPE_GRASS,
    TINT_TYPE_FOLIAGE,
    TINT_TYPE_WATER,
    TINT_TYPE_HARDCODED,
    TINT_TYPE_DRY_FOLIAGE,
    get_hardcoded_tint,
)

# In-memory cache for original face tint types (to prevent RNA allocation overhead and preserve base categories)
_MESH_BASE_TINT_TYPES: dict[str, Any] = {}

# In-memory storage registry to avoid serializing unpicklable native VoxelStorage into bpy properties
_STORAGE_CACHE: dict[str, Any] = {}


def clear_biome_updater_cache() -> None:
    """Clear in-memory caches for mesh tint types and voxel storage registry."""
    _MESH_BASE_TINT_TYPES.clear()
    _STORAGE_CACHE.clear()


def register_object_storage(key: str, storage: Any) -> None:
    """Register native VoxelStorage in memory for a given container UUID or object name."""
    if key and storage is not None:
        _STORAGE_CACHE[str(key)] = storage


def get_object_storage(key: str) -> Any:
    """Retrieve native VoxelStorage from memory cache."""
    if not key:
        return None
    return _STORAGE_CACHE.get(str(key))


def resolve_mesh_base_tint_types(
    mesh: Any,
    obj: Optional[Any] = None,
    raw_tint_data_2d: Optional[Any] = None,
    pack_stack: Optional[Any] = None,
) -> Any:
    """
    Resolve intrinsic material base tint types (0=None, 1=Grass, 2=Foliage, 3=Water, 4=Hardcoded, 5=Dry Foliage)
    for each face of the mesh, decoupling intrinsic material identity from biome-level hardcoded overrides.

    Prevents faces from being permanently trapped in TINT_TYPE_HARDCODED (4.0) after imports from biomes
    with custom colors (such as dark_forest or badlands).
    """
    if not HAS_NUMPY or mesh is None:
        return np.empty(0, dtype=np.int32) if HAS_NUMPY else []

    num_polys = len(mesh.polygons) if hasattr(mesh, "polygons") else 0
    if num_polys == 0:
        return np.empty(0, dtype=np.int32)

    mesh_name = getattr(mesh, "name", "")
    cached = _MESH_BASE_TINT_TYPES.get(mesh_name)
    if cached is not None and len(cached) == num_polys:
        return cached

    from .biome import get_or_load_biome_resolver, read_face_string_attribute
    resolver = get_or_load_biome_resolver(pack_stack=pack_stack)

    # Strategy A: Sub-millisecond INT Palette Indexing ('mtk_source_textures' + 'mtk_source_texture_idx')
    palette = None
    if hasattr(mesh, "get") and mesh.get("mtk_source_textures") is not None:
        palette = list(mesh.get("mtk_source_textures"))
    elif hasattr(mesh, "__contains__") and "mtk_source_textures" in mesh:
        palette = list(mesh["mtk_source_textures"])
    elif hasattr(mesh, "keys") and "mtk_source_textures" in mesh:
        palette = list(mesh["mtk_source_textures"])
    elif obj is not None and hasattr(obj, "get") and "mtk_source_textures" in obj:
        palette = list(obj["mtk_source_textures"])

    attr_idx = mesh.attributes.get(ATTR_SOURCE_TEXTURE_IDX) if hasattr(mesh, "attributes") else None
    if palette is not None and attr_idx is not None and len(attr_idx.data) == num_polys:
        if hasattr(attr_idx.data, "foreach_get"):
            pal_tt = np.array([
                resolver.get_tint_info(tex).get("tint_type", 0) if hasattr(resolver, "get_tint_info") else 0
                for tex in palette
            ], dtype=np.int32)
            idx_arr = np.empty(num_polys, dtype=np.int32)
            attr_idx.data.foreach_get("value", idx_arr)
            valid_mask = (idx_arr >= 0) & (idx_arr < len(pal_tt))
            base_tt = np.zeros(num_polys, dtype=np.int32)
            base_tt[valid_mask] = pal_tt[idx_arr[valid_mask]]

            # Refinement with raw_tint_data_2d:
            # Faces that were untinted during meshing (e.g. dirt bottom/side of grass block) have raw_data == 0.0.
            if raw_tint_data_2d is not None and len(raw_tint_data_2d) == num_polys:
                raw_zero_mask = (raw_tint_data_2d[:, 3] == float(TINT_TYPE_NONE))
                base_tt[raw_zero_mask] = TINT_TYPE_NONE

            if np.any(base_tt > 0):
                if mesh_name:
                    _MESH_BASE_TINT_TYPES[mesh_name] = base_tt
                return base_tt

    # Strategy B: Legacy STRING attribute ('mtk_source_texture_key')
    attr_str = mesh.attributes.get(ATTR_SOURCE_TEXTURE_KEY) if hasattr(mesh, "attributes") else None
    if attr_str is not None and len(attr_str.data) == num_polys:
        keys = read_face_string_attribute(mesh, ATTR_SOURCE_TEXTURE_KEY)
        if any(keys):
            unique_keys = set(keys)
            key_to_tt = {
                k: (resolver.get_tint_info(k).get("tint_type", 0) if hasattr(resolver, "get_tint_info") else 0)
                for k in unique_keys
            }
            base_tt = np.fromiter((key_to_tt.get(k, 0) for k in keys), dtype=np.int32, count=num_polys)
            if raw_tint_data_2d is not None and len(raw_tint_data_2d) == num_polys:
                raw_zero_mask = (raw_tint_data_2d[:, 3] == float(TINT_TYPE_NONE))
                base_tt[raw_zero_mask] = TINT_TYPE_NONE

            if np.any(base_tt > 0):
                if mesh_name:
                    _MESH_BASE_TINT_TYPES[mesh_name] = base_tt
                return base_tt

    # Strategy C: Material slots on object
    if obj is not None and len(getattr(obj, "material_slots", [])) > 0:
        slot_tt = []
        for slot in obj.material_slots:
            mat = slot.material
            if mat:
                key = str(mat.get("mtk_source_texture_key") or mat.get("mtk:material_id") or mat.name)
                tt = resolver.get_tint_info(key).get("tint_type", 0) if hasattr(resolver, "get_tint_info") else 0
            else:
                tt = 0
            slot_tt.append(tt)

        slot_tt_arr = np.array(slot_tt, dtype=np.int32)
        poly_mat_indices = np.empty(num_polys, dtype=np.int32)
        mesh.polygons.foreach_get("material_index", poly_mat_indices)
        valid_mask = (poly_mat_indices >= 0) & (poly_mat_indices < len(slot_tt_arr))
        base_tt = np.zeros(num_polys, dtype=np.int32)
        base_tt[valid_mask] = slot_tt_arr[poly_mat_indices[valid_mask]]
        if raw_tint_data_2d is not None and len(raw_tint_data_2d) == num_polys:
            raw_zero_mask = (raw_tint_data_2d[:, 3] == float(TINT_TYPE_NONE))
            base_tt[raw_zero_mask] = TINT_TYPE_NONE

        if np.any(base_tt > 0):
            if mesh_name:
                _MESH_BASE_TINT_TYPES[mesh_name] = base_tt
            return base_tt

    # Strategy D: Fallback to raw_tint_data_2d
    if raw_tint_data_2d is not None and len(raw_tint_data_2d) == num_polys:
        base_tt = np.round(raw_tint_data_2d[:, 3]).astype(np.int32)
        if mesh_name:
            _MESH_BASE_TINT_TYPES[mesh_name] = base_tt
        return base_tt

    base_tt = np.zeros(num_polys, dtype=np.int32)
    if mesh_name:
        _MESH_BASE_TINT_TYPES[mesh_name] = base_tt
    return base_tt



def is_mtk_object(obj: Optional[bpy.types.Object]) -> bool:
    """Check if the given object has MoziToolKit materials or face metadata."""
    if not obj or obj.type != "MESH" or not obj.data:
        return False
    if obj.get("mtk:provenance_schema_version") is not None or obj.get("mtk:biome_preset") is not None:
        return True
    mesh = obj.data
    attrs = mesh.attributes
    if any(name in attrs for name in (ATTR_SOURCE_TEXTURE_KEY, ATTR_SOURCE_TEXTURE_IDX, ATTR_BIOME_TINT_DATA, ATTR_BIOME_TINT_COLOR, ATTR_ATLAS_CHUNK_ID, ATTR_COLORMAP_UV)):
        return True
    for slot in obj.material_slots:
        mat = slot.material
        if mat:
            name_lower = mat.name.lower()
            if (
                name_lower.startswith(("mtk:", "mtk_", "mc_atlas"))
                or mat.get("mozi_created_by")
                or mat.get("mtk_material_mode")
                or PROP_ATLAS_MAPPING in mat
            ):
                return True
    return False


def detect_object_material_mode(obj: bpy.types.Object) -> str:
    """Determine whether an object is currently configured in Atlas mode."""
    if not obj or obj.type != "MESH" or not obj.data:
        return "UNKNOWN"
    return "ATLAS"

def resolve_and_apply_world_biome_tint(
    mesh_or_obj: Any,
    mesh: Optional[Any] = None,
    face_source_keys: Optional[List[str]] = None,
    effective_stack: Optional[Any] = None,
    prefs: Optional[Any] = None,
    base_cache: Optional[Path] = None,
) -> bool:
    """
    Resolve 3D World Biome tinting attributes from an associated VoxelStorage container
    and apply packed tint data, colors, and colormap UVs to the mesh.
    Returns True if world biome attributes were successfully computed or verified.
    """
    if mesh_or_obj is None and mesh is None:
        return False

    is_obj = hasattr(mesh_or_obj, "type") and getattr(mesh_or_obj, "type", "") == "MESH"
    obj = mesh_or_obj if is_obj else None
    target_mesh = mesh if mesh is not None else (getattr(mesh_or_obj, "data", mesh_or_obj) if is_obj else mesh_or_obj)

    if not hasattr(target_mesh, "polygons"):
        return False

    from .biome import (
        apply_biome_tint_attributes,
        read_face_string_attribute,
        get_or_load_biome_resolver,
    )

    storage = getattr(mesh_or_obj, "_storage", None) or getattr(target_mesh, "_storage", None)
    if storage is None and hasattr(mesh_or_obj, "name"):
        storage = get_object_storage(mesh_or_obj.name)
    if storage is None and hasattr(target_mesh, "name"):
        storage = get_object_storage(target_mesh.name)
    if storage is None and hasattr(mesh_or_obj, "get"):
        save_uuid = mesh_or_obj.get("mozi_save_uuid") or mesh_or_obj.get("mtk:container_id")
        if save_uuid:
            storage = get_object_storage(save_uuid)
    if storage is None and hasattr(target_mesh, "get"):
        save_uuid = target_mesh.get("mozi_save_uuid") or target_mesh.get("mtk:container_id")
        if save_uuid:
            storage = get_object_storage(save_uuid)
    if storage is None and hasattr(mesh_or_obj, "get"):
        storage = mesh_or_obj.get("mtk:storage", None)
    if storage is None and hasattr(target_mesh, "get"):
        storage = target_mesh.get("mtk:storage", None)
    if storage is None:
        try:
            try:
                from ....bridge.sync import get_live_sync_session
            except (ImportError, ValueError):
                from bridge.sync import get_live_sync_session
            session = get_live_sync_session()
            if session:
                storage = session.get_storage()
        except Exception:
            storage = None

    source_keys = list(face_source_keys) if face_source_keys else []
    if not any(source_keys) and hasattr(target_mesh, "attributes"):
        if ATTR_SOURCE_TEXTURE_KEY in target_mesh.attributes or ATTR_SOURCE_TEXTURE_IDX in target_mesh.attributes:
            source_keys = read_face_string_attribute(target_mesh, ATTR_SOURCE_TEXTURE_KEY)

    if not any(source_keys) and obj and len(getattr(obj, "material_slots", [])) > 0:
        for poly in target_mesh.polygons:
            m_idx = poly.material_index
            mat = obj.material_slots[m_idx].material if m_idx < len(obj.material_slots) else None
            key = (mat.get("mtk_source_texture_key") or mat.get("mtk:material_id") or (mat.name if mat else "")) if mat else ""
            source_keys.append(str(key))

    has_coords = (
        hasattr(target_mesh, "attributes")
        and "mtk_block_x" in target_mesh.attributes
        and "mtk_block_y" in target_mesh.attributes
        and "mtk_block_z" in target_mesh.attributes
    )

    if storage is not None and has_coords and any(source_keys):
        try:
            from ....bridge.material import compute_mesh_biome_attributes_from_storage
        except (ImportError, ValueError):
            from bridge.material import compute_mesh_biome_attributes_from_storage

        biome_resolver = get_or_load_biome_resolver(cache_dir=base_cache, prefs=prefs, pack_stack=effective_stack)
        num_polys = len(target_mesh.polygons)
        attr_x = target_mesh.attributes.get("mtk_block_x")
        attr_y = target_mesh.attributes.get("mtk_block_y")
        attr_z = target_mesh.attributes.get("mtk_block_z")

        if HAS_NUMPY and hasattr(attr_x.data, "foreach_get"):
            xs = np.empty(num_polys, dtype=np.int32)
            ys = np.empty(num_polys, dtype=np.int32)
            zs = np.empty(num_polys, dtype=np.int32)
            attr_x.data.foreach_get("value", xs)
            attr_y.data.foreach_get("value", ys)
            attr_z.data.foreach_get("value", zs)
            coords_x, coords_y, coords_z = xs, ys, zs
        else:
            coords_x = [int(p.value) for p in attr_x.data]
            coords_y = [int(p.value) for p in attr_y.data]
            coords_z = [int(p.value) for p in attr_z.data]

        res = compute_mesh_biome_attributes_from_storage(
            source_keys,
            coords_x,
            coords_y,
            coords_z,
            storage,
            resolver=biome_resolver,
            smooth=True,
        )
        apply_biome_tint_attributes(target_mesh, res["packed_tint_data"], res["tint_colors"], res["colormap_uvs"])
        if hasattr(mesh_or_obj, "__setitem__"):
            try:
                mesh_or_obj["mtk:biome_preset"] = "WORLD"
            except Exception:
                pass
        if hasattr(target_mesh, "update"):
            target_mesh.update()
        return True

    if hasattr(target_mesh, "attributes") and ATTR_BIOME_TINT_DATA in target_mesh.attributes:
        if hasattr(mesh_or_obj, "__setitem__"):
            try:
                mesh_or_obj["mtk:biome_preset"] = "WORLD"
            except Exception:
                pass
        if hasattr(target_mesh, "update"):
            target_mesh.update()
        return True

    return False


def update_object_biome(
    obj: bpy.types.Object,
    biome_name: str,
    pack_stack: Any = None,
) -> bool:
    """
    Instantly update an object's biome colors and colormap UVs without rerunning the texture replacement pipeline.
    Supports both Atlas mode (mesh face attributes) and Standalone mode (material shader node trees).
    """
    if not is_mtk_object(obj):
        return False

    mesh = obj.data
    mode = detect_object_material_mode(obj)

    # Read custom biome parameters if configured on the object
    is_custom = biome_name.upper() == "CUSTOM"
    if is_custom:
        custom_temp = float(getattr(obj, "mtk_biome_temp", obj.get("mtk_biome_temp", 0.8) if hasattr(obj, "get") else 0.8))
        custom_humidity = float(getattr(obj, "mtk_biome_humidity", obj.get("mtk_biome_humidity", 0.4) if hasattr(obj, "get") else 0.4))
        has_custom_grass = bool(getattr(obj, "mtk_biome_use_custom_grass", obj.get("mtk_biome_use_custom_grass", False) if hasattr(obj, "get") else False))
        has_custom_foliage = bool(getattr(obj, "mtk_biome_use_custom_foliage", obj.get("mtk_biome_use_custom_foliage", False) if hasattr(obj, "get") else False))
        has_custom_dry_foliage = bool(getattr(obj, "mtk_biome_use_custom_dry_foliage", obj.get("mtk_biome_use_custom_dry_foliage", False) if hasattr(obj, "get") else False))
        custom_grass = list(getattr(obj, "mtk_biome_grass_color", obj.get("mtk_biome_grass_color", (0.28, 0.51, 0.10, 1.0)) if hasattr(obj, "get") else (0.28, 0.51, 0.10, 1.0)))
        custom_foliage = list(getattr(obj, "mtk_biome_foliage_color", obj.get("mtk_biome_foliage_color", (0.18, 0.41, 0.03, 1.0)) if hasattr(obj, "get") else (0.18, 0.41, 0.03, 1.0)))
        custom_dry_foliage = list(getattr(obj, "mtk_biome_dry_foliage_color", obj.get("mtk_biome_dry_foliage_color", (0.37, 0.18, 0.06, 1.0)) if hasattr(obj, "get") else (0.37, 0.18, 0.06, 1.0)))
        custom_water = list(getattr(obj, "mtk_biome_water_color", obj.get("mtk_biome_water_color", (0.05, 0.18, 0.78, 1.0)) if hasattr(obj, "get") else (0.05, 0.18, 0.78, 1.0)))
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

    biome_colors = get_biome_colors(
        biome_name,
        pack_stack=pack_stack,
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
    if not is_custom:
        has_custom_grass = bool(biome_colors.get("has_custom_grass", False))
        has_custom_foliage = bool(biome_colors.get("has_custom_foliage", False))
        has_custom_dry_foliage = bool(biome_colors.get("has_custom_dry_foliage", False))

    effective_stack = pack_stack
    if effective_stack is None:
        try:
            from bridge.assets import get_configured_pack_stack
            effective_stack = get_configured_pack_stack()
        except Exception:
            effective_stack = None

    # 1. Update mesh face attributes (Both ATLAS and STANDALONE modes use attribute drivers)
    num_polys = len(mesh.polygons) if hasattr(mesh, "polygons") else 0
    if num_polys > 0:
        from .biome import (
            compute_biome_tint_attributes,
            apply_biome_tint_attributes,
            read_face_string_attribute,
            get_or_load_biome_resolver,
        )

        if biome_name.upper() == "WORLD":
            source_keys = []
            if ATTR_SOURCE_TEXTURE_KEY in mesh.attributes or ATTR_SOURCE_TEXTURE_IDX in mesh.attributes:
                source_keys = read_face_string_attribute(mesh, ATTR_SOURCE_TEXTURE_KEY)
            if resolve_and_apply_world_biome_tint(
                mesh_or_obj=obj,
                mesh=mesh,
                face_source_keys=source_keys,
                effective_stack=effective_stack,
            ):
                return True

        # FAST IN-PLACE VECTORIZED UPDATE PATH (< 1.5ms):
        # When ATTR_BIOME_TINT_DATA is already present on the mesh, tint categories (grass/foliage/water/dry/hardcoded/none)
        # and blending weights are already baked. Uniform presets and custom slider drag only alter colors & colormap UVs.
        tint_data_attr = mesh.attributes.get(ATTR_BIOME_TINT_DATA)
        has_tint_data = tint_data_attr is not None and len(tint_data_attr.data) == num_polys
        fast_path_done = False

        if has_tint_data and HAS_NUMPY and hasattr(tint_data_attr.data, "foreach_get"):
            try:
                raw_data = np.empty(num_polys * 4, dtype=np.float32)
                tint_data_attr.data.foreach_get("color", raw_data)
                raw_data_2d = raw_data.reshape(num_polys, 4)

                # Maintain cached base tint type (original 0..5 categories decoupled from biome hardcoded overrides)
                base_tt = resolve_mesh_base_tint_types(mesh, obj, raw_data_2d, pack_stack=effective_stack)

                is_init = bool(mesh.get("mtk:biome_tint_initialized", False)) if hasattr(mesh, "get") else False
                if not np.any(base_tt > 0) and not is_init:
                    fast_path_done = False
                else:
                    grass_col = biome_colors.get("grass_linear", [0.28, 0.51, 0.10, 1.0])
                    foliage_col = biome_colors.get("foliage_linear", [0.18, 0.41, 0.03, 1.0])
                    water_col = biome_colors.get("water_linear", [0.05, 0.18, 0.78, 1.0])
                    dry_foliage_col = biome_colors.get("dry_foliage_linear", [0.37, 0.18, 0.06, 1.0])
                    cm_uv = biome_colors.get("colormap_uv", [0.2, 0.32])
                    base_uv_3 = [float(cm_uv[0]), float(cm_uv[1]), 0.0]

                    # Determine target tint type per face:
                    # When custom override is checked, route to HARDCODED (4.0).
                    # When unchecked, route to standard categories (1.0 for grass, 2.0 for foliage, etc.)
                    target_tt = base_tt.astype(np.float32).copy()
                    if has_custom_grass:
                        target_tt[base_tt == TINT_TYPE_GRASS] = float(TINT_TYPE_HARDCODED)
                    if has_custom_foliage:
                        target_tt[base_tt == TINT_TYPE_FOLIAGE] = float(TINT_TYPE_HARDCODED)
                    if has_custom_dry_foliage:
                        target_tt[base_tt == TINT_TYPE_DRY_FOLIAGE] = float(TINT_TYPE_HARDCODED)

                    # 1. Update ATTR_BIOME_TINT_DATA only if tint types actually changed
                    if not np.array_equal(raw_data_2d[:, 3], target_tt):
                        raw_data_2d[:, 3] = target_tt
                        tint_data_attr.data.foreach_set("color", raw_data_2d.ravel())

                    # 2. Update ATTR_BIOME_TINT_COLOR
                    attr_col = mesh.attributes.get(ATTR_BIOME_TINT_COLOR)
                    if attr_col and len(attr_col.data) == num_polys and hasattr(attr_col.data, "foreach_set"):
                        new_tint_colors = np.ones((num_polys, 4), dtype=np.float32)
                        new_tint_colors[base_tt == TINT_TYPE_GRASS] = grass_col
                        new_tint_colors[base_tt == TINT_TYPE_FOLIAGE] = foliage_col
                        new_tint_colors[base_tt == TINT_TYPE_WATER] = water_col
                        new_tint_colors[base_tt == TINT_TYPE_DRY_FOLIAGE] = dry_foliage_col

                        if hasattr(attr_col.data, "foreach_get"):
                            old_cols_arr = np.empty(num_polys * 4, dtype=np.float32)
                            attr_col.data.foreach_get("color", old_cols_arr)
                            old_cols_2d = old_cols_arr.reshape(num_polys, 4)
                            hc_mask = (base_tt == TINT_TYPE_HARDCODED)
                            if np.any(hc_mask):
                                new_tint_colors[hc_mask] = old_cols_2d[hc_mask]

                        attr_col.data.foreach_set("color", new_tint_colors.ravel())

                    # 3. Update ATTR_COLORMAP_UV (temperature/downfall)
                    attr_uv = mesh.attributes.get(ATTR_COLORMAP_UV)
                    if attr_uv and len(attr_uv.data) == num_polys and hasattr(attr_uv.data, "foreach_set"):
                        new_cm_uvs = np.empty((num_polys, 3), dtype=np.float32)
                        new_cm_uvs[:] = base_uv_3
                        attr_uv.data.foreach_set("vector", new_cm_uvs.ravel())

                    if hasattr(mesh, "__setitem__"):
                        try:
                            mesh["mtk:biome_tint_initialized"] = True
                        except Exception:
                            pass
                    fast_path_done = True
            except Exception:
                fast_path_done = False

        if not fast_path_done:
            # Fallback path: compute full biome tint attributes from source keys or materials
            source_keys = []
            if ATTR_SOURCE_TEXTURE_KEY in mesh.attributes or ATTR_SOURCE_TEXTURE_IDX in mesh.attributes:
                source_keys = read_face_string_attribute(mesh, ATTR_SOURCE_TEXTURE_KEY)

            if any(source_keys):
                biome_resolver = get_or_load_biome_resolver(pack_stack=effective_stack)
                packed_tint_data, tint_colors, colormap_uvs = compute_biome_tint_attributes(
                    source_keys,
                    biome_preset=biome_name,
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
                if hasattr(mesh, "__setitem__"):
                    try:
                        mesh["mtk:biome_tint_initialized"] = True
                    except Exception:
                        pass
            elif len(obj.material_slots) > 0:
                derived_keys = []
                for poly in mesh.polygons:
                    m_idx = poly.material_index
                    mat = obj.material_slots[m_idx].material if m_idx < len(obj.material_slots) else None
                    key = (mat.get("mtk_source_texture_key") or mat.get("mtk:material_id") or (mat.name if mat else "")) if mat else ""
                    derived_keys.append(str(key))

                if any(derived_keys):
                    try:
                        from bridge.mesh import inject_face_attribute_string
                        inject_face_attribute_string(mesh, ATTR_SOURCE_TEXTURE_KEY, derived_keys)
                    except Exception:
                        pass
                    biome_resolver = get_or_load_biome_resolver(pack_stack=effective_stack)
                    packed_tint_data, tint_colors, colormap_uvs = compute_biome_tint_attributes(
                        derived_keys,
                        biome_preset=biome_name,
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
                    if hasattr(mesh, "__setitem__"):
                        try:
                            mesh["mtk:biome_tint_initialized"] = True
                        except Exception:
                            pass

    obj["mtk:biome_preset"] = biome_name
    return True
