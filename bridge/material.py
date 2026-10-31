"""
MoziToolKit Material & Biome Bridge Module.
Encapsulates high-performance Rust core (libmtk_py) routines for material name resolution,
UV remapping, atlas metadata, and Biome color/tint generation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from .engine import get_libmtk, has_libmtk, require_libmtk

logger = logging.getLogger(__name__)


def is_material_bridge_available() -> bool:
    """Check if native libmtk_py material and biome functions are loaded."""
    mtk = get_libmtk()
    return bool(
        mtk is not None
        and hasattr(mtk, "MaterialResolver")
        and hasattr(mtk, "BiomeResolver")
    )


def require_material_bridge() -> None:
    """Raise RuntimeError if native libmtk_py material bridge is unavailable."""
    if not is_material_bridge_available():
        require_libmtk("material & biome bridge")


# ---------------------------------------------------------------------------
# Biome Tint Constants & Bridge Proxy
# ---------------------------------------------------------------------------

mtk_inst = get_libmtk()
TINT_TYPE_NONE: int = getattr(mtk_inst, "TINT_TYPE_NONE", 0) if mtk_inst else 0
TINT_TYPE_GRASS: int = getattr(mtk_inst, "TINT_TYPE_GRASS", 1) if mtk_inst else 1
TINT_TYPE_FOLIAGE: int = getattr(mtk_inst, "TINT_TYPE_FOLIAGE", 2) if mtk_inst else 2
TINT_TYPE_WATER: int = getattr(mtk_inst, "TINT_TYPE_WATER", 3) if mtk_inst else 3
TINT_TYPE_HARDCODED: int = getattr(mtk_inst, "TINT_TYPE_HARDCODED", 4) if mtk_inst else 4
TINT_TYPE_DRY_FOLIAGE: int = getattr(mtk_inst, "TINT_TYPE_DRY_FOLIAGE", 5) if mtk_inst else 5


def __getattr__(name: str) -> Any:
    mtk = get_libmtk()
    if name == "HAS_LIBMTK":
        return is_material_bridge_available()
    if name in ("BiomeResolver", "MaterialResolver", "GridAtlasSpec", "BakedAtlas"):
        require_material_bridge()
        val = getattr(mtk, name, None)
        if val is None:
            raise AttributeError(f"libmtk_py does not expose '{name}'")
        return val
    if name.startswith("TINT_TYPE_"):
        if mtk and hasattr(mtk, name):
            return getattr(mtk, name)
        require_material_bridge()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


# ---------------------------------------------------------------------------
# Biome Metadata & Colormap API
# ---------------------------------------------------------------------------

def load_biome_resolver_from_file(file_path: Union[str, Path]) -> Any:
    """Load a precompiled BiomeResolver instance from a biome_mapping.json file."""
    mtk = require_libmtk("load_biome_resolver_from_file")
    return mtk.BiomeResolver.from_file(str(file_path))


def get_biome_meta(biome_name: str) -> Dict[str, Any]:
    """Retrieve canonical metadata, temperature, humidity, and colors from Rust core."""
    mtk = require_libmtk("get_biome_meta")
    return mtk.get_biome_meta(biome_name)


def sample_colormap_colors(temperature: float, humidity: float) -> Dict[str, List[float]]:
    """Sample resident vanilla colormap linear RGBA colors from temperature and humidity in Rust."""
    mtk = require_libmtk("sample_colormap_colors")
    return mtk.sample_colormap_colors(float(temperature), float(humidity))


def get_all_biomes() -> List[Dict[str, Any]]:
    """Retrieve all standard vanilla Minecraft biomes with canonical metadata."""
    mtk = require_libmtk("get_all_biomes")
    return mtk.get_all_biomes()


def compute_biome_tint_attributes(
    face_texture_keys: List[str],
    biome_preset: Union[str, List[Tuple[str, float]]] = "PLAINS",
    resolver: Optional[Any] = None,
    custom_temp: Optional[float] = None,
    custom_humidity: Optional[float] = None,
    custom_grass: Optional[List[float]] = None,
    custom_foliage: Optional[List[float]] = None,
    custom_dry_foliage: Optional[List[float]] = None,
    custom_water: Optional[List[float]] = None,
    has_custom_grass: bool = False,
    has_custom_foliage: bool = False,
    has_custom_dry_foliage: bool = False,
    face_biomes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Compute packed tint weights and resolved Linear RGBA colors using the Rust core.
    Returns a dictionary with keys: 'packed_tint_data', 'tint_colors'.
    """
    mtk = require_libmtk("compute_biome_tint_attributes")

    if face_biomes is not None:
        return mtk.compute_biome_tint_attributes(
            face_texture_keys,
            "PLAINS",
            resolver=resolver,
            face_biomes=face_biomes,
        )

    if isinstance(biome_preset, list):
        return mtk.compute_biome_tint_attributes(
            face_texture_keys,
            "PLAINS",
            multi_biomes=biome_preset,
            resolver=resolver,
        )

    return mtk.compute_biome_tint_attributes(
        face_texture_keys,
        str(biome_preset),
        multi_biomes=None,
        resolver=resolver,
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


def compute_biome_tint_attributes_paletted(
    palette: Sequence[str],
    face_indices: Sequence[int],
    biome_preset: Union[str, List[Tuple[str, float]]] = "PLAINS",
    resolver: Optional[Any] = None,
    custom_temp: Optional[float] = None,
    custom_humidity: Optional[float] = None,
    custom_grass: Optional[List[float]] = None,
    custom_foliage: Optional[List[float]] = None,
    custom_dry_foliage: Optional[List[float]] = None,
    custom_water: Optional[List[float]] = None,
    has_custom_grass: bool = False,
    has_custom_foliage: bool = False,
    has_custom_dry_foliage: bool = False,
) -> Tuple[np.ndarray, np.ndarray]:
    """Palette-native biome tint computation returning zero-copy flat arrays."""
    mtk = require_libmtk("compute_biome_tint_attributes_paletted")
    multi = list(biome_preset) if isinstance(biome_preset, list) else None
    name = "PLAINS" if multi is not None else str(biome_preset)
    packed, colors = mtk.compute_biome_tint_attributes_paletted(
        list(palette),
        face_indices,
        name,
        multi_biomes=multi,
        resolver=resolver,
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
    return (
        np.frombuffer(packed, dtype=np.float32).reshape(-1, 4),
        np.frombuffer(colors, dtype=np.float32).reshape(-1, 4),
    )


def reapply_uniform_biome_tint(
    base_tint_types: Any,
    packed_tint_data: Any,
    existing_tint_colors: Any,
    grass_color: Sequence[float],
    foliage_color: Sequence[float],
    dry_foliage_color: Sequence[float],
    water_color: Sequence[float],
    has_custom_grass: bool = False,
    has_custom_foliage: bool = False,
    has_custom_dry_foliage: bool = False,
) -> Any:
    """
    Re-apply a uniform biome palette using Rust parallel math.

    Inputs are flat buffers:
      - base_tint_types: uint8 per face
      - packed_tint_data: float32 x 4 per face
      - existing_tint_colors: float32 x 4 per face (may be empty)

    Returns zero-copy memoryviews for (packed_tint_data, tint_colors).
    """
    mtk = require_libmtk("reapply_uniform_biome_tint")
    return mtk.reapply_uniform_biome_tint(
        base_tint_types,
        packed_tint_data,
        existing_tint_colors,
        tuple(grass_color),
        tuple(foliage_color),
        tuple(dry_foliage_color),
        tuple(water_color),
        bool(has_custom_grass),
        bool(has_custom_foliage),
        bool(has_custom_dry_foliage),
    )


def compute_mesh_biome_attributes_from_storage(
    face_texture_keys: List[str],
    block_xs: List[int],
    block_ys: List[int],
    block_zs: List[int],
    storage: Any,
    resolver: Optional[Any] = None,
    smooth: bool = True,
) -> Dict[str, Any]:
    """
    Compute coordinate-aware 3D biome tint attributes from VoxelStorage container.
    """
    mtk = require_libmtk("compute_mesh_biome_attributes_from_storage")
    return mtk.compute_mesh_biome_attributes_from_storage(
        face_texture_keys,
        block_xs,
        block_ys,
        block_zs,
        storage,
        resolver=resolver,
        smooth=smooth,
    )


# ---------------------------------------------------------------------------
# Material Resolution & UV Remapping
# ---------------------------------------------------------------------------

def clean_material_name(name: str) -> str:
    """Normalize and clean a material or texture name into an identifier stem."""
    mtk = require_libmtk("clean_material_name")
    return mtk.MaterialResolver.clean_name(name)


def remap_mesh_multi_uvs_paletted(
    loop_uvs: Sequence[float],
    face_material_palette: Sequence[str],
    face_material_indices: Sequence[int],
    face_loop_ranges: Sequence[Tuple[int, int]],
    atlas: Any,
    alias_map: Optional[Dict[str, List[str]]] = None,
    grid_spec: Optional[Any] = None,
    existing_key_palette: Optional[Sequence[str]] = None,
    existing_key_indices: Optional[Sequence[int]] = None,
    enable_animated_textures: bool = False,
) -> Any:
    """Palette-native multi-UV remap returning zero-copy id/metric buffers."""
    mtk = require_libmtk("remap_mesh_multi_uvs_paletted")
    return mtk.MaterialResolver.remap_mesh_multi_uvs_paletted(
        loop_uvs if isinstance(loop_uvs, (list, np.ndarray)) else list(loop_uvs),
        list(face_material_palette),
        face_material_indices,
        face_loop_ranges if isinstance(face_loop_ranges, list) else list(face_loop_ranges),
        atlas,
        alias_map,
        grid_spec,
        list(existing_key_palette) if existing_key_palette is not None else None,
        existing_key_indices,
        bool(enable_animated_textures),
    )


def resolve_mesh_material_routes(
    face_texture_keys: Sequence[str],
    atlas: Any,
    alias_map: Optional[Dict[str, List[str]]] = None,
    enable_animated_textures: bool = False,
) -> Any:
    """Resolve atlas chunk/texture routing and animation metadata for face keys in Rust."""
    mtk = require_libmtk("resolve_mesh_material_routes")
    return mtk.MaterialResolver.resolve_mesh_routes(
        list(face_texture_keys),
        atlas,
        alias_map,
        bool(enable_animated_textures),
    )


def reroute_mesh_animation(
    loop_uvs: Sequence[float],
    face_loop_ranges: Sequence[Tuple[int, int]],
    face_texture_keys: Sequence[str],
    face_old_chunk_ids: Sequence[int],
    atlas: Any,
    alias_map: Optional[Dict[str, List[str]]] = None,
    enable_animated_textures: bool = False,
) -> Any:
    """Re-project existing atlas UVs from the previous chunk routing to a new animation policy."""
    mtk = require_libmtk("reroute_mesh_animation")
    return mtk.MaterialResolver.reroute_mesh_animation(
        loop_uvs if isinstance(loop_uvs, (list, np.ndarray)) else list(loop_uvs),
        face_loop_ranges if isinstance(face_loop_ranges, list) else list(face_loop_ranges),
        list(face_texture_keys),
        [int(x) for x in face_old_chunk_ids],
        atlas,
        alias_map,
        bool(enable_animated_textures),
    )


def load_baked_atlas_from_json(json_str: str) -> Any:
    """Load a BakedAtlas instance from atlas_mapping.json string content."""
    mtk = require_libmtk("load_baked_atlas_from_json")
    return mtk.BakedAtlas.from_mapping_json(json_str)


def build_material_palette(
    slot_names: Sequence[str],
    slot_is_mtk: Sequence[bool],
    slot_source_ids: Sequence[str],
    poly_mats: Any,
    existing_key_palette: Optional[Sequence[str]] = None,
    existing_key_indices: Optional[Any] = None,
) -> Tuple[List[str], np.ndarray]:
    """Build a deduplicated material palette and per-face index buffer via libmtk."""
    mtk = require_libmtk("build_material_palette")
    palette, indices_mv = mtk.build_material_palette(
        list(slot_names),
        list(slot_is_mtk),
        list(slot_source_ids),
        poly_mats,
        list(existing_key_palette) if existing_key_palette is not None else None,
        existing_key_indices,
    )
    indices = np.frombuffer(indices_mv, dtype=np.uint32)
    return palette, indices


# ---------------------------------------------------------------------------
# Texture Descriptor & Slot Resolution
# ---------------------------------------------------------------------------

def get_chunk_texture_specs(chunk_meta: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Extract the authoritative list of texture slot specifications for an atlas chunk.
    Falls back gracefully to legacy channel flags if the 'textures' field is absent.
    """
    raw_textures = chunk_meta.get("textures")
    if raw_textures:
        return [dict(t) for t in raw_textures]

    cat = str(chunk_meta.get("category", "blocks"))
    c_idx = int(chunk_meta.get("category_chunk_index", 1))
    is_anim = bool(chunk_meta.get("is_animated", False))
    stem = chunk_meta.get("file_stem") or (
        f"{cat}_anim_chunk_{c_idx:03}" if is_anim else f"{cat}_chunk_{c_idx:03}"
    )

    specs = [{"role": "albedo", "file_name": f"{stem}.png", "colorspace": "sRGB"}]
    if chunk_meta.get("has_normal"):
        specs.append({"role": "normal", "file_name": f"{stem}_n.png", "colorspace": "Non-Color"})
    if chunk_meta.get("has_orm"):
        specs.append({"role": "orm", "file_name": f"{stem}_orm.png", "colorspace": "Non-Color"})
    if chunk_meta.get("has_aux"):
        specs.append({"role": "aux", "file_name": f"{stem}_aux.png", "colorspace": "Non-Color"})
    if chunk_meta.get("has_overlay"):
        specs.append({"role": "overlay", "file_name": f"{stem}_overlay.png", "colorspace": "sRGB"})
    return specs


def resolve_chunk_texture_sources(
    chunk_meta: Dict[str, Any],
    atlas_dir: Optional[Union[str, Path]] = None,
    active_atlas: Optional[Any] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Resolve active texture slot sources (filesystem Path or zero-copy in-memory buffer) for a chunk.
    Returns a dictionary mapping role -> {
        'role': str,
        'source': Path | tuple[int, int, Any] | None,
        'colorspace': str,
        'file_name': str,
        'chunk_id': str,
    }
    """
    specs = get_chunk_texture_specs(chunk_meta)
    width = int(chunk_meta.get("width", 1024))
    height = int(chunk_meta.get("height", 1024))
    chunk_id = int(chunk_meta.get("chunk_id", 0))
    atlas_path = Path(atlas_dir) if atlas_dir is not None else None

    # Map roles to in-memory PyBakedAtlas getters
    memory_getter_map = {
        "albedo": "get_chunk_albedo_f32",
        "normal": "get_chunk_normal_f32",
        "orm": "get_chunk_orm_f32",
        "aux": "get_chunk_aux_f32",
        "overlay": "get_chunk_overlay_f32",
    }

    resolved: Dict[str, Dict[str, Any]] = {}
    for spec in specs:
        role = spec["role"]
        file_name = spec["file_name"]
        colorspace = spec.get("colorspace", "sRGB")
        disk_path = (atlas_path / file_name) if atlas_path is not None else None

        source: Any = disk_path

        # If disk file is unavailable, stream zero-copy in-memory from active_atlas
        if (disk_path is None or not disk_path.exists()) and active_atlas is not None:
            getter_name = memory_getter_map.get(role)
            if getter_name and hasattr(active_atlas, getter_name):
                try:
                    getter = getattr(active_atlas, getter_name)
                    buf = getter(chunk_id, flip_v=True)
                    if buf is not None:
                        source = (width, height, buf)
                except Exception:
                    pass

        resolved[role] = {
            "role": role,
            "source": source,
            "colorspace": colorspace,
            "file_name": file_name,
            "chunk_id": f"atlas/textures/{file_name}",
        }
    return resolved


__all__ = [
    "HAS_LIBMTK",
    "is_material_bridge_available",
    "require_material_bridge",
    "BiomeResolver",
    "load_biome_resolver_from_file",
    "get_biome_meta",
    "sample_colormap_colors",
    "get_all_biomes",
    "compute_biome_tint_attributes",
    "compute_biome_tint_attributes_paletted",
    "compute_mesh_biome_attributes_from_storage",
    "MaterialResolver",
    "clean_material_name",
    "GridAtlasSpec",
    "BakedAtlas",
    "load_baked_atlas_from_json",
    "build_material_palette",
    "get_chunk_texture_specs",
    "resolve_chunk_texture_sources",
    "TINT_TYPE_NONE",
    "TINT_TYPE_GRASS",
    "TINT_TYPE_FOLIAGE",
    "TINT_TYPE_WATER",
    "TINT_TYPE_HARDCODED",
    "TINT_TYPE_DRY_FOLIAGE",
]


