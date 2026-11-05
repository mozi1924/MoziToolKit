from _mtk_helpers import mesh_world
import gzip
import json
import os
import sys
import unittest
from pathlib import Path

import bpy
import bmesh
import mathutils
import libmtk_py

PROJECT_DIR = Path(__file__).parent.parent.resolve()


class TestDebugWorldSnapshot(unittest.TestCase):
    """Verifies pure-code generation and meshing of canonical Minecraft debug world."""

    def test_load_and_mesh_debug_world(self):
        from _assets import require_assets

        require_assets()  # canonical debug world requires full vanilla assets
        storage = libmtk_py.VoxelStorage.create_debug_world()
        bounds = storage.get_bounds()
        self.assertEqual(bounds[0], 0)
        self.assertEqual(bounds[1], 69)
        self.assertEqual(bounds[2], 0)
        self.assertGreater(bounds[3], 100)
        self.assertEqual(bounds[4], 3)
        self.assertGreater(bounds[5], 100)
        self.assertGreater(libmtk_py.unstable.testing.voxel_dirty_section_count(storage), 50)

        config = libmtk_py.MesherConfig(enable_ao=True, mesh_fluids=True, z_up_coordinates=True)
        mesh = mesh_world(storage, config)

        self.assertGreater(mesh.quad_count, 10000, "Should generate >10000 quads for debug world")
        self.assertGreater(mesh.vertex_count, 10000, "Should generate >10000 vertices for debug world")

    def test_pure_code_from_states(self):
        states = [
            "minecraft:stone",
            "minecraft:granite",
            "minecraft:oak_stairs[facing=north,half=bottom,shape=straight]",
        ]
        storage = libmtk_py.VoxelStorage.create_debug_world_from_states(states)
        self.assertEqual(storage.get_block(1, 70, 1), "minecraft:stone")
        self.assertEqual(storage.get_block(1, 70, 3), "minecraft:granite")


if __name__ == "__main__":
    unittest.main()
