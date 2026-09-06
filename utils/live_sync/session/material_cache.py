"""
Material atlas parameter extraction and cache management for Live Sync.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
import bpy

from ...mc_baker import clear_shared_baker_cache
from ..meshing import clear_mesh_builder_caches

logger = logging.getLogger("MoziToolKit.LiveSync.MaterialCache")

_cached_atlas_params: Optional[dict] = None
_cached_mat_signature: Optional[tuple] = None


def extract_atlas_params(mat: Optional[bpy.types.Material], pack_stack: Any = None) -> dict:
    """Safely extract atlas mapping parameters from material or current pack stack."""
    try:
        from ...materials.yefira import extract_atlas_parameters
        return extract_atlas_parameters(mat, pack_stack=pack_stack)
    except (ImportError, ValueError):
        try:
            from utils.materials.yefira import extract_atlas_parameters
            return extract_atlas_parameters(mat, pack_stack=pack_stack)
        except Exception:
            return {}


def find_bound_atlas_material(obj: Optional[bpy.types.Object]) -> Optional[bpy.types.Material]:
    """Find the active bound atlas material on a container root or mesh object."""
    try:
        from ...materials.yefira import find_bound_atlas_material as _find_bound
        return _find_bound(obj)
    except (ImportError, ValueError):
        try:
            from utils.materials.yefira import find_bound_atlas_material as _find_bound
            return _find_bound(obj)
        except Exception:
            return None


def get_cached_atlas_params(mat: Optional[bpy.types.Material]) -> dict:
    """Retrieve atlas parameters authoritatively, invalidating when material or pack stack changes."""
    global _cached_atlas_params, _cached_mat_signature
    try:
        from ...materials.pack import get_configured_pack_stack
        from ...materials.pipeline.provenance import get_effective_pack_hash, is_material_hash_valid
    except (ImportError, ValueError):
        from utils.materials.pack import get_configured_pack_stack
        from utils.materials.pipeline.provenance import get_effective_pack_hash, is_material_hash_valid

    pack_stack = None
    stack_hash = ""
    try:
        pack_stack = get_configured_pack_stack()
        stack_hash = get_effective_pack_hash(pack_stack)
    except Exception:
        pass

    if mat and stack_hash and not is_material_hash_valid(mat, stack_hash):
        mat = None

    if mat:
        mapping = mat.get("mtk:atlas_mapping", mat.get("mtk_atlas_mapping", ""))
        current_signature = (
            mat.as_pointer() if hasattr(mat, "as_pointer") else id(mat),
            mapping,
            get_effective_pack_hash(mat),
            stack_hash,
        )
    else:
        current_signature = (0, "", "", stack_hash)

    if _cached_atlas_params is None or _cached_mat_signature != current_signature:
        _cached_mat_signature = current_signature
        _cached_atlas_params = extract_atlas_params(mat, pack_stack=pack_stack)
        clear_mesh_builder_caches()
    return _cached_atlas_params


def clear_sync_caches() -> None:
    """Invalidate atlas parameter cache, mesh builder caches, and baker caches on material or world reset."""
    global _cached_atlas_params, _cached_mat_signature
    _cached_atlas_params = None
    _cached_mat_signature = None
    clear_mesh_builder_caches()
    clear_shared_baker_cache()

    from .registry import get_active_session_manager
    mgr = get_active_session_manager()
    if mgr:
        for s in mgr.get_all_sessions():
            s.clear_caches()
