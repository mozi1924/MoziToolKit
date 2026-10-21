"""
MoziToolKit Mesh Face Culling Bridge Module.

Accelerated spatial face occlusion culling backed strictly by Rust libmtk (libmtk_py).
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from .engine import get_libmtk, require_libmtk


def __getattr__(name: str) -> Any:
    if name == "mtk_py":
        return get_libmtk()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def cull_mesh_faces(
    mesh_data: Any,
    tolerance: float = 1e-3,
    cull_coplanar_opposite: bool = True,
    cull_duplicates: bool = True,
) -> Tuple[Any, Dict[str, Any]]:
    """Cull interior contacting faces and duplicate polygons from a MeshData buffer."""
    mtk = require_libmtk("cull_mesh_faces")
    culled_mesh, stats = mtk.cull_mesh_faces(
        mesh_data, tolerance, cull_coplanar_opposite, cull_duplicates
    )
    if getattr(culled_mesh, "profile", None) is not None:
        try:
            from ..dev.profile_tracker import record_operation_profile
            record_operation_profile("Cull Mesh Faces", culled_mesh.profile)
        except Exception:
            pass
    return culled_mesh, stats
