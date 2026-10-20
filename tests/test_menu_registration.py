"""
Tests for Context Menu Registration and Dynamic Rendering.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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
        self.assertIn("mozi.toggle_voxel_cloud", all_ops)
        self.assertNotIn("mozi.precompile_cache", all_ops)
        # cull_mesh_faces is misleading in right-click context menu and strictly excluded
        self.assertNotIn("mozi.cull_mesh_faces", all_ops)
        # Internal/duplicate/operator-wrapper entries must never be exposed
        for internal_id in (
            "mozi.remesh_from_voxel_cloud",
            "mozi.rematerialize_from_voxel_cloud",
            "mozi.clean_empty_material_slots",
            "mozi.update_material_shading_adaptation",
        ):
            self.assertNotIn(internal_id, all_ops)
        # Optional operators for preference pool
        self.assertIn("mozi.repair_fluid_uv", all_ops)
        self.assertIn("mozi.auto_extrude_repair", all_ops)
        self.assertIn("mozi.adaptive_pixel_split", all_ops)

        presets = get_default_presets()
        self.assertIn("object", presets)
        self.assertIn("mesh", presets)
        self.assertIn("uv", presets)

        # Default preset for mesh
        mesh_op_ids = [item["operator"] for item in presets["mesh"]]
        self.assertIn("mozi.adaptive_pixel_split", mesh_op_ids)
        self.assertIn("mozi.replace_material", mesh_op_ids)
        self.assertIn("mozi.rebuild_mesh", mesh_op_ids)
        self.assertIn("mozi.toggle_voxel_cloud", mesh_op_ids)
        self.assertIn("mozi.auto_extrude_repair", mesh_op_ids)
        self.assertIn("mozi.random_extrude", mesh_op_ids)
        self.assertIn("mozi.select_hard_edges", mesh_op_ids)
        self.assertIn("mozi.select_transparent_faces", mesh_op_ids)
        self.assertIn("mozi.repair_fluid_uv", mesh_op_ids)
        self.assertIn("mozi.clear_custom_normals", mesh_op_ids)
        self.assertIn("mozi.set_texture_interpolation_closest", mesh_op_ids)
        # cull_mesh_faces is intentionally excluded from the context menu preset
        self.assertNotIn("mozi.cull_mesh_faces", mesh_op_ids)

        # Default preset for object
        obj_op_ids = [item["operator"] for item in presets["object"]]
        self.assertEqual(obj_op_ids, [
            "mozi.rebuild_mesh",
            "mozi.replace_material",
            "mozi.toggle_voxel_cloud",
            "mozi.clear_custom_normals",
            "mozi.set_texture_interpolation_closest",
        ])

        # Default preset for uv
        uv_op_ids = [item["operator"] for item in presets["uv"]]
        self.assertEqual(uv_op_ids, [
            "mozi.adaptive_pixel_split",
            "mozi.scale_uv",
            "mozi.select_transparent_faces",
        ])

    def test_i18n_right_click_menu_labels(self):
        from i18n import tr
        from i18n.dictionary import translations_dict

        zh_dict = translations_dict.get("zh_HANS", {})
        self.assertEqual(zh_dict.get(('*', 'Rebuild Voxel Mesh')), '重建体素网格')
        self.assertEqual(zh_dict.get(('*', 'Toggle Voxel Point Cloud Visibility')), '切换体素点云可见性')
        self.assertEqual(zh_dict.get(('*', 'Toggle Voxel Cloud Visibility')), '切换体素点云可见性')
        self.assertEqual(zh_dict.get(('*', 'Select Transparent Faces')), '选择透明面')
        self.assertEqual(zh_dict.get(('*', 'Clear Custom Normals')), '删除自定义法向')
        self.assertEqual(zh_dict.get(('*', 'Set Image Interpolation to Closest')), '图像纹理插值设为最近')

    def test_rebuild_mesh_rejects_provenance_only_mesh(self):
        from operators.mesh import resolve_mesh_rebuild_targets, MOZI_OT_rebuild_mesh

        # A standalone external mesh with provenance has no voxel source.
        mock_obj_prov = MagicMock(type="MESH")
        mock_obj_prov.name = "Character_Hair"
        mock_obj_prov.get.return_value = None
        mock_obj_prov.parent = None
        mock_obj_prov.data.attributes = {"mtk_source_texture_key": MagicMock()}
        mock_context = MagicMock()
        mock_context.active_object = mock_obj_prov
        mock_context.selected_objects = [mock_obj_prov]

        root, world, cloud, stype = resolve_mesh_rebuild_targets(mock_context)
        self.assertEqual(stype, "NONE")
        self.assertIsNone(world)
        self.assertFalse(MOZI_OT_rebuild_mesh.poll(mock_context))

    def test_replace_material_provenance_predetection(self):
        from operators.op_materials import _has_provenance_attributes

        # None or non-mesh
        self.assertFalse(_has_provenance_attributes(None))
        mock_obj_none = MagicMock(type="EMPTY")
        self.assertFalse(_has_provenance_attributes(mock_obj_none))

        # Mesh without attributes
        mock_obj_mesh = MagicMock(type="MESH")
        mock_obj_mesh.data.attributes = {}
        self.assertFalse(_has_provenance_attributes(mock_obj_mesh))

        # Mesh with attributes
        mock_obj_prov = MagicMock(type="MESH")
        mock_obj_prov.data.attributes = {"mtk_source_texture_key": MagicMock()}
        self.assertTrue(_has_provenance_attributes(mock_obj_prov))


    def test_unknown_operator_ids_are_filtered(self):
        from utils.config.models import ConfigData

        raw = {
            "version": 1,
            "views": {
                "mesh": [
                    {"operator": "mozi.ghost", "label": "Ghost", "enabled": True},
                    {"operator": "mozi.rebuild_mesh", "label": "Rebuild", "enabled": True},
                ]
            },
        }
        cfg = ConfigData.from_dict(raw)
        self.assertEqual([it.operator for it in cfg.views["mesh"]], ["mozi.rebuild_mesh"])

    def test_user_customizations_preserved(self):
        """Custom labels, ordering, disabled flags, and removals survive normalization/reload."""
        from utils.config.models import ConfigData

        user_dict = {
            "version": 1,
            "views": {
                "object": [
                    {"operator": "mozi.rebuild_mesh", "label": "One and Only", "enabled": False}
                ],
                "mesh": [
                    {"operator": "mozi.random_extrude", "label": "Solo Extrude", "enabled": True}
                ],
                "uv": [],
            },
        }

        cfg = ConfigData.from_dict(user_dict)
        self.assertEqual(len(cfg.views["object"]), 1)
        self.assertEqual(cfg.views["object"][0].operator, "mozi.rebuild_mesh")
        self.assertEqual(cfg.views["object"][0].label, "One and Only")
        self.assertFalse(cfg.views["object"][0].enabled)
        self.assertEqual(len(cfg.views["mesh"]), 1)

        for _ in range(5):
            cfg.normalize()
            self.assertEqual(len(cfg.views["object"]), 1)
            self.assertEqual(cfg.views["object"][0].label, "One and Only")
            self.assertFalse(cfg.views["object"][0].enabled)
            self.assertEqual(len(cfg.views["mesh"]), 1)

        cfg2 = ConfigData.from_dict(cfg.to_dict())
        self.assertEqual(len(cfg2.views["object"]), 1)
        self.assertEqual(cfg2.views["object"][0].label, "One and Only")
        self.assertFalse(cfg2.views["object"][0].enabled)
        self.assertEqual(len(cfg2.views["mesh"]), 1)

    def test_draw_dynamic_menu_skips_unregistered(self):
        with patch(
            "utils.system.menu_registry.load_config",
            return_value={
                "mesh": [
                    {"operator": "mozi.ghost", "label": "Ghost", "enabled": True},
                    {"operator": "mozi.rebuild_mesh", "label": "Rebuild", "enabled": True},
                ]
            },
        ):
            layout = MagicMock()
            draw_dynamic_menu(layout, "mesh")

        called_ids = [call.args[0] for call in layout.operator.call_args_list if call.args]
        self.assertIn("mozi.rebuild_mesh", called_ids)
        self.assertNotIn("mozi.ghost", called_ids)

    def test_config_manager_reset_single_view(self):
        from utils.config import get_config_manager
        from utils.config.models import MenuItem

        mgr = get_config_manager()
        # Set custom views
        mgr.set_views({
            "mesh": [{"operator": "mozi.adaptive_pixel_split", "label": "Custom Split", "enabled": True}],
            "object": [{"operator": "mozi.rebuild_mesh", "label": "Custom Rebuild", "enabled": True}],
            "uv": [{"operator": "mozi.scale_uv", "label": "Custom Scale", "enabled": True}],
        })

        # Reset only mesh view
        mgr.reset_views(view_name="mesh")
        views = mgr.get_views()
        # Mesh should be reset to default preset list (length > 5)
        self.assertGreater(len(views["mesh"]), 3)
        # Object and UV should still keep their custom item
        self.assertEqual(views["object"][0]["label"], "Custom Rebuild")
        self.assertEqual(views["uv"][0]["label"], "Custom Scale")

        # Reset all views
        mgr.reset_views()
        views_all = mgr.get_views()
        self.assertNotEqual(views_all["object"][0]["label"], "Custom Rebuild")


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

