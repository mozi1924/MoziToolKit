"""
Fluid UV repair utilities.

Fixes inverted UV heights on Minecraft fluid quad faces (e.g. water, lava flowing
slopes where the top two vertices have their UV V coordinates inverted relative
to their 3D heights).
Accelerated by Rust libmtk (batch_repair_fluid_uv) with zero-copy batch processing.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

import numpy as np

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
        batch_repair_fluid_uv,
        get_fluid_top_uvs,
        get_fluid_side_uvs,
    )
except (ImportError, ValueError):
    from bridge.uv import (
        repair_quad_fluid_uv,
        batch_repair_fluid_uv,
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


def _process_bmesh_fluid_uv_repairs(
    bm,
    uv_layer,
    target_faces: Optional[Sequence] = None,
    force: bool = False,
    min_slope_threshold: float = 0.005,
) -> int:
    """
    Batch repair fluid UVs on a BMesh using Rust batch_repair_fluid_uv.
    """
    faces_to_process = target_faces if target_faces is not None else bm.faces
    # Only 4-vertex quads can have fluid slope repairs
    quad_faces = [f for f in faces_to_process if len(f.verts) == 4]
    num_faces = len(quad_faces)
    if num_faces == 0:
        return 0

    verts_flat = np.empty(num_faces * 12, dtype=np.float32)
    uvs_flat = np.empty(num_faces * 8, dtype=np.float32)
    normals_flat = np.empty(num_faces * 3, dtype=np.float32)

    face_loops = []
    v_idx = 0
    uv_idx = 0
    n_idx = 0

    for f in quad_faces:
        loops = list(f.loops)
        face_loops.append(loops)
        fnorm = f.normal
        normals_flat[n_idx] = fnorm.x
        normals_flat[n_idx + 1] = fnorm.y
        normals_flat[n_idx + 2] = fnorm.z
        n_idx += 3

        for l in loops:
            co = l.vert.co
            verts_flat[v_idx] = co.x
            verts_flat[v_idx + 1] = co.y
            verts_flat[v_idx + 2] = co.z
            v_idx += 3

            uv = l[uv_layer].uv
            uvs_flat[uv_idx] = uv.x
            uvs_flat[uv_idx + 1] = uv.y
            uv_idx += 2

    orig_v = uvs_flat[1::2].copy()

    repaired_count, uvs_flat = batch_repair_fluid_uv(
        verts_flat,
        uvs_flat,
        normals_flat,
        force=force,
        min_slope_threshold=min_slope_threshold,
    )

    if repaired_count == 0:
        return 0

    # Determine which faces actually changed and update only those loops
    changed_loops = np.where(uvs_flat[1::2] != orig_v)[0]
    changed_faces = np.unique(changed_loops // 4)

    for fi in changed_faces:
        loops = face_loops[fi]
        base_uv = int(fi) * 8
        loops[0][uv_layer].uv.y = float(uvs_flat[base_uv + 1])
        loops[1][uv_layer].uv.y = float(uvs_flat[base_uv + 3])
        loops[2][uv_layer].uv.y = float(uvs_flat[base_uv + 5])
        loops[3][uv_layer].uv.y = float(uvs_flat[base_uv + 7])

    return repaired_count


def _process_raw_mesh_fluid_uv_repairs(
    mesh,
    uv_layer=None,
    target_faces: Optional[Sequence] = None,
    force: bool = False,
    min_slope_threshold: float = 0.005,
) -> int:
    """
    High-throughput zero-copy batch fluid UV repair for standard bpy.types.Mesh
    using Blender foreach_get / foreach_set.
    """
    if mesh is None or not hasattr(mesh, "polygons") or len(mesh.polygons) == 0:
        return 0

    if uv_layer is None:
        if hasattr(mesh, "uv_layers") and mesh.uv_layers.active:
            uv_layer = mesh.uv_layers.active
        else:
            return 0

    if not hasattr(uv_layer, "data") or len(uv_layer.data) == 0:
        return 0

    num_polys = len(mesh.polygons)
    num_loops = len(mesh.loops)
    num_verts = len(mesh.vertices)

    poly_totals = np.empty(num_polys, dtype=np.int32)
    mesh.polygons.foreach_get("loop_total", poly_totals)

    if target_faces is not None:
        target_indices = np.array(
            [f.index if hasattr(f, "index") else int(f) for f in target_faces],
            dtype=np.int32,
        )
        quad_mask = poly_totals[target_indices] == 4
        quad_indices = target_indices[quad_mask]
    else:
        quad_indices = np.where(poly_totals == 4)[0]

    if len(quad_indices) == 0:
        return 0

    poly_starts = np.empty(num_polys, dtype=np.int32)
    mesh.polygons.foreach_get("loop_start", poly_starts)

    quad_starts = poly_starts[quad_indices]
    quad_loop_indices = (quad_starts[:, None] + np.arange(4, dtype=np.int32)).ravel()

    loop_v_indices = np.empty(num_loops, dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loop_v_indices)

    vert_cos = np.empty(num_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", vert_cos)
    vert_cos_reshaped = vert_cos.reshape(-1, 3)

    quad_v_indices = loop_v_indices[quad_loop_indices]
    verts_flat = vert_cos_reshaped[quad_v_indices].ravel()

    normals_all = np.empty(num_polys * 3, dtype=np.float32)
    mesh.polygons.foreach_get("normal", normals_all)
    normals_flat = normals_all.reshape(-1, 3)[quad_indices].ravel()

    all_uvs = np.empty(num_loops * 2, dtype=np.float32)
    uv_layer.data.foreach_get("uv", all_uvs)
    all_uvs_reshaped = all_uvs.reshape(-1, 2)
    uvs_flat = all_uvs_reshaped[quad_loop_indices].ravel().copy()

    repaired_count, repaired_uvs = batch_repair_fluid_uv(
        verts_flat,
        uvs_flat,
        normals_flat,
        force=force,
        min_slope_threshold=min_slope_threshold,
    )

    if repaired_count > 0:
        all_uvs_reshaped[quad_loop_indices] = np.asarray(repaired_uvs, dtype=np.float32).reshape(-1, 2)
        uv_layer.data.foreach_set("uv", all_uvs.ravel())
        if hasattr(mesh, "update"):
            mesh.update()

    return repaired_count


def process_bmesh_fluid_uv_repairs(
    bm,
    uv_layer=None,
    target_faces: Optional[Sequence] = None,
    force: bool = False,
    min_slope_threshold: float = 0.005,
) -> int:
    """Explicit BMesh batch fluid UV repair entry point."""
    if bm is None:
        return 0
    if uv_layer is None:
        uv_layer = bm.loops.layers.uv.verify()
    return _process_bmesh_fluid_uv_repairs(
        bm,
        uv_layer=uv_layer,
        target_faces=target_faces,
        force=force,
        min_slope_threshold=min_slope_threshold,
    )


def process_raw_mesh_fluid_uv_repairs(
    mesh,
    uv_layer=None,
    target_faces: Optional[Sequence] = None,
    force: bool = False,
    min_slope_threshold: float = 0.005,
) -> int:
    """Explicit bpy.types.Mesh zero-copy batch fluid UV repair entry point."""
    return _process_raw_mesh_fluid_uv_repairs(
        mesh,
        uv_layer=uv_layer,
        target_faces=target_faces,
        force=force,
        min_slope_threshold=min_slope_threshold,
    )


def process_mesh_fluid_uv_repairs(
    bm,
    uv_layer=None,
    target_faces: Optional[Sequence] = None,
    force: bool = False,
    min_slope_threshold: float = 0.005,
) -> int:
    """
    Repair fluid UV inversions across target faces or the entire mesh.
    Supports both BMesh (bmesh.types.BMesh) and standard Blender Mesh (bpy.types.Mesh)
    with accelerated zero-copy batch processing backed by Rust libmtk (batch_repair_fluid_uv).

    :param bm: bmesh or bpy.types.Mesh object.
    :param uv_layer: bmesh loop UV layer or mesh UV layer. If None, active UV layer is used.
    :param target_faces: Specific faces to process. If None, all faces in bm are processed.
    :param force: Force swap on target faces even if slope inversion test is borderline.
    :param min_slope_threshold: Minimum height difference between top two vertices.
    :return: Number of faces successfully repaired.
    """
    if bm is None:
        return 0

    if hasattr(bm, "polygons"):
        return _process_raw_mesh_fluid_uv_repairs(
            bm,
            uv_layer=uv_layer,
            target_faces=target_faces,
            force=force,
            min_slope_threshold=min_slope_threshold,
        )

    if uv_layer is None:
        uv_layer = bm.loops.layers.uv.verify()

    return _process_bmesh_fluid_uv_repairs(
        bm,
        uv_layer=uv_layer,
        target_faces=target_faces,
        force=force,
        min_slope_threshold=min_slope_threshold,
    )
