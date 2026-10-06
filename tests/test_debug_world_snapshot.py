import os
import sys
from pathlib import Path
from unittest.mock import MagicMock
import types

PROJECT_DIR = Path(__file__).parent.parent.resolve()
site_pkgs = PROJECT_DIR / "site-packages"
for p in [str(site_pkgs), str(PROJECT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

if "mathutils" not in sys.modules:
    sys.modules["mathutils"] = MagicMock()

if "bpy_extras" not in sys.modules:
    bpy_extras = types.ModuleType("bpy_extras")
    bpy_extras.__path__ = []
    io_utils = types.ModuleType("bpy_extras.io_utils")
    io_utils.ExportHelper = object
    io_utils.ImportHelper = object
    bpy_extras.io_utils = io_utils
    sys.modules["bpy_extras"] = bpy_extras
    sys.modules["bpy_extras.io_utils"] = io_utils

try:
    import bpy
    HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "meshes")
except ImportError:
    bpy = MagicMock()
    HAS_BPY = False

if not HAS_BPY:
    class _MockOperator: pass
    class _MockPanel: pass
    class _MockMenu: pass
    class _MockPropertyGroup: pass
    class _MockUIList: pass
    class _MockAddonPreferences: pass

    class _MockTypes:
        Operator = _MockOperator
        Panel = _MockPanel
        Menu = _MockMenu
        PropertyGroup = _MockPropertyGroup
        UIList = _MockUIList
        AddonPreferences = _MockAddonPreferences

    bpy.types = _MockTypes
    bpy.app = MagicMock()
    bpy.props = MagicMock()

    sys.modules["bpy"] = bpy
    sys.modules["bpy.props"] = bpy.props
    sys.modules["bpy.types"] = _MockTypes
    sys.modules["bpy.app"] = bpy.app
    sys.modules["bmesh"] = MagicMock()

import gzip
import json
import unittest
import libmtk_py


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
        self.assertGreater(storage.dirty_section_count(), 50)

        config = libmtk_py.MesherConfig(enable_ao=True, mesh_fluids=True, z_up_coordinates=True)
        mesh = libmtk_py.SectionMesher.mesh_world(storage, config)

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
