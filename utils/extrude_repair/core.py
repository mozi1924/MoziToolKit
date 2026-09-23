"""
Extrude UV Repair Core Module for MoziToolKit.

Accelerated via Rust libmtk Data In, Data Out architecture.
"""

from typing import Optional, Set

try:
    from ...bridge.extrude import repair_mesh_extruded_side_faces_batch
except (ImportError, ValueError):
    from bridge.extrude import repair_mesh_extruded_side_faces_batch


def repair_extruded_side_faces(
    bm,
    obj=None,
    context=None,
    repair_uv: bool = True,
    add_crease: bool = False,
    crease_val: float = 1.0,
    only_collapsed: bool = False,
    uv_mode: str = "INWARD",
    smart_side_face_indices: Optional[Set[int]] = None,
) -> int:
    """Repair UV overlapping and add Mean Crease to side faces created during face extrusion.

    Fully supports Atlas textures (Unified Atlas, Baked Atlas, animated strips, non-square)
    with anisotropic 2D pixel stepping, safety UV bounds clamping, and material isolation.
    All calculations are executed in a single Rust FFI batch.

    :param bm: BMesh instance in edit mode.
    :param obj: Target Blender Object (for material resolution).
    :param context: Blender context.
    :param repair_uv: Whether to project and fix UVs on extruded side faces.
    :param add_crease: Whether to add Mean Crease to side edges.
    :param crease_val: Crease weight value (0.0 to 1.0).
    :param only_collapsed: If True, only repair collapsed side faces or active extruded side faces.
    :param uv_mode: 'SMART' (derive from extrusion direction), 'INWARD'
        (shrink side UVs into the selected face pixel), or 'OUTWARD' (use the
        pixel from each adjacent, unselected face when one exists).
    :param smart_side_face_indices: Mutable set of side-face indices belonging
        to the current interactive smart extrusion.
    :return: Number of repaired side faces.
    """
    return repair_mesh_extruded_side_faces_batch(
        bm=bm,
        obj=obj,
        context=context,
        repair_uv=repair_uv,
        add_crease=add_crease,
        crease_val=crease_val,
        only_collapsed=only_collapsed,
        uv_mode=uv_mode,
        smart_side_face_indices=smart_side_face_indices,
    )
