"""
MoziToolKit Extrude & UV Repair Bridge Module.

Accelerated extruded side UV geometric reconstruction and 3D noise generation
backed strictly by Rust libmtk (libmtk_py) using a Data In, Data Out architecture.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from .engine import get_libmtk, require_libmtk


def __getattr__(name: str) -> Any:
    if name == "mtk_py":
        return get_libmtk()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def repair_extruded_side_uv(
    uv_base_a: Tuple[float, float],
    uv_base_b: Tuple[float, float],
    top_normal: Tuple[float, float, float],
    extrude_vec: Tuple[float, float, float],
    mode: str = "SMART",
    step_u: float = 1.0 / 16.0,
    step_v: float = 1.0 / 16.0,
    top_uv_bounds: Optional[Tuple[float, float, float, float]] = None,
    adjacent_uv_strip: Optional[Sequence[Tuple[float, float]]] = None,
) -> List[Tuple[float, float]]:
    """Reconstruct 4 UV corner coordinates for an extruded side quad polygon."""
    mtk = require_libmtk("repair_extruded_side_uv")
    adj = list(adjacent_uv_strip) if adjacent_uv_strip is not None else None
    return mtk.repair_extruded_side_uv(
        tuple(uv_base_a),
        tuple(uv_base_b),
        tuple(top_normal),
        tuple(extrude_vec),
        mode,
        step_u,
        step_v,
        top_uv_bounds,
        adj,
    )


def generate_random_extrude_heights(
    centers: Sequence[Tuple[float, float, float]],
    noise_type: str = "RANDOM",
    min_height: float = 0.0,
    max_height: float = 1.0,
    noise_scale: float = 1.0,
    seed: int = 1234,
    discrete_steps: Optional[int] = None,
) -> List[float]:
    """Generate 3D noise-based random extrusion displacement heights."""
    mtk = require_libmtk("generate_random_extrude_heights")
    pts = [tuple(c) for c in centers]
    return mtk.generate_random_extrude_heights(
        pts, noise_type, min_height, max_height, noise_scale, seed, discrete_steps
    )


def process_flat_mesh_extrude_repair(
    positions: List[float],
    loop_vertices: List[int],
    loop_uvs: List[float],
    face_loop_starts: List[int],
    face_loop_totals: List[int],
    face_materials: List[int],
    selected_faces: List[int],
    pixel_steps: List[List[float]],
    uv_mode: str = "SMART",
    repair_uv: bool = True,
    add_crease: bool = False,
    crease_val: float = 1.0,
    only_collapsed: bool = False,
    smart_side_faces: Optional[List[int]] = None,
) -> Tuple[List[Tuple[int, List[Tuple[float, float]]]], List[Tuple[int, int]], List[Tuple[Tuple[int, int], float]], int]:
    """Pure Data In, Data Out backend pipeline for extrude side UV repair and crease assignment."""
    mtk = require_libmtk("process_flat_mesh_extrude_repair")
    return mtk.process_flat_mesh_extrude_repair(
        positions=positions,
        loop_vertices=loop_vertices,
        loop_uvs=loop_uvs,
        face_loop_starts=face_loop_starts,
        face_loop_totals=face_loop_totals,
        face_materials=face_materials,
        selected_faces=selected_faces,
        pixel_steps=pixel_steps,
        uv_mode=uv_mode,
        repair_uv=repair_uv,
        add_crease=add_crease,
        crease_val=crease_val,
        only_collapsed=only_collapsed,
        smart_side_faces=smart_side_faces,
    )


# Host-level BMesh and shader analysis functions are forwarded from utils.mesh.random_extrude
try:
    from ..utils.mesh.random_extrude import (
        get_face_pixel_step,
        process_random_extrude,
        process_random_extrude_mesh_batch,
        repair_extruded_side_faces,
        repair_mesh_extruded_side_faces_batch,
    )
except (ImportError, ValueError):
    from utils.mesh.random_extrude import (
        get_face_pixel_step,
        process_random_extrude,
        process_random_extrude_mesh_batch,
        repair_extruded_side_faces,
        repair_mesh_extruded_side_faces_batch,
    )

__all__ = [
    "repair_extruded_side_uv",
    "generate_random_extrude_heights",
    "process_flat_mesh_extrude_repair",
    "get_face_pixel_step",
    "repair_mesh_extruded_side_faces_batch",
    "process_random_extrude_mesh_batch",
    "repair_extruded_side_faces",
    "process_random_extrude",
]
