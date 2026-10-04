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
    """Verifies offline loading and meshing of exported Minecraft live debug world."""

    def test_load_and_mesh_debug_world(self):
        storage = libmtk_py.VoxelStorage.create_debug_world()
        bounds = storage.get_bounds()
        self.assertEqual(bounds, (0, 69, 0, 361, 3, 363))
        self.assertEqual(storage.dirty_section_count(), 529)

        config = libmtk_py.MesherConfig(enable_ao=True, mesh_fluids=True, z_up_coordinates=True)
        mesh = libmtk_py.SectionMesher.mesh_world(storage, config)

        self.assertGreater(mesh.quad_count, 100000, "Should generate >100000 quads for debug world")
        self.assertGreater(mesh.vertex_count, 100000, "Should generate >100000 vertices for debug world")


if __name__ == "__main__":
    unittest.main()
