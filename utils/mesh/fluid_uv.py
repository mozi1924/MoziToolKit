"""
Fluid UV repair utilities.

Fixes inverted UV heights on Minecraft fluid quad faces (e.g. water, lava flowing
slopes where the top two vertices have their UV V coordinates inverted relative
to their 3D heights).
"""

from __future__ import annotations

from typing import Optional, List, Sequence
import math

try:
    import bpy
    import bmesh
    from mathutils import Vector
except ImportError:
    bpy = None
    bmesh = None
    Vector = None


def _evaluate_face_axis(face, loops, up_axis: Vector):
    """
    Project up_axis onto face plane and evaluate base flatness and top slope.
    """
    normal = face.normal
    if normal.length < 1e-6:
        face.normal_update()
        normal = face.normal
        if normal.length < 1e-6:
            return None

    proj_up = up_axis - (up_axis.dot(normal)) * normal
    if proj_up.length < 1e-4:
        return None
    proj_up.normalize()

    heights = [(i, l.vert.co.dot(proj_up)) for i, l in enumerate(loops)]
    heights_sorted = sorted(heights, key=lambda x: x[1])

    b1_idx, h_b1 = heights_sorted[0]
    b2_idx, h_b2 = heights_sorted[1]
    t1_idx, h_t1 = heights_sorted[2]
    t2_idx, h_t2 = heights_sorted[3]

    base_diff = abs(h_b2 - h_b1)
    top_diff = h_t2 - h_t1

    return {
        "proj_up": proj_up,
        "base_diff": base_diff,
        "top_diff": top_diff,
        "t1_idx": t1_idx,
        "t2_idx": t2_idx,
        "h_t1": h_t1,
        "h_t2": h_t2,
    }


def repair_face_fluid_uv(face, uv_layer, force: bool = False, min_slope_threshold: float = 0.005) -> bool:
    """
    Check and repair inverted fluid UV on a single quad face.

    :param face: bmesh face (must have 4 vertices).
    :param uv_layer: bmesh loop UV layer.
    :param force: If True, swap top UV heights if top edge is slanted even if not strictly detected as inverted.
    :param min_slope_threshold: Minimum height difference between top two vertices to consider face as slanted.
    :return: True if the face UV was modified, False otherwise.
    """
    if face is None or uv_layer is None or len(face.verts) != 4:
        return False

    loops = list(face.loops)

    # Evaluate candidate up axes: Y-up (Minecraft OBJ) and Z-up (Blender native)
    eval_y = _evaluate_face_axis(face, loops, Vector((0.0, 1.0, 0.0)))
    eval_z = _evaluate_face_axis(face, loops, Vector((0.0, 0.0, 1.0)))

    candidates = [e for e in (eval_y, eval_z) if e is not None]
    if not candidates:
        return False

    # Choose candidate with the most distinct top slope relative to base flatness
    def _axis_candidate_score(e):
        # Higher top_diff and lower base_diff is better
        return e["top_diff"] - e["base_diff"]

    best_eval = max(candidates, key=_axis_candidate_score)

    top_h_diff = best_eval["top_diff"]
    if top_h_diff < min_slope_threshold and not force:
        return False

    t1_idx = best_eval["t1_idx"]
    t2_idx = best_eval["t2_idx"]

    loop_t1 = loops[t1_idx]
    loop_t2 = loops[t2_idx]

    uv1 = loop_t1[uv_layer].uv
    uv2 = loop_t2[uv_layer].uv

    # In standard UV mapping, V corresponds to height.
    # Since h_t1 < h_t2, we expect uv1.y <= uv2.y.
    # If uv1.y > uv2.y (within tolerance), it is inverted.
    uv_v_diff = uv2.y - uv1.y
    is_inverted = (uv_v_diff < -1e-5)

    if is_inverted or (force and top_h_diff >= min_slope_threshold):
        old_v1_y = uv1.y
        loop_t1[uv_layer].uv.y = uv2.y
        loop_t2[uv_layer].uv.y = old_v1_y
        return True

    return False


def process_mesh_fluid_uv_repairs(
    bm,
    uv_layer=None,
    target_faces: Optional[Sequence] = None,
    force: bool = False,
) -> int:
    """
    Repair fluid UV inversions across target faces or the entire mesh.

    :param bm: bmesh object.
    :param uv_layer: bmesh loop UV layer. If None, active UV layer is used.
    :param target_faces: Specific faces to process. If None, all faces in bm.faces are processed.
    :param force: Force swap on target faces even if slope inversion test is borderline.
    :return: Number of faces successfully repaired.
    """
    if bm is None:
        return 0

    if uv_layer is None:
        uv_layer = bm.loops.layers.uv.verify()

    faces_to_process = target_faces if target_faces is not None else bm.faces
    repaired_count = 0

    for face in faces_to_process:
        if repair_face_fluid_uv(face, uv_layer, force=force):
            repaired_count += 1

    return repaired_count
