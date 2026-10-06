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
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


try:
    from unittest.mock import MagicMock
    import bpy
    import bmesh
    from mathutils import Vector
    HAS_REAL_BPY = (
        bpy is not None
        and not isinstance(bpy, MagicMock)
        and hasattr(bpy, "data")
        and hasattr(bpy.data, "meshes")
    )
except ImportError:
    bpy = None
    bmesh = None
    Vector = None
    HAS_REAL_BPY = False

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

    def test_batch_repair_numpy_and_array_zero_copy(self):
        """Test that batch_repair_fluid_uv supports both array.array and numpy ndarrays."""
        import array
        verts = array.array("f", [
            0.0, 1.0, 0.0,
            0.0, 0.0, 0.0,
            0.0, 0.0, 0.2,
            0.0, 1.0, 0.8,
        ])
        uvs = array.array("f", [
            1.0, 0.0,
            0.0, 0.0,
            0.0, 0.8,  # Inverted
            1.0, 0.2,  # Inverted
        ])
        count, out_uvs = batch_repair_fluid_uv(verts, uvs)
        self.assertEqual(count, 1)
        self.assertAlmostEqual(uvs[5], 0.2, places=5)
        self.assertAlmostEqual(uvs[7], 0.8, places=5)

        try:
            import numpy as np
            np_verts = np.array([
                0.0, 1.0, 0.0,
                0.0, 0.0, 0.0,
                0.0, 0.0, 0.2,
                0.0, 1.0, 0.8,
            ], dtype=np.float32)
            np_uvs = np.array([
                1.0, 0.0,
                0.0, 0.0,
                0.0, 0.8,
                1.0, 0.2,
            ], dtype=np.float32)
            np_count, np_out = batch_repair_fluid_uv(np_verts, np_uvs)
            self.assertEqual(np_count, 1)
            # Verify in-place mutation
            self.assertAlmostEqual(float(np_uvs[5]), 0.2, places=5)
            self.assertAlmostEqual(float(np_uvs[7]), 0.8, places=5)
        except ImportError:
            pass


