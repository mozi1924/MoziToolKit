"""
MoziToolKit Mesh Face Culling Bridge Module.

Accelerated spatial face occlusion culling backed strictly by Rust libmtk (libmtk_py).
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

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


def cull_mesh_faces(
    mesh_data: mtk_py.MeshData,
    tolerance: float = 1e-3,
    cull_coplanar_opposite: bool = True,
    cull_duplicates: bool = True,
) -> Tuple[mtk_py.MeshData, Dict[str, Any]]:
    """Cull interior contacting faces and duplicate polygons from a MeshData buffer."""
    return mtk_py.cull_mesh_faces(
        mesh_data, tolerance, cull_coplanar_opposite, cull_duplicates
    )
