"""
MoziToolKit Extrude & UV Repair Bridge Module.

Accelerated extruded side UV geometric reconstruction and 3D noise generation
backed strictly by Rust libmtk (libmtk_py).
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

try:
    import libmtk_py as mtk_py
except ImportError:
    try:
        import mtk_py
    except ImportError:
        mtk_py = None

if mtk_py is None:
    raise ImportError(
        "libmtk_py native extension is missing. Please install the compiled extension wheel."
    )


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
    adj = list(adjacent_uv_strip) if adjacent_uv_strip is not None else None
    return mtk_py.repair_extruded_side_uv(
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
    pts = [tuple(c) for c in centers]
    return mtk_py.generate_random_extrude_heights(
        pts, noise_type, min_height, max_height, noise_scale, seed, discrete_steps
    )
