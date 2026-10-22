"""
Vectorized material/index remapping utilities.

Only ``remap_indices_lut`` remains public: it is used by the world material
binding path to remap polygon material indices without Python-level loops.
The former per-object scene cleaners were removed because Blender already
provides ``bpy.ops.object.material_slot_remove_unused``.
"""

from __future__ import annotations

from typing import Any, Dict

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
    Purges dead, redundant, and obsolete MTK attributes from a Blender mesh.

    Removes obsolete attributes (e.g. mtk_colormap_uv, mtk_material_slot, mtk_atlas_texture_id,
    mtk_anim_total_frames, mtk_material_props, etc.) leaving only canonical active attributes.
    Preserves provenance attributes such as mtk_source_texture_key, mtk_source_texture_idx,
    and mtk_atlas_chunk_id.
    """
    if mesh_or_obj is None:
        return []

    mesh = getattr(mesh_or_obj, "data", mesh_or_obj)
    if not hasattr(mesh, "attributes"):
        return []

    from .constants import EXCLUDED_MESH_ATTRIBUTES

    removed: list[str] = []
    for name in EXCLUDED_MESH_ATTRIBUTES:
        attr = mesh.attributes.get(name)
        if attr is not None:
            try:
                mesh.attributes.remove(attr)
                removed.append(name)
            except Exception:
                pass

    return removed

