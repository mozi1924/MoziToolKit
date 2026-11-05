"""
Tests for Context Menu Registration and Dynamic Rendering.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import bpy
import bpy_extras
import MoziToolKit.ui as ui

from MoziToolKit.utils.system.menu_registry import (
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
        from MoziToolKit.i18n import tr
        from MoziToolKit.i18n.dictionary import translations_dict

        zh_dict = translations_dict.get("zh_HANS", {})
        self.assertEqual(zh_dict.get(('*', 'Rebuild Voxel Mesh')), '重建体素网格')
        self.assertEqual(zh_dict.get(('*', 'Toggle Voxel Point Cloud Visibility')), '切换体素点云可见性')
        self.assertEqual(zh_dict.get(('*', 'Toggle Voxel Cloud Visibility')), '切换体素点云可见性')
        self.assertEqual(zh_dict.get(('*', 'Select Transparent Faces')), '选择透明面')
        self.assertEqual(zh_dict.get(('*', 'Clear Custom Normals')), '删除自定义法向')
        self.assertEqual(zh_dict.get(('*', 'Set Image Interpolation to Closest')), '图像纹理插值设为最近')

    def test_rebuild_mesh_rejects_provenance_only_mesh(self):
        from MoziToolKit.operators.mesh import resolve_mesh_rebuild_targets, MOZI_OT_rebuild_mesh

        # A standalone external mesh with provenance has no voxel source.
        mesh = bpy.data.meshes.new("Character_Hair_Mesh")
        mesh.attributes.new(name="mtk_source_texture_key", type="STRING", domain="POINT")
        obj = bpy.data.objects.new("Character_Hair", mesh)
        bpy.context.scene.collection.objects.link(obj)

        try:
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)

            root, world, cloud, stype = resolve_mesh_rebuild_targets(bpy.context)
            self.assertEqual(stype, "NONE")
            self.assertIsNone(world)
            self.assertFalse(MOZI_OT_rebuild_mesh.poll(bpy.context))
        finally:
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(mesh)

    def test_replace_material_provenance_predetection(self):
        from MoziToolKit.operators.op_materials import _has_provenance_attributes

        # None or non-mesh
        self.assertFalse(_has_provenance_attributes(None))
        empty = bpy.data.objects.new("EmptyTest", None)
        self.assertFalse(_has_provenance_attributes(empty))

        # Mesh without attributes
        mesh_empty = bpy.data.meshes.new("MeshEmptyTest")
        obj_mesh = bpy.data.objects.new("ObjMeshTest", mesh_empty)
        self.assertFalse(_has_provenance_attributes(obj_mesh))

        # Mesh with attributes
        mesh_prov = bpy.data.meshes.new("MeshProvTest")
        mesh_prov.attributes.new(name="mtk_source_texture_key", type="STRING", domain="POINT")
        obj_prov = bpy.data.objects.new("ObjProvTest", mesh_prov)
        self.assertTrue(_has_provenance_attributes(obj_prov))

        # Clean up
        bpy.data.objects.remove(obj_prov)
        bpy.data.meshes.remove(mesh_prov)
        bpy.data.objects.remove(obj_mesh)
        bpy.data.meshes.remove(mesh_empty)
        bpy.data.objects.remove(empty)


    def test_unknown_operator_ids_are_filtered(self):
        from MoziToolKit.utils.config.models import ConfigData

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
        from MoziToolKit.utils.config.models import ConfigData

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
        class DummyLayout:
            def __init__(self):
                self.operators = []
            def operator(self, op_id, **kwargs):
                self.operators.append(op_id)
                return self
            def separator(self): pass
            def label(self, **kwargs): pass

        with patch(
            "MoziToolKit.utils.system.menu_registry.load_config",
            return_value={
                "mesh": [
                    {"operator": "mozi.ghost", "label": "Ghost", "enabled": True},
                    {"operator": "mozi.rebuild_mesh", "label": "Rebuild", "enabled": True},
                ]
            },
        ):
            layout = DummyLayout()
            draw_dynamic_menu(layout, "mesh")

        self.assertIn("mozi.rebuild_mesh", layout.operators)
        self.assertNotIn("mozi.ghost", layout.operators)

    def test_config_manager_reset_single_view(self):
        from MoziToolKit.utils.config import get_config_manager
        from MoziToolKit.utils.config.models import MenuItem

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


    def test_menu_hooks_registration(self):
        # Register hooks
        ui.menu_mesh.register()
        ui.menu_object.register()
        ui.menu_select.register()
        ui.menu_uv.register()

        class DummyLayout:
            def __init__(self):
                self.operators = []
                self.labels = []
            def operator(self, op_id, **kwargs):
                self.operators.append(op_id)
                return self
            def label(self, **kwargs):
                self.labels.append(kwargs)
                return self
            def separator(self): pass

        layout = DummyLayout()
        draw_dynamic_menu(layout, "object")
        self.assertTrue(len(layout.labels) > 0)
        self.assertTrue(len(layout.operators) > 0)

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