@unittest.skipIf(not HAS_REAL_BPY, "Blender environment not available")
class TestFluidUVBlenderBMesh(unittest.TestCase):
    def setUp(self):
        self.mesh = bpy.data.meshes.new("TestFluidBMesh")
        self.bm = bmesh.new()
        self.uv_layer = self.bm.loops.layers.uv.new("UVMap")

    def tearDown(self):
        self.bm.free()
        if self.mesh.name in bpy.data.meshes:
            bpy.data.meshes.remove(self.mesh)

    def _create_quad_face(self, bm, z_left, z_right, uv_v_left, uv_v_right, x_offset=0.0):
        v0 = bm.verts.new(Vector((x_offset + 0.0, 1.0, 0.0)))
        v1 = bm.verts.new(Vector((x_offset + 0.0, 0.0, 0.0)))
        v2 = bm.verts.new(Vector((x_offset + 0.0, 0.0, z_left)))
        v3 = bm.verts.new(Vector((x_offset + 0.0, 1.0, z_right)))
        face = bm.faces.new([v0, v1, v2, v3])
        return face, [
            Vector((1.0, 0.0)),
            Vector((0.0, 0.0)),
            Vector((0.0, uv_v_left)),
            Vector((1.0, uv_v_right)),
        ]

    def test_bmesh_repair_face_fluid_uv(self):
        face, init_uvs = self._create_quad_face(self.bm, 0.2, 0.8, 0.8, 0.2)
        self.bm.faces.ensure_lookup_table()

        loops = list(face.loops)
        for l, uv in zip(loops, init_uvs):
            l[self.uv_layer].uv = uv

        repaired = repair_face_fluid_uv(face, self.uv_layer)
        self.assertTrue(repaired)
        self.assertAlmostEqual(loops[2][self.uv_layer].uv.y, 0.2, places=4)
        self.assertAlmostEqual(loops[3][self.uv_layer].uv.y, 0.8, places=4)

    def test_bmesh_batch_process_vs_individual_repair_strict_parity(self):
        """
        Create 2 identical BMesh meshes with 30 diverse faces (inverted, non-inverted, flat).
        Process bm1 face-by-face (legacy) and bm2 via batch_repair_fluid_uv.
        Verify that 100% of face UVs match down to the exact float precision!
        """
        bm_legacy = bmesh.new()
        uv_layer_legacy = bm_legacy.loops.layers.uv.new("UVMap")

        bm_batch = bmesh.new()
        uv_layer_batch = bm_batch.loops.layers.uv.new("UVMap")

        try:
            # Generate 30 diverse quad faces
            for i in range(30):
                x_off = float(i) * 2.0
                is_inverted = (i % 2 == 0)
                is_slanted = (i % 3 != 0)

                z_l = 0.2 if is_slanted else 0.5
                z_r = 0.8 if is_slanted else 0.5

                if is_inverted and is_slanted:
                    uv_vl, uv_vr = 0.8, 0.2
                else:
                    uv_vl, uv_vr = 0.2, 0.8

                f1, uvs1 = self._create_quad_face(bm_legacy, z_l, z_r, uv_vl, uv_vr, x_off)
                for l, uv in zip(f1.loops, uvs1):
                    l[uv_layer_legacy].uv = uv

                f2, uvs2 = self._create_quad_face(bm_batch, z_l, z_r, uv_vl, uv_vr, x_off)
                for l, uv in zip(f2.loops, uvs2):
                    l[uv_layer_batch].uv = uv

            bm_legacy.faces.ensure_lookup_table()
            bm_batch.faces.ensure_lookup_table()

            # 1. Legacy per-face loop
            legacy_count = 0
            for f in bm_legacy.faces:
                if repair_face_fluid_uv(f, uv_layer_legacy):
                    legacy_count += 1

            # 2. New batch repair using batch_repair_fluid_uv
            batch_count = process_mesh_fluid_uv_repairs(bm_batch, uv_layer=uv_layer_batch)

            self.assertEqual(legacy_count, batch_count)
            self.assertGreater(batch_count, 0)

            # Compare every loop UV coordinate between both meshes
            for f_leg, f_bat in zip(bm_legacy.faces, bm_batch.faces):
                for l_leg, l_bat in zip(f_leg.loops, f_bat.loops):
                    self.assertAlmostEqual(l_leg[uv_layer_legacy].uv.x, l_bat[uv_layer_batch].uv.x, places=5)
                    self.assertAlmostEqual(l_leg[uv_layer_legacy].uv.y, l_bat[uv_layer_batch].uv.y, places=5)

        finally:
            bm_legacy.free()
            bm_batch.free()

    def test_raw_mesh_batch_fluid_uv_repair(self):
        """Test zero-copy batch repair directly on bpy.types.Mesh."""
        mesh = bpy.data.meshes.new("TestRawFluidMesh")
        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.new("UVMap")

        try:
            # 10 faces
            for i in range(10):
                x_off = float(i) * 2.0
                is_inv = (i % 2 == 0)
                uv_vl, uv_vr = (0.8, 0.2) if is_inv else (0.2, 0.8)
                f, uvs = self._create_quad_face(bm, 0.2, 0.8, uv_vl, uv_vr, x_off)
                for l, uv in zip(f.loops, uvs):
                    l[uv_layer].uv = uv

            bm.to_mesh(mesh)
            mesh.update()

            # Process directly on bpy.types.Mesh
            repaired_count = process_mesh_fluid_uv_repairs(mesh)
            self.assertEqual(repaired_count, 5)

            # Verify UVs written back correctly to mesh loops
            raw_uv_layer = mesh.uv_layers.active
            for poly in mesh.polygons:
                is_inv = (poly.index % 2 == 0)
                loop_indices = list(poly.loop_indices)
                v2_y = raw_uv_layer.data[loop_indices[2]].uv.y
                v3_y = raw_uv_layer.data[loop_indices[3]].uv.y
                self.assertAlmostEqual(v2_y, 0.2, places=4)
                self.assertAlmostEqual(v3_y, 0.8, places=4)

        finally:
            bm.free()
            bpy.data.meshes.remove(mesh)

    def test_bmesh_target_faces_subset(self):
        """Test passing target_faces subset to process_mesh_fluid_uv_repairs."""
        faces = []
        for i in range(4):
            f, uvs = self._create_quad_face(self.bm, 0.2, 0.8, 0.8, 0.2, float(i) * 2.0)
            for l, uv in zip(f.loops, uvs):
                l[self.uv_layer].uv = uv
            faces.append(f)

        self.bm.faces.ensure_lookup_table()

        # Only process face 0 and face 2
        subset = [faces[0], faces[2]]
        count = process_mesh_fluid_uv_repairs(self.bm, self.uv_layer, target_faces=subset)
        self.assertEqual(count, 2)

        # Face 0 repaired
        self.assertAlmostEqual(list(faces[0].loops)[2][self.uv_layer].uv.y, 0.2, places=4)
        # Face 1 untouched (remains 0.8)
        self.assertAlmostEqual(list(faces[1].loops)[2][self.uv_layer].uv.y, 0.8, places=4)
        # Face 2 repaired
        self.assertAlmostEqual(list(faces[2].loops)[2][self.uv_layer].uv.y, 0.2, places=4)
        # Face 3 untouched (remains 0.8)
        self.assertAlmostEqual(list(faces[3].loops)[2][self.uv_layer].uv.y, 0.8, places=4)


if __name__ == "__main__":
    if "--" in sys.argv:
        argv = [sys.argv[0]] + sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = [sys.argv[0]]
    unittest.main(argv=argv)
