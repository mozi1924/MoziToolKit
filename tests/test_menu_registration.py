"""
Tests for Context Menu Registration and Dynamic Rendering.
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

try:
    import bpy
    import bpy_extras
    HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "meshes") and not isinstance(bpy.data, MagicMock)
except ImportError:
    bpy = MagicMock()
    import types
    bpy_extras = types.ModuleType("bpy_extras")
    bpy_extras.__path__ = []

    class _MockOperator: pass
    class _MockPanel: pass
    class _MockMenu: pass
    class _MockPropertyGroup: pass
    class _MockUIList: pass
    class _MockAddonPreferences: pass
    class _MockExportHelper: pass
    class _MockImportHelper: pass

    class _MockTypes:
        Operator = _MockOperator
        Panel = _MockPanel
        Menu = _MockMenu
        PropertyGroup = _MockPropertyGroup
        UIList = _MockUIList
        AddonPreferences = _MockAddonPreferences

    class _MockIoUtils:
        ExportHelper = _MockExportHelper
        ImportHelper = _MockImportHelper

    io_utils_mod = types.ModuleType("bpy_extras.io_utils")
    io_utils_mod.ExportHelper = _MockExportHelper
    io_utils_mod.ImportHelper = _MockImportHelper

    bpy.types = _MockTypes
    bpy.app = MagicMock()
    bpy.props = MagicMock()
    bpy_extras.io_utils = io_utils_mod

    sys.modules["bpy"] = bpy
    sys.modules["bpy.props"] = bpy.props
    sys.modules["bpy.types"] = _MockTypes
    sys.modules["bpy.app"] = bpy.app
    sys.modules["bpy_extras"] = bpy_extras
    sys.modules["bpy_extras.io_utils"] = io_utils_mod
    HAS_BPY = False

if HAS_BPY:
    import ui
else:
    ui = None

from utils.system.menu_registry import (
    draw_dynamic_menu,
    get_all_operators,
    get_default_presets,
    ALL_OPERATORS,
    DEFAULT_PRESETS,
)




class TestMenuRegistration(unittest.TestCase):
    def test_canonical_operators_and_presets(self):
        all_ops = get_all_operators()
        self.assertIn("mozi.replace_material", all_ops)
        self.assertIn("mozi.restore_materials_from_attributes", all_ops)
        self.assertNotIn("mozi.precompile_cache", all_ops)
        self.assertIn("mozi.repair_fluid_uv", all_ops)
        self.assertIn("mozi.auto_extrude_repair", all_ops)
        self.assertIn("mozi.adaptive_pixel_split", all_ops)
        self.assertIn("mozi.cull_mesh_faces", all_ops)

        presets = get_default_presets()
        self.assertIn("object", presets)
        self.assertIn("mesh", presets)
        self.assertIn("uv", presets)

        mesh_op_ids = [item["operator"] for item in presets["mesh"]]
        self.assertIn("mozi.repair_fluid_uv", mesh_op_ids)
        self.assertIn("mozi.auto_extrude_repair", mesh_op_ids)
        self.assertIn("mozi.adaptive_pixel_split", mesh_op_ids)
        self.assertIn("mozi.cull_mesh_faces", mesh_op_ids)

        uv_op_ids = [item["operator"] for item in presets["uv"]]
        self.assertIn("mozi.repair_fluid_uv", uv_op_ids)
        self.assertIn("mozi.scale_uv", uv_op_ids)


    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_menu_hooks_registration(self):
        # Register hooks
        ui.menu_mesh.register()
        ui.menu_object.register()
        ui.menu_select.register()
        ui.menu_uv.register()

        # Mock layout to test drawing
        mock_layout = MagicMock()
        draw_dynamic_menu(mock_layout, "object")
        self.assertTrue(mock_layout.label.called)
        self.assertTrue(mock_layout.operator.called)

        # Unregister hooks
        ui.menu_uv.unregister()
        ui.menu_select.unregister()
        ui.menu_object.unregister()
        ui.menu_mesh.unregister()


if __name__ == "__main__":
    if "--" in sys.argv:
        argv = [sys.argv[0]] + sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = [sys.argv[0]]
    unittest.main(argv=argv)

