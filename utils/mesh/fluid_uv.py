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


def is_fluid_texture_name(name: Optional[str]) -> bool:
    """Check if a texture or material name represents water or lava."""
    if not name:
        return False
    name_clean = name.strip().lower()
    return "water" in name_clean or "lava" in name_clean


def is_flowing_fluid_texture(name: Optional[str]) -> bool:
    """Check if a texture or material name represents flowing fluid."""
    if not name:
        return False
    name_clean = name.strip().lower()
    is_fluid = "water" in name_clean or "lava" in name_clean
    is_flow = "flow" in name_clean or "flowing" in name_clean
    return is_fluid and is_flow


def get_fluid_top_uvs(is_flowing: bool = True, rotation: float = 0.0) -> tuple[tuple[float, float], ...]:
    """
    Get Minecraft-standard UV coordinates for top/bottom fluid faces.
    
    Flowing fluids sample a 16x16 window ([0.25, 0.75]) inside the 32x32 sprite,
    centered at (0.5, 0.5), with rotation baked directly into the coordinates.
    Stationary source pools sample the standard full [0, 1] sprite.
    """
    if not is_flowing:
        return ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0))

    base_uvs = ((0.25, 0.25), (0.25, 0.75), (0.75, 0.75), (0.75, 0.25))
    if abs(rotation) < 1e-4:
        return base_uvs

    # In MC coordinate space (where Y is inverted relative to Blender UV space),
    # rotating Blender UV by +rotation corresponds to rotating MC UV by -rotation:
    cos_t = math.cos(-rotation)
    sin_t = math.sin(-rotation)
    rotated = []
    for u, v in base_uvs:
        du = u - 0.5
        dv = v - 0.5
        ru = 0.5 + (du * cos_t - dv * sin_t)
        rv = 0.5 + (du * sin_t + dv * cos_t)
        rotated.append((ru, rv))
    return tuple(rotated)


def get_fluid_side_uvs(h_left_top: float, h_right_top: float) -> tuple[tuple[float, float], ...]:
    """
    Get Minecraft/Mineways-standard UV coordinates for vertical/sloped fluid side faces.
    
    Side faces sample the [0.0, 0.5] quadrant of the 32x32 sprite, mapping
    proportional 1-block height to 16 pixels.
    """
    return (
        (0.0, (1.0 - h_left_top) * 0.5),
        (0.0, 0.5),
        (0.5, 0.5),
        (0.5, (1.0 - h_right_top) * 0.5),
    )


def repair_polygon_fluid_uv(
    polygon,
    mesh,
    uv_layer,
    force: bool = False,
    min_slope_threshold: float = 0.005,
) -> bool:
    """
    Repair inverted fluid UV on a standard bpy.types.MeshPolygon.
    """
    if polygon is None or mesh is None or uv_layer is None or len(polygon.loop_indices) != 4:
        return False

    loop_indices = list(polygon.loop_indices)
    verts = [mesh.vertices[mesh.loops[li].vertex_index] for li in loop_indices]
    normal = polygon.normal

    if normal.length < 1e-6:
        return False

    # Check for Z-up and Y-up candidate up axes
    candidates = []
    for up_axis in (Vector((0.0, 0.0, 1.0)), Vector((0.0, 1.0, 0.0))):
        proj_up = up_axis - (up_axis.dot(normal)) * normal
        if proj_up.length >= 1e-4:
            proj_up.normalize()
            heights = [(i, verts[i].co.dot(proj_up)) for i in range(4)]
            heights_sorted = sorted(heights, key=lambda x: x[1])
            base_diff = abs(heights_sorted[1][1] - heights_sorted[0][1])
            top_diff = heights_sorted[3][1] - heights_sorted[2][1]
            candidates.append({
                "top_diff": top_diff,
                "base_diff": base_diff,
                "t1_idx": heights_sorted[2][0],
                "t2_idx": heights_sorted[3][0],
            })

    if not candidates:
        return False

    best_eval = max(candidates, key=lambda e: e["top_diff"] - e["base_diff"])
    top_h_diff = best_eval["top_diff"]
    if top_h_diff < min_slope_threshold and not force:
        return False

    t1_li = loop_indices[best_eval["t1_idx"]]
    t2_li = loop_indices[best_eval["t2_idx"]]

    uv1 = uv_layer.data[t1_li].uv
    uv2 = uv_layer.data[t2_li].uv

    uv_v_diff = uv2.y - uv1.y
    is_inverted = (uv_v_diff < -1e-5)

    if is_inverted or (force and top_h_diff >= min_slope_threshold):
        old_v1_y = uv1.y
        uv1.y = uv2.y
        uv2.y = old_v1_y
        return True

    return False


def normalize_static_fluid_face_uv(
    polygon,
    mesh,
    uv_layer,
    texture_name: Optional[str] = None,
) -> bool:
    """
    Normalize static mesh fluid face UV to canonical Minecraft 16x16 sampling window.
    
    - For flowing top faces: fits UV to [0.25, 0.75] window centered at (0.5, 0.5)
      while preserving geometric rotation.
    - For side faces: repairs inverted top height V coordinates and fits to [0.0, 0.5] x [0.5, 1.0] quadrant.
    """
    if polygon is None or uv_layer is None or not polygon.loop_indices:
        return False

    is_flowing = is_flowing_fluid_texture(texture_name)
    normal = polygon.normal

    # Horizontal (Top / Bottom) Face
    if abs(normal.z) >= 0.7 or abs(normal.y) >= 0.7:
        if is_flowing:
            uvs = [uv_layer.data[li].uv for li in polygon.loop_indices]
            center_u = sum(uv.x for uv in uvs) / len(uvs)
            center_v = sum(uv.y for uv in uvs) / len(uvs)
            # Scale coordinates relative to center into [0.25, 0.75] (scale factor 0.5)
            for uv in uvs:
                uv.x = 0.5 + (uv.x - center_u) * 0.5
                uv.y = 0.5 + (uv.y - center_v) * 0.5
            return True
    else:
        # Vertical Side Face
        if len(polygon.loop_indices) == 4:
            repair_polygon_fluid_uv(polygon, mesh, uv_layer)
        if is_flowing:
            uvs = [uv_layer.data[li].uv for li in polygon.loop_indices]
            min_u = min(uv.x for uv in uvs)
            max_u = max(uv.x for uv in uvs)
            span_u = max_u - min_u
            if span_u > 0.6:  # Spans full [0, 1], compress to [0.0, 0.5]
                for uv in uvs:
                    uv.x = (uv.x - min_u) * 0.5
            min_v = min(uv.y for uv in uvs)
            max_v = max(uv.y for uv in uvs)
            span_v = max_v - min_v
            if span_v > 0.6:  # Spans full [0, 1], compress to [0.5, 1.0] (top quadrant)
                for uv in uvs:
                    uv.y = 0.5 + (uv.y - min_v) * 0.5
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

