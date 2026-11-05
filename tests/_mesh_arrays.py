"""NumPy helpers for native MeshData buffers and simple test meshes."""

from __future__ import annotations

import numpy as np


def positions(mesh):
    return np.frombuffer(mesh.positions_memoryview(), dtype=np.float32).tolist()


def normals(mesh):
    return np.frombuffer(mesh.normals_memoryview(), dtype=np.float32).tolist()


def uvs(mesh):
    return np.frombuffer(mesh.uvs_memoryview(), dtype=np.float32).tolist()


def loop_uvs(mesh):
    return np.frombuffer(mesh.loop_uvs_memoryview(), dtype=np.float32).tolist()


def indices(mesh):
    return np.frombuffer(mesh.indices_memoryview(), dtype=np.uint32).tolist()


def quad_indices(mesh):
    mv = mesh.quad_indices_memoryview()
    if mv is None:
        return []
    return np.frombuffer(mv, dtype=np.uint32).tolist()


def face_materials(mesh):
    mv = mesh.face_materials_memoryview()
    if mv is None:
        return []
    return np.frombuffer(mv, dtype=np.uint16).tolist()


def mesh_from_quads(positions_flat, quads, quad_uvs, materials=None, normals_flat=None):
    """Builds a quad MeshData from shared vertices and per-quad loop UVs."""
    import libmtk_py

    starts = []
    totals = []
    loop_vertices = []
    loop_uvs_flat = []
    cursor = 0
    for quad, uv in zip(quads, quad_uvs):
        if len(quad) != 4 or len(uv) != 4:
            raise ValueError("mesh_from_quads expects four vertices/UVs per quad")
        starts.append(cursor)
        totals.append(4)
        loop_vertices.extend(int(v) for v in quad)
        for u, v in uv:
            loop_uvs_flat.extend((float(u), float(v)))
        cursor += 4
    mats = list(materials) if materials is not None else [0] * len(quads)
    return libmtk_py.MeshData.from_flat_polygons(
        positions_flat,
        loop_vertices,
        loop_uvs_flat,
        starts,
        totals,
        normals_flat,
        mats,
    )


def unit_quad(material=0):
    return mesh_from_quads(
        [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0],
        [[0, 1, 2, 3]],
        [[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]],
        [material],
    )


def unit_quads(count, material=0):
    positions_list = []
    quads_list = []
    uvs_list = []
    mats_list = []
    for i in range(count):
        base_v = i * 4
        positions_list.extend([0.0, float(i), 0.0, 1.0, float(i), 0.0, 1.0, float(i) + 1.0, 0.0, 0.0, float(i) + 1.0, 0.0])
        quads_list.append([base_v, base_v + 1, base_v + 2, base_v + 3])
        uvs_list.append([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        mats_list.append(material)
    return mesh_from_quads(positions_list, quads_list, uvs_list, mats_list)
