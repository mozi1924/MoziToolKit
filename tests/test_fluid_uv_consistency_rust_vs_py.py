"""
Test Suite for Fluid UV Bridge and Algorithms backed by libmtk_py.
Validates sloped quad repair, Z-up / Y-up detection, top/side UV generation,
and Blender BMesh repair execution.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
libmtk_release_path = PROJECT_DIR.parent / "libmozitoolkit" / "target" / "release"

if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
if str(libmtk_release_path) not in sys.path:
    sys.path.insert(0, str(libmtk_release_path))


try:
    import bpy
    import bmesh
    from mathutils import Vector
except ImportError:
    bpy = None
    bmesh = None
    Vector = None

from bridge.uv import (
    repair_quad_fluid_uv,
    batch_repair_fluid_uv,
    get_fluid_top_uvs,
    get_fluid_side_uvs,
)
from utils.mesh.fluid_uv import repair_face_fluid_uv, process_mesh_fluid_uv_repairs


class TestFluidUVBridge(unittest.TestCase):
    def test_single_inverted_quad_z_up(self):
        """Test Z-up sloped quad face where top UV heights are inverted."""
        verts = [
            (0.0, 1.0, 0.0),  # v0
            (0.0, 0.0, 0.0),  # v1
            (0.0, 0.0, 0.2),  # v2: top left (low: 0.2)
            (0.0, 1.0, 0.8),  # v3: top right (high: 0.8)
        ]
        inverted_uvs = [
            (1.0, 0.0),
            (0.0, 0.0),
            (0.0, 0.8),  # Inverted: should be 0.2
            (1.0, 0.2),  # Inverted: should be 0.8
        ]

        repaired, out_uvs = repair_quad_fluid_uv(verts, inverted_uvs)
        self.assertTrue(repaired)
        self.assertAlmostEqual(out_uvs[2][1], 0.2, places=5)
        self.assertAlmostEqual(out_uvs[3][1], 0.8, places=5)

    def test_single_inverted_quad_y_up(self):
        """Test Y-up (Minecraft OBJ convention) sloped quad face."""
        verts = [
            (1.0, 0.0, 0.0),  # Bottom right
            (0.0, 0.0, 0.0),  # Bottom left
            (0.0, 0.2, 0.0),  # Top left (low: 0.2)
            (1.0, 0.8, 0.0),  # Top right (high: 0.8)
        ]
        inverted_uvs = [
            (1.0, 0.0),
            (0.0, 0.0),
            (0.0, 0.8),  # Inverted
            (1.0, 0.2),  # Inverted
        ]

        repaired, out_uvs = repair_quad_fluid_uv(verts, inverted_uvs)
        self.assertTrue(repaired)
        self.assertAlmostEqual(out_uvs[2][1], 0.2, places=5)
        self.assertAlmostEqual(out_uvs[3][1], 0.8, places=5)

    def test_non_inverted_face(self):
        """Non-inverted face should not be modified."""
        verts = [
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 0.2),
            (0.0, 1.0, 0.8),
        ]
        correct_uvs = [
            (1.0, 0.0),
            (0.0, 0.0),
            (0.0, 0.2),
            (1.0, 0.8),
        ]

        repaired, out_uvs = repair_quad_fluid_uv(verts, correct_uvs, force=False)
        self.assertFalse(repaired)
        self.assertAlmostEqual(out_uvs[2][1], 0.2, places=5)
        self.assertAlmostEqual(out_uvs[3][1], 0.8, places=5)

    def test_top_uvs_generation_and_rotation(self):
        # Flowing top with 0 rotation
        top_0 = get_fluid_top_uvs(is_flowing=True, rotation=0.0)
        self.assertEqual(len(top_0), 4)
        self.assertAlmostEqual(top_0[0][0], 0.25, places=5)
        self.assertAlmostEqual(top_0[0][1], 0.25, places=5)
        self.assertAlmostEqual(top_0[2][0], 0.75, places=5)
        self.assertAlmostEqual(top_0[2][1], 0.75, places=5)

        # Still pool
        still = get_fluid_top_uvs(is_flowing=False)
        self.assertEqual(still[0], (0.0, 0.0))
        self.assertEqual(still[2], (1.0, 1.0))

    def test_side_uvs_generation(self):
        side = get_fluid_side_uvs(0.8, 0.2)
        self.assertEqual(len(side), 4)
        self.assertAlmostEqual(side[0][1], (1.0 - 0.8) * 0.5, places=5)
        self.assertAlmostEqual(side[3][1], (1.0 - 0.2) * 0.5, places=5)

    def test_batch_repair_fluid_uv(self):
        verts_flat = []
        uvs_flat = []
        expected_repaired = 0

        for i in range(100):
            is_inv = (i % 2 == 0)
            verts_flat.extend([
                0.0, 1.0, 0.0,
                0.0, 0.0, 0.0,
                0.0, 0.0, 0.2,
                0.0, 1.0, 0.8,
            ])
            if is_inv:
                uvs_flat.extend([
                    1.0, 0.0,
                    0.0, 0.0,
                    0.0, 0.8,
                    1.0, 0.2,
                ])
                expected_repaired += 1
            else:
                uvs_flat.extend([
                    1.0, 0.0,
                    0.0, 0.0,
                    0.0, 0.2,
                    1.0, 0.8,
                ])

        count, out_uvs = batch_repair_fluid_uv(verts_flat, uvs_flat)
        self.assertEqual(count, expected_repaired)
        self.assertEqual(len(out_uvs), len(uvs_flat))


@unittest.skipIf(bpy is None, "Blender environment not available")
class TestFluidUVBlenderBMesh(unittest.TestCase):
    def setUp(self):
        self.mesh = bpy.data.meshes.new("TestFluidBMesh")
        self.bm = bmesh.new()
        self.uv_layer = self.bm.loops.layers.uv.new("UVMap")

    def tearDown(self):
        self.bm.free()
        if self.mesh.name in bpy.data.meshes:
            bpy.data.meshes.remove(self.mesh)

    def test_bmesh_repair_face_fluid_uv(self):
        v0 = self.bm.verts.new(Vector((0.0, 0.0, 1.0)))
        v1 = self.bm.verts.new(Vector((0.0, 0.0, 0.0)))
        v2 = self.bm.verts.new(Vector((0.0, 0.2, 0.0)))
        v3 = self.bm.verts.new(Vector((0.0, 0.8, 1.0)))
        face = self.bm.faces.new([v0, v1, v2, v3])
        self.bm.faces.ensure_lookup_table()

        loops = list(face.loops)
        loops[0][self.uv_layer].uv = Vector((1.0, 0.0))
        loops[1][self.uv_layer].uv = Vector((0.0, 0.0))
        loops[2][self.uv_layer].uv = Vector((0.0, 0.8))  # Inverted
        loops[3][self.uv_layer].uv = Vector((1.0, 0.2))  # Inverted

        repaired = repair_face_fluid_uv(face, self.uv_layer)
        self.assertTrue(repaired)
        self.assertAlmostEqual(loops[2][self.uv_layer].uv.y, 0.2, places=4)
        self.assertAlmostEqual(loops[3][self.uv_layer].uv.y, 0.8, places=4)


if __name__ == "__main__":
    if "--" in sys.argv:
        argv = [sys.argv[0]] + sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = [sys.argv[0]]
    unittest.main(argv=argv)
