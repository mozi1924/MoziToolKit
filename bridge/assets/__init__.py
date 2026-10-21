"""
Bridge: Asset Precompilation & Resource Stack Management Subsystem.
Transfers resource pack configuration from Blender to libmtk (Rust) for
headless Atlas stitching, Standalone material generation, and Model baking.
Zero-computation on the Python side: all parsing, packing, image decoding,
and geometric meshing are handled entirely within libmtk.
"""

from __future__ import annotations

from typing import Any

from ..engine import get_libmtk, has_libmtk, require_libmtk
from .cache import (
    check_cache_dirty,
    clear_cache,
    ensure_atlas_textures_extracted,
    ensure_colormaps_extracted,
    get_active_cache_package_path,
    get_cache_dir,
    get_cache_fingerprint,
    get_cache_manifest,
    get_cache_stats,
    get_cache_timestamp,
    get_cached_texture_f32,
    get_cached_texture_rgba,
    invalidate_asset_cache_memory,
    load_atlas_from_cache,
    load_atlas_mapping_from_cache,
    load_baked_atlas_from_cache,
    load_baked_model_database,
    load_biome_resolver_from_cache,
    load_model_database_from_cache,
    open_active_asset_cache,
    open_cache_folder,
)
from .pack import get_configured_ctm_solver, get_configured_pack_stack
from .precompile import (
    precompile_stack,
    precompile_stack_async,
    reload_atlas_images,
)


def _get_libmtk():
    return get_libmtk()


def _has_libmtk() -> bool:
    return has_libmtk()


def __getattr__(name: str) -> Any:
    if name == "HAS_LIBMTK":
        return has_libmtk()
    if name == "libmtk_py":
        return get_libmtk()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    "get_configured_pack_stack",
    "get_configured_ctm_solver",
    "precompile_stack",
    "precompile_stack_async",
    "invalidate_asset_cache_memory",
    "get_active_cache_package_path",
    "open_active_asset_cache",
    "load_atlas_mapping_from_cache",
    "get_cached_texture_rgba",
    "get_cached_texture_f32",
    "ensure_atlas_textures_extracted",
    "ensure_colormaps_extracted",
    "load_baked_model_database",
    "load_model_database_from_cache",
    "load_atlas_from_cache",
    "load_baked_atlas_from_cache",
    "load_biome_resolver_from_cache",
    "get_cache_manifest",
    "get_cache_fingerprint",
    "get_cache_timestamp",
    "check_cache_dirty",
    "reload_atlas_images",
    "clear_cache",
    "get_cache_dir",
    "get_cache_stats",
    "open_cache_folder",
]
