"""
Tests for canonical voxel-level FaceCuller and VoxelStorage integration.
"""

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from _mtk_helpers import mesh_world


class TestVoxelCullBridge(unittest.TestCase):

    def test_vegetation_culling_rules(self):
        try:
            import libmtk_py
        except ImportError:
            self.skipTest("libmtk_py not available")

        storage = libmtk_py.VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        palette = ["minecraft:air", "minecraft:stone", "minecraft:kelp[age=0]"]
        grid = [0] * 4096
        # Stone at (0, 0, 0)
        grid[0] = 1
        # Kelp above stone at (0, 1, 0)
        grid[16] = 2
        storage.set_section_snapshot(0, 0, 0, 0, 0, 0, 16, 16, 16, palette, grid)

        culler = libmtk_py.FaceCuller()
        config = libmtk_py.MesherConfig()
        mesh = mesh_world(storage, config=config, culler=culler)

        # Stone top face under kelp must NOT be culled (stone must have all 6 faces rendered)
        self.assertGreaterEqual(mesh.face_count, 6)

    def test_voxel_storage_dynamic_bounds(self):
        try:
            import libmtk_py
        except ImportError:
            self.skipTest("libmtk_py not available")

        storage = libmtk_py.VoxelStorage()
        palette = ["minecraft:air", "minecraft:stone"]
        grid = [0] * 4096
        grid[0] = 1

        storage.set_section_snapshot(0, 0, 0, 0, 0, 0, 16, 16, 16, palette, grid)
        self.assertEqual(storage.get_bounds(), (0, 0, 0, 16, 16, 16))

        # Second chunk at (1, 0, 0) automatically expands bounds to [0..32, 0..16, 0..16]
        storage.set_section_snapshot(1, 0, 0, 16, 0, 0, 16, 16, 16, palette, grid)
        self.assertEqual(storage.get_bounds(), (0, 0, 0, 32, 16, 16))


if __name__ == "__main__":
    unittest.main()

