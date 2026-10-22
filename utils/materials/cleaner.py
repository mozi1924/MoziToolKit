"""
Vectorized material/index remapping utilities.

Only ``remap_indices_lut`` remains public: it is used by the world material
binding path to remap polygon material indices without Python-level loops.
The former per-object scene cleaners were removed because Blender already
provides ``bpy.ops.object.material_slot_remove_unused``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from ...bridge.mesh.attribute_schema import (
    ATTR_ANIM_FRAME_SIZE,
    ATTR_ANIM_TIMING,
    ATTR_BLOCK_X,
    ATTR_BLOCK_Y,
    ATTR_BLOCK_Z,
    RETIRED_ATTRIBUTE_NAMES,
)

logger = logging.getLogger("MoziToolKit.Utils.Materials.Cleaner")

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False


def remap_indices_lut(
    indices: Any,
    mapping: Dict[int, int],
    default_value: int = 0,
) -> Any:
    """
    Vectorized integer index remapping using a dense Look-Up Table (LUT).

    Avoids Python-level list comprehension over hundreds of thousands of
    polygon indices. Falls back gracefully if mapping keys or indices are
    negative, empty, or exceed reasonable LUT bounds.
    """
    if not mapping or len(indices) == 0:
        if HAS_NUMPY and isinstance(indices, np.ndarray):
            return np.full_like(indices, default_value, dtype=np.int32)
        return [default_value] * len(indices)

    if HAS_NUMPY and isinstance(indices, np.ndarray):
        try:
            max_idx = int(indices.max())
            min_idx = int(indices.min())
            if min_idx >= 0 and max_idx < 1_000_000:
                max_key = max(mapping.keys())
                min_key = min(mapping.keys())
                if min_key >= 0 and max_key < 1_000_000:
                    lut_size = max(max_idx, max_key) + 1
                    lut = np.full(lut_size, default_value, dtype=np.int32)
                    for k, v in mapping.items():
                        lut[k] = v
                    return lut[indices]
        except Exception:
            pass
        return np.array(
            [mapping.get(int(idx), default_value) for idx in indices],
            dtype=np.int32,
        )

    return [mapping.get(int(idx), default_value) for idx in indices]


def clean_obsolete_mesh_attributes(mesh_or_obj: Any) -> list[str]:
    """
    Purges retired MTK attributes from a Blender mesh.

    The retired-name list comes from the native attribute schema; active
    provenance/material/metadata attributes are never touched.
    """
    if mesh_or_obj is None:
        return []

    mesh = getattr(mesh_or_obj, "data", mesh_or_obj)
    if not hasattr(mesh, "attributes"):
        return []

    removed: list[str] = []
    for name in RETIRED_ATTRIBUTE_NAMES:
        attr = mesh.attributes.get(name)
        if attr is not None:
            try:
                mesh.attributes.remove(attr)
                removed.append(name)
            except Exception as exc:
                logger.debug("Failed to purge retired attribute %s: %s", name, exc)

    return removed

def mesh_has_animation(mesh_or_obj: Any) -> bool:
    """Returns True when the mesh carries at least one animated face."""
    mesh = getattr(mesh_or_obj, "data", mesh_or_obj)
    attributes = getattr(mesh, "attributes", None)
    if attributes is None:
        return False
    attr = attributes.get(ATTR_ANIM_TIMING)
    if attr is None or len(attr.data) == 0:
        return False
    if HAS_NUMPY and hasattr(attr.data, "foreach_get"):
        raw = np.empty(len(attr.data) * 3, dtype=np.float32)
        attr.data.foreach_get("vector", raw)
        return bool((raw[0::3] > 1.0).any())
    for elem in attr.data:
        vector = getattr(elem, "vector", None)
        if vector is not None and vector[0] > 1.0:
            return True
    return False


def prune_optional_mesh_attributes(
    mesh_or_obj: Any,
    keep_animation: bool,
    keep_block_coords: bool,
    keep_source_texture_string: bool = True,
) -> list[str]:
    """Removes optional attributes that the current mesh origin does not need.

    Animation metrics only matter for animated materials; world block coordinates
    are only needed by internal voxel/save/sync meshes that can re-sample 3D
    biomes. Provenance itself is always kept.
    """
    mesh = getattr(mesh_or_obj, "data", mesh_or_obj)
    attributes = getattr(mesh, "attributes", None)
    if attributes is None:
        return []

    candidates: list[str] = []
    if not keep_animation:
        candidates.extend((ATTR_ANIM_TIMING, ATTR_ANIM_FRAME_SIZE))
    if not keep_block_coords:
        candidates.extend((ATTR_BLOCK_X, ATTR_BLOCK_Y, ATTR_BLOCK_Z))

    removed: list[str] = []
    for name in candidates:
        attr = attributes.get(name)
        if attr is None:
            continue
        try:
            attributes.remove(attr)
            removed.append(name)
        except Exception as exc:
            logger.debug("Failed to prune optional attribute %s: %s", name, exc)
    return removed
