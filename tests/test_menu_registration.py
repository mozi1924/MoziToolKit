"""
Tests for Context Menu Registration and Dynamic Rendering.
"""

import unittest
from unittest.mock import MagicMock

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from ui import menus
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
        self.assertIn("mozi.replace_materials", all_ops)
        self.assertIn("mozi.restore_materials_from_provenance", all_ops)
        self.assertIn("mozi.precompile_cache", all_ops)

        presets = get_default_presets()
        self.assertIn("object", presets)
        self.assertIn("mesh", presets)
        self.assertIn("uv", presets)

        obj_op_ids = [item["operator"] for item in presets["object"]]
        self.assertIn("mozi.replace_materials", obj_op_ids)
        self.assertIn("mozi.restore_materials_from_provenance", obj_op_ids)

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_menu_hooks_registration(self):
        # Register hooks
        menus.register()

        # Mock layout to test drawing
        mock_layout = MagicMock()
        draw_dynamic_menu(mock_layout, "object")
        self.assertTrue(mock_layout.label.called)
        self.assertTrue(mock_layout.operator.called)

        # Unregister hooks
        menus.unregister()


if __name__ == "__main__":
    unittest.main()
