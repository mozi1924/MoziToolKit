"""
Fluid UV repair utilities.

Fixes inverted UV heights on Minecraft fluid quad faces (e.g. water, lava flowing
slopes where the top two vertices have their UV V coordinates inverted relative
to their 3D heights).
Accelerated by Rust libmtk (repair_mesh_fluid_uv_inplace) with zero-copy batch processing.
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

from ...bridge.uv import (
    repair_mesh_fluid_uv_inplace,
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
    """Check and repair inverted fluid UV on a single BMesh quad face."""
    if face is None or uv_layer is None or len(face.verts) != 4:
        return False

    loops = list(face.loops)
    positions = np.empty(12, dtype=np.float32)
    uvs = np.empty(8, dtype=np.float32)
    for i, l in enumerate(loops):
        positions[i * 3 : i * 3 + 3] = (l.vert.co.x, l.vert.co.y, l.vert.co.z)
        uvs[i * 2 : i * 2 + 2] = (l[uv_layer].uv.x, l[uv_layer].uv.y)

    orig_v = uvs[1::2].copy()
    count = repair_mesh_fluid_uv_inplace(
        positions=positions,
        loop_verts=np.arange(4, dtype=np.uint32),
        face_loop_starts=np.array([0], dtype=np.uint32),
        face_loop_totals=np.array([4], dtype=np.uint32),
        uvs=uvs,
        force=force,
        min_slope_threshold=min_slope_threshold,
    )
    if count > 0:
        for i, l in enumerate(loops):
            if uvs[i * 2 + 1] != orig_v[i]:
                l[uv_layer].uv.y = float(uvs[i * 2 + 1])
        return True
    return False


def repair_polygon_fluid_uv(
    polygon,
    mesh,
    uv_layer,
    force: bool = False,
    min_slope_threshold: float = 0.005,
) -> bool:
    """Repair inverted fluid UV on a standard bpy.types.MeshPolygon."""
    if polygon is None or mesh is None or uv_layer is None or len(polygon.loop_indices) != 4:
        return False
    return _process_raw_mesh_fluid_uv_repairs(
        mesh,
        uv_layer=uv_layer,
        target_faces=[polygon],
        force=force,
        min_slope_threshold=min_slope_threshold,
    ) > 0


def _process_bmesh_fluid_uv_repairs(
    bm,
    uv_layer,
    target_faces: Optional[Sequence] = None,
    force: bool = False,
    min_slope_threshold: float = 0.005,
) -> int:
    """
    Batch repair fluid UVs on a BMesh using Rust repair_mesh_fluid_uv_inplace.
    """
    faces_to_process = target_faces if target_faces is not None else bm.faces
    # Only 4-vertex quads can have fluid slope repairs
    quad_faces = [f for f in faces_to_process if len(f.verts) == 4]
    num_faces = len(quad_faces)
    if num_faces == 0:
        return 0

    verts_flat = np.empty(num_faces * 12, dtype=np.float32)
    uvs_flat = np.empty(num_faces * 8, dtype=np.float32)

    face_loops = []
    v_idx = 0
    uv_idx = 0

    for f in quad_faces:
        loops = list(f.loops)
        face_loops.append(loops)
        for l in loops:
            co = l.vert.co
            verts_flat[v_idx : v_idx + 3] = (co.x, co.y, co.z)
            v_idx += 3

            uv = l[uv_layer].uv
            uvs_flat[uv_idx : uv_idx + 2] = (uv.x, uv.y)
            uv_idx += 2

    orig_v = uvs_flat[1::2].copy()

    loop_verts = np.arange(num_faces * 4, dtype=np.uint32)
    face_starts = np.arange(0, num_faces * 4, 4, dtype=np.uint32)
    face_totals = np.full(num_faces, 4, dtype=np.uint32)

    repaired_count = repair_mesh_fluid_uv_inplace(
        positions=verts_flat,
        loop_verts=loop_verts,
        face_loop_starts=face_starts,
        face_loop_totals=face_totals,
        uvs=uvs_flat,
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
    using Blender foreach_get / foreach_set and Rust repair_mesh_fluid_uv_inplace.
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

    positions = np.empty(num_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", positions)

    loop_verts = np.empty(num_loops, dtype=np.uint32)
    mesh.loops.foreach_get("vertex_index", loop_verts)

    loop_starts = np.empty(num_polys, dtype=np.uint32)
    mesh.polygons.foreach_get("loop_start", loop_starts)

    loop_totals = np.empty(num_polys, dtype=np.uint32)
    mesh.polygons.foreach_get("loop_total", loop_totals)

    uvs = np.empty(num_loops * 2, dtype=np.float32)
    uv_layer.data.foreach_get("uv", uvs)

    face_indices = None
    if target_faces is not None:
        face_indices = np.array(
            [f.index if hasattr(f, "index") else int(f) for f in target_faces],
            dtype=np.uint32,
        )

    repaired_count = repair_mesh_fluid_uv_inplace(
        positions=positions,
        loop_verts=loop_verts,
        face_loop_starts=loop_starts,
        face_loop_totals=loop_totals,
        uvs=uvs,
        face_indices=face_indices,
        force=force,
        min_slope_threshold=min_slope_threshold,
    )

    if repaired_count > 0:
        uv_layer.data.foreach_set("uv", uvs)
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
    with accelerated zero-copy batch processing backed by Rust libmtk (repair_mesh_fluid_uv_inplace).

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
