"""
Fluid UV repair utilities.

Fixes inverted UV heights on Minecraft fluid quad faces (e.g. water, lava flowing
slopes where the top two vertices have their UV V coordinates inverted relative
to their 3D heights).
"""

from __future__ import annotations

from typing import Optional, Sequence
import math

try:
    import bpy
    import bmesh
    from mathutils import Vector
except ImportError:
    bpy = None
    bmesh = None
    Vector = None

try:
    from ...bridge.uv import (
        repair_quad_fluid_uv,
        get_fluid_top_uvs,
        get_fluid_side_uvs,
    )
except (ImportError, ValueError):
    from bridge.uv import (
        repair_quad_fluid_uv,
        get_fluid_top_uvs,
        get_fluid_side_uvs,
    )



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


def repair_face_fluid_uv(
    face,
    uv_layer,
    force: bool = False,
    min_slope_threshold: float = 0.005,
) -> bool:
    """
    Check and repair inverted fluid UV on a single BMesh quad face.

    :param face: bmesh face (must have 4 vertices).
    :param uv_layer: bmesh loop UV layer.
    :param force: If True, swap top UV heights if top edge is slanted even if not strictly detected as inverted.
    :param min_slope_threshold: Minimum height difference between top two vertices to consider face as slanted.
    :return: True if the face UV was modified, False otherwise.
    """
    if face is None or uv_layer is None or len(face.verts) != 4:
        return False

    loops = list(face.loops)
    verts = [(l.vert.co.x, l.vert.co.y, l.vert.co.z) for l in loops]
    uvs = [(l[uv_layer].uv.x, l[uv_layer].uv.y) for l in loops]
    normal = (face.normal.x, face.normal.y, face.normal.z) if face.normal.length >= 1e-6 else None

    repaired, new_uvs = repair_quad_fluid_uv(verts, uvs, normal, force, min_slope_threshold)
    if repaired:
        for l, (u, v) in zip(loops, new_uvs):
            l[uv_layer].uv.x = u
            l[uv_layer].uv.y = v
        return True

    return False


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
    verts = [
        (
            mesh.vertices[mesh.loops[li].vertex_index].co.x,
            mesh.vertices[mesh.loops[li].vertex_index].co.y,
            mesh.vertices[mesh.loops[li].vertex_index].co.z,
        )
        for li in loop_indices
    ]
    uvs = [
        (uv_layer.data[li].uv.x, uv_layer.data[li].uv.y)
        for li in loop_indices
    ]
    normal = (polygon.normal.x, polygon.normal.y, polygon.normal.z) if polygon.normal.length >= 1e-6 else None

    repaired, new_uvs = repair_quad_fluid_uv(verts, uvs, normal, force, min_slope_threshold)
    if repaired:
        for li, (u, v) in zip(loop_indices, new_uvs):
            uv_layer.data[li].uv.x = u
            uv_layer.data[li].uv.y = v
        return True

    return False


def process_mesh_fluid_uv_repairs(
    bm,
    uv_layer=None,
    target_faces: Optional[Sequence] = None,
    force: bool = False,
    min_slope_threshold: float = 0.005,
) -> int:
    """
    Repair fluid UV inversions across target faces or the entire mesh.

    :param bm: bmesh object.
    :param uv_layer: bmesh loop UV layer. If None, active UV layer is used.
    :param target_faces: Specific faces to process. If None, all faces in bm.faces are processed.
    :param force: Force swap on target faces even if slope inversion test is borderline.
    :param min_slope_threshold: Minimum height difference between top two vertices.
    :return: Number of faces successfully repaired.
    """
    if bm is None:
        return 0

    if uv_layer is None:
        uv_layer = bm.loops.layers.uv.verify()

    faces_to_process = target_faces if target_faces is not None else bm.faces
    repaired_count = 0

    for face in faces_to_process:
        if repair_face_fluid_uv(face, uv_layer, force=force, min_slope_threshold=min_slope_threshold):
            repaired_count += 1

    return repaired_count
