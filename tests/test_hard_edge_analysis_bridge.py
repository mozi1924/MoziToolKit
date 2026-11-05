"""
Tests for Rust-accelerated hard and sharp edge topology analysis bridge.
Runs 100% inside real Blender host environment with native bpy data structures.
"""

from __future__ import annotations

import unittest
import numpy as np
import bpy
import bmesh
import mathutils

from MoziToolKit.bridge.mesh.topology import analyze_mesh_hard_edges
from MoziToolKit.bridge.engine import has_libmtk


class TestHardEdgeAnalysisBridge(unittest.TestCase):
    def setUp(self):
        if not has_libmtk():
            self.skipTest("libmtk is not available")
        self._created_meshes: list[bpy.types.Mesh] = []

    def tearDown(self):
        for mesh in self._created_meshes:
            if mesh.name in bpy.data.meshes:
                bpy.data.meshes.remove(mesh)

    def test_cube_hard_edges(self):
        # Unit cube: 8 vertices, 6 quad faces
        vertices = [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
            (1.0, 0.0, 1.0),
            (1.0, 1.0, 1.0),
            (0.0, 1.0, 1.0),
        ]
        faces = [
            (0, 3, 2, 1),
            (4, 5, 6, 7),
            (0, 1, 5, 4),
            (2, 3, 7, 6),
            (0, 4, 7, 3),
            (1, 2, 6, 5),
        ]

        mesh = bpy.data.meshes.new("test_real_cube")
        self._created_meshes.append(mesh)
        mesh.from_pydata(vertices, [], faces)
        mesh.update()

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
        # 2 coplanar quads sharing vertices 1 and 2
        vertices = [
            (0.0, 0.0, 0.0),  # 0
            (1.0, 0.0, 0.0),  # 1
            (1.0, 1.0, 0.0),  # 2
            (0.0, 1.0, 0.0),  # 3
            (2.0, 0.0, 0.0),  # 4
            (2.0, 1.0, 0.0),  # 5
        ]
        faces = [
            (0, 1, 2, 3),
            (1, 4, 5, 2),
        ]

        mesh = bpy.data.meshes.new("test_real_coplanar")
        self._created_meshes.append(mesh)
        mesh.from_pydata(vertices, [], faces)
        mesh.update()

        mask = analyze_mesh_hard_edges(mesh, sharp_angle_rad=np.radians(30.0))
        self.assertIsNotNone(mask)
        self.assertEqual(len(mask), 7)

        # Locate the shared edge between vert 1 and vert 2
        shared_edge_idx = None
        for i, edge in enumerate(mesh.edges):
            v_pair = set(edge.vertices)
            if v_pair == {1, 2}:
                shared_edge_idx = i
                break
        self.assertIsNotNone(shared_edge_idx, "Shared edge between (1, 2) must exist")

        self.assertEqual(mask[shared_edge_idx], 0, "Internal coplanar edge must be smooth")
        boundary_indices = [i for i in range(7) if i != shared_edge_idx]
        self.assertTrue(np.all(mask[boundary_indices] == 1), "Boundary edges must be hard")


if __name__ == "__main__":
    unittest.main()
