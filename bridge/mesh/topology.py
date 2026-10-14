"""
MoziToolKit Mesh Topology Bridge Module.

Accelerated mesh topology, dihedral angle computation, and hard edge detection
backed strictly by Rust libmtk.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from ..engine import get_libmtk, require_libmtk

logger = logging.getLogger("MoziToolKit.Bridge.Mesh.Topology")


def analyze_mesh_hard_edges(
    mesh: Any,
    sharp_angle_rad: float = 0.5235987755982988,  # ~30 degrees in radians
    explicit_sharp_edges: Optional[np.ndarray] = None,
) -> Optional[np.ndarray]:
    """
    Analyzes mesh edge sharpness using vectorized buffers and Rust libmtk core.

    :param mesh: bpy.types.Mesh instance.
    :param sharp_angle_rad: Angle in radians above which an edge is considered sharp.
    :param explicit_sharp_edges: Optional uint8/bool numpy array of length len(mesh.edges).
    :return: uint8 numpy array of length len(mesh.edges) with 1 for hard edges and 0 for smooth edges,
             or None if libmtk is not available.
    """
    mtk = require_libmtk("analyze_mesh_hard_edges")
    if not hasattr(mtk, "analyze_mesh_hard_edges"):
        return None

    num_verts = len(getattr(mesh, "vertices", []))
    num_edges = len(getattr(mesh, "edges", []))
    num_polys = len(getattr(mesh, "polygons", []))
    num_loops = len(getattr(mesh, "loops", []))

    if num_edges == 0 or num_polys == 0 or num_verts == 0:
        return np.zeros(num_edges, dtype=np.uint8)

    positions = np.empty(num_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", positions)

    edge_verts = np.empty(num_edges * 2, dtype=np.uint32)
    mesh.edges.foreach_get("vertices", edge_verts)

    loop_starts = np.empty(num_polys, dtype=np.uint32)
    mesh.polygons.foreach_get("loop_start", loop_starts)

    loop_totals = np.empty(num_polys, dtype=np.uint32)
    mesh.polygons.foreach_get("loop_total", loop_totals)

    loop_verts = np.empty(num_loops, dtype=np.uint32)
    mesh.loops.foreach_get("vertex_index", loop_verts)

    raw_bytes = mtk.analyze_mesh_hard_edges(
        positions,
        edge_verts,
        loop_starts,
        loop_totals,
        loop_verts,
        float(sharp_angle_rad),
        explicit_sharp_edges,
    )

    return np.frombuffer(raw_bytes, dtype=np.uint8)
