"""
Random Extrude Core Utility Module for MoziToolKit.

Accelerated via Rust libmtk Data In, Data Out architecture.
"""

from typing import Tuple

try:
    from ...bridge.extrude import process_random_extrude_mesh_batch
except (ImportError, ValueError):
    from bridge.extrude import process_random_extrude_mesh_batch


def process_random_extrude(
    bm,
    min_height: float = 0.0,
    max_height: float = 0.1,
    seed: int = 0,
    noise_mode: str = "RANDOM",
    noise_scale: float = 1.0,
    repair_uv: bool = True,
    uv_mode: str = "SMART",
    add_crease: bool = False,
    crease_val: float = 1.0,
    obj=None,
    context=None,
) -> Tuple[int, int]:
    """
    Extrude selected faces individually along their face normals with random heights,
    and optionally repair extruded side face UVs and edge creases.

    Noise generation and batch UV repair are performed via Rust libmtk.
    """
    return process_random_extrude_mesh_batch(
        bm=bm,
        min_height=min_height,
        max_height=max_height,
        seed=seed,
        noise_mode=noise_mode,
        noise_scale=noise_scale,
        repair_uv=repair_uv,
        uv_mode=uv_mode,
        add_crease=add_crease,
        crease_val=crease_val,
        obj=obj,
        context=context,
    )
