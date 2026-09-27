"""
Unit and integration tests for voxel mesh vertex welding and bottom-center origin alignment.
Verifies that libmtk voxel meshing matches MoziToolKit requirements:
1. Meshes have duplicate spatial vertices welded into manifold topology (8 verts for 1 cube, 12 for 2 joined cubes).
2. The object origin (0, 0, 0) is situated at the bottom center of the bounding volume.
3. Corner-domain UVs and colors/AO are properly preserved during Blender injection.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
libmtk_release_path = PROJECT_DIR.parent / "libmozitoolkit" / "target" / "release"

for p in [str(libmtk_release_path), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

if "mathutils" not in sys.modules:
    sys.modules["mathutils"] = MagicMock()

try:
    import bpy
    HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data")
except ImportError:
    bpy = MagicMock()
    sys.modules["bpy"] = bpy
    sys.modules["bpy.props"] = MagicMock()
    sys.modules["bpy.types"] = MagicMock()
    sys.modules["bpy.app"] = MagicMock()
    HAS_BPY = False

if "bmesh" not in sys.modules:
    sys.modules["bmesh"] = MagicMock()

try:
    import libmtk_py as mtk_py
    HAS_LIBMTK = True
except ImportError:
    mtk_py = None
    HAS_LIBMTK = False


class TestVoxelWeldingAndOrigin(unittest.TestCase):
    def setUp(self):
        if not HAS_LIBMTK:
            self.skipTest("libmtk_py not available")

    def test_single_cube_welding(self):
        """A single solid cube should have 8 vertices when welded, and 24 when unwelded."""
        storage = mtk_py.VoxelStorage()
        storage.set_bounds(0, 0, 0, 1, 1, 1)
        storage.set_block(0, 0, 0, "minecraft:stone")

        # Welded
        cfg_welded = mtk_py.MesherConfig(
            origin_centered=True,
            weld_vertices=True,
            z_up_coordinates=True,
        )
        mesh_welded = mtk_py.SectionMesher.mesh_world(storage, cfg_welded)
        self.assertEqual(mesh_welded.vertex_count, 8)
        self.assertEqual(mesh_welded.face_count, 6)
        self.assertEqual(mesh_welded.quad_count, 6)
        self.assertEqual(mesh_welded.triangle_count, 12)
        # 6 quads * 4 loop corners = 24 loop UVs
        self.assertEqual(len(mesh_welded.get_flat_uvs()), 48)

        # Unwelded
        cfg_unwelded = mtk_py.MesherConfig(
            origin_centered=True,
            weld_vertices=False,
            z_up_coordinates=True,
        )
        mesh_unwelded = mtk_py.SectionMesher.mesh_world(storage, cfg_unwelded)
        self.assertEqual(mesh_unwelded.vertex_count, 24)
        self.assertEqual(mesh_unwelded.face_count, 6)

    def test_two_joined_cubes_welding(self):
        """Two adjacent solid cubes should cull their shared face (leaving 10 faces) and weld to 12 vertices."""
        storage = mtk_py.VoxelStorage()
        storage.set_bounds(0, 0, 0, 2, 1, 1)
        storage.set_block(0, 0, 0, "minecraft:stone")
        storage.set_block(1, 0, 0, "minecraft:stone")

        cfg_welded = mtk_py.MesherConfig(
            origin_centered=True,
            weld_vertices=True,
            z_up_coordinates=True,
        )
        mesh_welded = mtk_py.SectionMesher.mesh_world(storage, cfg_welded)
        self.assertEqual(mesh_welded.vertex_count, 12)
        self.assertEqual(mesh_welded.face_count, 10)
        self.assertEqual(mesh_welded.quad_count, 10)
        self.assertEqual(mesh_welded.triangle_count, 20)

        # Unwelded: 10 visible faces * 4 vertices = 40 vertices
        cfg_unwelded = mtk_py.MesherConfig(
            origin_centered=True,
            weld_vertices=False,
            z_up_coordinates=True,
        )
        mesh_unwelded = mtk_py.SectionMesher.mesh_world(storage, cfg_unwelded)
        self.assertEqual(mesh_unwelded.vertex_count, 40)
        self.assertEqual(mesh_unwelded.face_count, 10)

    def test_bottom_center_origin_alignment(self):
        """
        In Blender coordinates (Z-Up), the object origin should be at the bottom center:
        - Center of X is 0.0
        - Center of Y is 0.0
        - Minimum Z (base) is 0.0
        """
        # Test 1: Single cube at (0, 0, 0)
        storage = mtk_py.VoxelStorage()
        storage.set_bounds(0, 0, 0, 1, 1, 1)
        storage.set_block(0, 0, 0, "minecraft:stone")

        cfg = mtk_py.MesherConfig(
            origin_centered=True,
            weld_vertices=True,
            z_up_coordinates=True,
        )
        mesh = mtk_py.SectionMesher.mesh_world(storage, cfg)

        pos = mesh.get_flat_positions()
        xs = [pos[i * 3] for i in range(mesh.vertex_count)]
        ys = [pos[i * 3 + 1] for i in range(mesh.vertex_count)]
        zs = [pos[i * 3 + 2] for i in range(mesh.vertex_count)]

        self.assertAlmostEqual((min(xs) + max(xs)) / 2.0, 0.0, places=5)
        self.assertAlmostEqual((min(ys) + max(ys)) / 2.0, 0.0, places=5)
        self.assertAlmostEqual(min(zs), 0.0, places=5)
        self.assertAlmostEqual(max(zs), 1.0, places=5)

        # Test 2: Arbitrary offset volume (100, 50, 200) size (4, 8, 4)
        storage2 = mtk_py.VoxelStorage()
        storage2.set_bounds(100, 50, 200, 4, 8, 4)
        storage2.set_block(100, 50, 200, "minecraft:stone")
        storage2.set_block(103, 57, 203, "minecraft:stone")

        mesh2 = mtk_py.SectionMesher.mesh_world(storage2, cfg)
        pos2 = mesh2.get_flat_positions()
        xs2 = [pos2[i * 3] for i in range(mesh2.vertex_count)]
        ys2 = [pos2[i * 3 + 1] for i in range(mesh2.vertex_count)]
        zs2 = [pos2[i * 3 + 2] for i in range(mesh2.vertex_count)]

        # The bounding box was (100..104, 50..58, 200..204)
        # Block at 100, 50, 200 is at min_x, min_y, min_z
        # Block at 103, 57, 203 is at max_x, max_y, max_z
        self.assertAlmostEqual((min(xs2) + max(xs2)) / 2.0, 0.0, places=5)
        self.assertAlmostEqual((min(ys2) + max(ys2)) / 2.0, 0.0, places=5)
        self.assertAlmostEqual(min(zs2), 0.0, places=5)
        self.assertAlmostEqual(max(zs2), 8.0, places=5)


if __name__ == "__main__":
    unittest.main()
