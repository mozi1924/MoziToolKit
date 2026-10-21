"""
Tests for Rust-accelerated hard and sharp edge topology analysis bridge.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock
import numpy as np

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
libmtk_release_path = PROJECT_DIR.parent / "libmozitoolkit" / "target" / "release"

for p in [str(libmtk_release_path), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

if "bpy" not in sys.modules:
    sys.modules["bpy"] = MagicMock()
if "mathutils" not in sys.modules:
    sys.modules["mathutils"] = MagicMock()

from MoziToolKit.bridge.mesh.topology import analyze_mesh_hard_edges
from MoziToolKit.bridge.engine import has_libmtk


class MockMeshAttribute:
    def __init__(self, data, count=None):
        self.data = data
        self._count = count if count is not None else len(data)

    def __len__(self):
        return self._count

    def foreach_get(self, attr, target):
        target[:] = np.asarray(self.data, dtype=target.dtype)


class MockBlenderMesh:
    def __init__(self, positions, edge_verts, loop_starts, loop_totals, loop_verts):
        self.vertices = MockMeshAttribute(positions, len(positions) // 3)
        self.edges = MockMeshAttribute(edge_verts, len(edge_verts) // 2)
        self.loops = MockMeshAttribute(loop_verts, len(loop_verts))
        self.polygons = MagicMock()
        self.polygons.__len__.return_value = len(loop_starts)
        
        def _poly_foreach_get(attr, target):
            if attr == "loop_start":
                target[:] = np.asarray(loop_starts, dtype=target.dtype)
            elif attr == "loop_total":
                target[:] = np.asarray(loop_totals, dtype=target.dtype)
        self.polygons.foreach_get = _poly_foreach_get


class TestHardEdgeAnalysisBridge(unittest.TestCase):
    def setUp(self):
        if not has_libmtk():
            self.skipTest("libmtk is not available")

    def test_cube_hard_edges(self):
        # Unit cube: 8 vertices, 12 edges, 6 quad faces
        positions = [
            0.0, 0.0, 0.0,  # 0
            1.0, 0.0, 0.0,  # 1
            1.0, 1.0, 0.0,  # 2
            0.0, 1.0, 0.0,  # 3
            0.0, 0.0, 1.0,  # 4
            1.0, 0.0, 1.0,  # 5
            1.0, 1.0, 1.0,  # 6
            0.0, 1.0, 1.0,  # 7
        ]
        edge_verts = [
            0, 1, 1, 2, 2, 3, 3, 0,  # bottom 0..3
            4, 5, 5, 6, 6, 7, 7, 4,  # top 4..7
            0, 4, 1, 5, 2, 6, 3, 7,  # pillars 8..11
        ]
        loop_starts = [0, 4, 8, 12, 16, 20]
        loop_totals = [4, 4, 4, 4, 4, 4]
        loop_verts = [
            0, 3, 2, 1,
            4, 5, 6, 7,
            0, 1, 5, 4,
            2, 3, 7, 6,
            0, 4, 7, 3,
            1, 2, 6, 5,
        ]

        mesh = MockBlenderMesh(positions, edge_verts, loop_starts, loop_totals, loop_verts)

        # 30 degrees threshold (90 degree cube edges must all be hard)
        mask = analyze_mesh_hard_edges(mesh, sharp_angle_rad=np.radians(30.0))
        self.assertIsNotNone(mask)
        self.assertEqual(len(mask), 12)
        self.assertTrue(np.all(mask == 1))

        # 100 degrees threshold (90 degree cube edges must all be smooth)
        mask_smooth = analyze_mesh_hard_edges(mesh, sharp_angle_rad=np.radians(100.0))
        self.assertIsNotNone(mask_smooth)
        self.assertEqual(len(mask_smooth), 12)
        self.assertTrue(np.all(mask_smooth == 0))

    def test_coplanar_quads_shared_edge(self):
        # 2 coplanar quads: shared edge 0 is smooth, others are boundary (hard)
        positions = [
            0.0, 0.0, 0.0,  # 0
            1.0, 0.0, 0.0,  # 1
            1.0, 1.0, 0.0,  # 2
            0.0, 1.0, 0.0,  # 3
            2.0, 0.0, 0.0,  # 4
            2.0, 1.0, 0.0,  # 5
        ]
        edge_verts = [
            1, 2,  # 0: Shared internal edge
            0, 1,  # 1: Boundary
            2, 3,  # 2: Boundary
            3, 0,  # 3: Boundary
            1, 4,  # 4: Boundary
            4, 5,  # 5: Boundary
            5, 2,  # 6: Boundary
        ]
        loop_starts = [0, 4]
        loop_totals = [4, 4]
        loop_verts = [
            0, 1, 2, 3,
            1, 4, 5, 2,
        ]

        mesh = MockBlenderMesh(positions, edge_verts, loop_starts, loop_totals, loop_verts)
        mask = analyze_mesh_hard_edges(mesh, sharp_angle_rad=np.radians(30.0))
        self.assertIsNotNone(mask)
        self.assertEqual(len(mask), 7)
        self.assertEqual(mask[0], 0, "Internal coplanar edge must be smooth")
        self.assertTrue(np.all(mask[1:] == 1), "Boundary edges must be hard")


if __name__ == "__main__":
    unittest.main()
