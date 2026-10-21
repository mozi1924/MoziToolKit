"""
Instant Biome Updater for Atlas and Standalone Material Modes.
Updates mesh face attributes or material shader nodes in < 1ms without rerunning the texture replacement pipeline.
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger("MoziToolKit.Materials.Biome.Updater")

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


def mark_world_biome(obj: Any, storage: Any = None, aliases: Any = ()) -> bool:
    """
    Tag an MTK voxel mesh as using true 3D World Biome tinting and cache its storage.

    Every voxel-derived surface mesh (save import, Live Sync, rebuild) bakes real 3D
    biome colors into its tint attributes. Tagging ``mtk:biome_preset`` here keeps the
    biome panel from falling back to the uniform ``PLAINS`` default, while registering
    the storage lets a later WORLD re-selection recompute colors without a live session.

    ``aliases`` may contain extra lookup keys (root container name, container UUID)
    that should resolve to the same storage.
    """
    if obj is None:
        return False

    try:
        obj["mtk:biome_preset"] = "WORLD"
    except (TypeError, AttributeError, KeyError):
        try:
            setattr(obj, "mtk:biome_preset", "WORLD")
        except Exception:
            pass

    if storage is not None:
        mesh = getattr(obj, "data", None)
        for key in (getattr(obj, "name", ""), getattr(mesh, "name", "")):
            if isinstance(key, str) and key:
                register_object_storage(key, storage)
        for key in aliases:
            if isinstance(key, str) and key:
                register_object_storage(key, storage)

    return True


def _rehydrate_storage_from_point_cloud(obj: Any, target_mesh: Any = None) -> Any:
    """
    Rebuild a VoxelStorage from the companion point cloud persisted in the .blend.

    This is the offline fallback for save imports and disconnected Live Sync
    containers: the point cloud keeps per-voxel block states and 3D biomes, so a
    later WORLD selection can restore the exact tint instead of refusing or
    repainting with the uniform Plains fallback.
    """
    if obj is None:
        return None

    try:
        from ....bridge.point_cloud import extract_voxel_point_cloud
        from ....utils.point_cloud import get_associated_voxel_cloud
        from ....bridge.point_cloud.constants import ATTR_BIOME, ATTR_BIOME_IDX, PROP_BIOME_PALETTE
    except (ImportError, ValueError):
        try:
            from bridge.point_cloud import extract_voxel_point_cloud
            from utils.point_cloud import get_associated_voxel_cloud
            from bridge.point_cloud.constants import ATTR_BIOME, ATTR_BIOME_IDX, PROP_BIOME_PALETTE
        except Exception:
            return None

    try:
        cloud = get_associated_voxel_cloud(obj)
        if cloud is None:
            return None

        cloud_mesh = getattr(cloud, "data", None)
        attrs = getattr(cloud_mesh, "attributes", None)
        if attrs is None:
            return None
        has_biomes = ATTR_BIOME in attrs
        if not has_biomes and ATTR_BIOME_IDX in attrs:
            has_biomes = hasattr(cloud, "__contains__") and PROP_BIOME_PALETTE in cloud
        if not has_biomes:
            # Legacy point clouds without biome data would silently become Plains.
            return None

        cloud_data = extract_voxel_point_cloud(cloud)
        if cloud_data is None:
            return None
        storage = cloud_data.to_storage()
    except Exception:
        return None

    if storage is None:
        return None

    for target in (obj, cloud):
        name = getattr(target, "name", "")
        if isinstance(name, str) and name:
            register_object_storage(name, storage)
    if target_mesh is not None:
        name = getattr(target_mesh, "name", "")
        if isinstance(name, str) and name:
            register_object_storage(name, storage)
    if hasattr(obj, "get"):
        for prop in ("mtk:container_id", "mozi_save_uuid"):
            key = obj.get(prop)
            if isinstance(key, str) and key:
                register_object_storage(key, storage)

    return storage


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
    if not obj or obj.type != "MESH" or obj.data is None:
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
        # Fallback for a freshly opened file while a Live Sync session is still
        # running: the in-memory storage has not been registered under the object
        # names yet, but the active session owns the same 3D biomes.
        try:
            try:
                from ....bridge.sync import get_sync_bridge_session
            except (ImportError, ValueError):
                from bridge.sync import get_sync_bridge_session
            session = get_sync_bridge_session()
            if session is not None and getattr(session, "is_active", False):
                storage = session.get_storage()
        except Exception:
            storage = None
    if storage is None:
        # Offline fallback: the .blend-persisted companion point cloud carries
        # per-voxel 3D biomes for both save imports and disconnected sync worlds.
        storage = _rehydrate_storage_from_point_cloud(obj, target_mesh)

    source_keys = list(face_source_keys) if face_source_keys else []
    if not any(source_keys) and hasattr(target_mesh, "attributes"):
        if ATTR_SOURCE_TEXTURE_KEY in target_mesh.attributes or ATTR_SOURCE_TEXTURE_IDX in target_mesh.attributes:
            source_keys = read_face_string_attribute(target_mesh, ATTR_SOURCE_TEXTURE_KEY)

    if not any(source_keys) and obj and len(getattr(obj, "material_slots", [])) > 0:
        derived = []
        for poly in target_mesh.polygons:
            m_idx = poly.material_index
            mat = obj.material_slots[m_idx].material if m_idx < len(obj.material_slots) else None
            key = (mat.get("mtk_source_texture_key") or mat.get("mtk:material_id") or "") if mat else ""
            derived.append(str(key))
        # Atlas chunk materials carry no source key. Falling back to their names
        # would classify every face as "none" and permanently zero the tint types.
        if derived and all(derived):
            source_keys = derived

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
        # Existing tint attributes are only trustworthy as 3D world data when no
        # uniform preset has overwritten them. Without storage we cannot restore
        # real biome colors, so refuse instead of silently relabeling Plains.
        current_preset = None
        if hasattr(mesh_or_obj, "get"):
            current_preset = mesh_or_obj.get("mtk:biome_preset")
        if isinstance(current_preset, str) and current_preset and current_preset.upper() != "WORLD":
            return False
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
            from ....bridge.assets import get_configured_pack_stack
            effective_stack = get_configured_pack_stack()
        except (ImportError, ValueError):
            try:
                from MoziToolKit.bridge.assets import get_configured_pack_stack
                effective_stack = get_configured_pack_stack()
            except (ImportError, ValueError):
                try:
                    from bridge.assets import get_configured_pack_stack
                    effective_stack = get_configured_pack_stack()
                except Exception:
                    effective_stack = None
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

            # A uniform "WORLD" preset has no colormap entry and resolves to Plains
            # in Rust. Refuse instead of silently repainting 3D-biome faces as Plains.
            logger.warning(
                "Cannot restore WORLD biome for '%s': no voxel storage or source-texture "
                "provenance. Rebuild the voxel mesh from its point cloud/storage.",
                getattr(obj, "name", "<unnamed>"),
            )
            return False

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

                # Maintain cached base tint type (original 0..5 categories decoupled from biome hardcoded overrides)
                base_tt = resolve_mesh_base_tint_types(
                    mesh, obj, raw_data.reshape(num_polys, 4), pack_stack=effective_stack
                )

                is_init = bool(mesh.get("mtk:biome_tint_initialized", False)) if hasattr(mesh, "get") else False
                if not np.any(base_tt > 0) and not is_init:
                    fast_path_done = False
                else:
                    grass_col = biome_colors.get("grass_linear", [0.28, 0.51, 0.10, 1.0])
                    foliage_col = biome_colors.get("foliage_linear", [0.18, 0.41, 0.03, 1.0])
                    water_col = biome_colors.get("water_linear", [0.05, 0.18, 0.78, 1.0])
                    dry_foliage_col = biome_colors.get("dry_foliage_linear", [0.37, 0.18, 0.06, 1.0])
                    cm_uv = biome_colors.get("colormap_uv", [0.2, 0.32])

                    # Rust owns the per-face category/color composition. Python only
                    # reads/writes flat buffers, so slider drags stay memory-bandwidth bound.
                    try:
                        from ....bridge.material import reapply_uniform_biome_tint
                    except (ImportError, ValueError):
                        try:
                            from bridge.material import reapply_uniform_biome_tint
                        except Exception:
                            reapply_uniform_biome_tint = None

                    if reapply_uniform_biome_tint is not None and len(base_tt) == num_polys:
                        attr_col = mesh.attributes.get(ATTR_BIOME_TINT_COLOR)
                        # Only hardcoded faces need the previous colors. Avoid a
                        # 4-byte-per-face read when the mesh has none.
                        needs_existing_colors = bool(np.any(base_tt == TINT_TYPE_HARDCODED))
                        if (
                            needs_existing_colors
                            and attr_col is not None
                            and len(attr_col.data) == num_polys
                            and hasattr(attr_col.data, "foreach_get")
                        ):
                            old_cols = np.empty(num_polys * 4, dtype=np.float32)
                            attr_col.data.foreach_get("color", old_cols)
                        else:
                            old_cols = np.empty(0, dtype=np.float32)

                        packed_mv, colors_mv, uvs_mv = reapply_uniform_biome_tint(
                            np.ascontiguousarray(base_tt, dtype=np.uint8),
                            np.ascontiguousarray(raw_data, dtype=np.float32),
                            np.ascontiguousarray(old_cols, dtype=np.float32),
                            grass_col,
                            foliage_col,
                            dry_foliage_col,
                            water_col,
                            cm_uv,
                            has_custom_grass=has_custom_grass,
                            has_custom_foliage=has_custom_foliage,
                            has_custom_dry_foliage=has_custom_dry_foliage,
                        )

                        tint_data_attr.data.foreach_set(
                            "color", np.frombuffer(packed_mv, dtype=np.float32)
                        )
                        if attr_col is not None and len(attr_col.data) == num_polys and hasattr(attr_col.data, "foreach_set"):
                            attr_col.data.foreach_set(
                                "color", np.frombuffer(colors_mv, dtype=np.float32)
                            )

                        attr_uv = mesh.attributes.get(ATTR_COLORMAP_UV)
                        if attr_uv is not None and len(attr_uv.data) == num_polys and hasattr(attr_uv.data, "foreach_set"):
                            attr_uv.data.foreach_set(
                                "vector", np.frombuffer(uvs_mv, dtype=np.float32)
                            )

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
                    key = (mat.get("mtk_source_texture_key") or mat.get("mtk:material_id") or "") if mat else ""
                    derived_keys.append(str(key))

                # Never derive provenance from atlas chunk material names: that
                # would zero every face's tint type and break later presets.
                if derived_keys and all(derived_keys):
                    try:
                        from ....bridge.mesh import inject_face_attribute_string
                        inject_face_attribute_string(mesh, ATTR_SOURCE_TEXTURE_KEY, derived_keys)
                    except (ImportError, ValueError):
                        try:
                            from MoziToolKit.bridge.mesh import inject_face_attribute_string
                            inject_face_attribute_string(mesh, ATTR_SOURCE_TEXTURE_KEY, derived_keys)
                        except (ImportError, ValueError):
                            try:
                                from bridge.mesh import inject_face_attribute_string
                                inject_face_attribute_string(mesh, ATTR_SOURCE_TEXTURE_KEY, derived_keys)
                            except Exception:
                                pass
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
    # Attribute writes via foreach_set already tag the mesh; update() is cheap and
    # guarantees the evaluated mesh / shader Attribute nodes see the new buffers.
    if hasattr(mesh, "update"):
        mesh.update()
    return True
