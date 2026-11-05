"""
Tests for Scene and Save Import Sidebar Options SSOT, CTM Export Gating, and i18n Translations.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import bpy

from MoziToolKit.i18n import tr
from MoziToolKit.i18n.dictionary import translations_dict
from MoziToolKit.operators.common import CommonMeshingOptionsMixin, draw_meshing_options
from MoziToolKit.operators.save.op_import_save import MTK_OT_import_minecraft_save
from MoziToolKit.operators.scene.op_export_scene import MOZI_OT_export_scene
from MoziToolKit.operators.scene.op_import_scene import MOZI_OT_import_scene


class TestSceneOptionsSSOTAndI18n(unittest.TestCase):
    """Test suite ensuring SSOT for meshing options between save and scene imports."""

    @classmethod
    def setUpClass(cls):
        for op_cls in (MTK_OT_import_minecraft_save, MOZI_OT_import_scene, MOZI_OT_export_scene):
            try:
                bpy.utils.register_class(op_cls)
            except ValueError:
                pass

    def test_01_ssot_inheritance(self):
        """Verifies that both save and scene import operators inherit from CommonMeshingOptionsMixin."""
        self.assertTrue(issubclass(MTK_OT_import_minecraft_save, CommonMeshingOptionsMixin))
        self.assertTrue(issubclass(MOZI_OT_import_scene, CommonMeshingOptionsMixin))

    def test_02_canonical_meshing_properties_present(self):
        """Verifies that both operators expose identical canonical meshing properties and defaults."""
        canonical_props = [
            ("enable_ao", True, "Ambient Occlusion"),
            ("mesh_fluids", True, "Mesh Fluids"),
            ("weld_vertices", True, "Weld Vertices"),
            ("origin_centered", True, "Origin Centered"),
            ("enable_ctm", True, "Connected Textures (CTM)"),
            ("enable_animated_textures", True, "Animated Textures"),
        ]

        save_rna = bpy.ops.mtk.import_minecraft_save.get_rna_type()
        scene_rna = bpy.ops.mozi.import_scene.get_rna_type()

        for prop_id, expected_default, expected_name in canonical_props:
            self.assertIn(prop_id, save_rna.properties, f"Missing {prop_id} on save import")
            self.assertIn(prop_id, scene_rna.properties, f"Missing {prop_id} on scene import")

            save_prop = save_rna.properties[prop_id]
            scene_prop = scene_rna.properties[prop_id]

            self.assertEqual(save_prop.default, expected_default)
            self.assertEqual(scene_prop.default, expected_default)
            self.assertEqual(save_prop.name, expected_name)
            self.assertEqual(scene_prop.name, expected_name)

    def test_03_scene_specific_properties(self):
        """Verifies scene-specific properties like allow_host_fallback are retained."""
        scene_rna = bpy.ops.mozi.import_scene.get_rna_type()
        self.assertIn("allow_host_fallback", scene_rna.properties)
        self.assertEqual(scene_rna.properties["allow_host_fallback"].default, False)
        self.assertIn("material_mode", scene_rna.properties)

    def test_04_export_scene_hides_ctm_option(self):
        """Verifies that MOZI_OT_export_scene does not draw enable_ctm in the sidebar."""
        export_rna = bpy.ops.mozi.export_scene.get_rna_type()
        self.assertIn("enable_ctm", export_rna.properties)
        ctm_prop = export_rna.properties["enable_ctm"]
        self.assertTrue(ctm_prop.default)
        self.assertTrue(ctm_prop.is_hidden)

        # Verify layout draw does not call prop for enable_ctm
        drawn_props = []

        class MockLayout:
            def box(self):
                return self

            def label(self, *args, **kwargs):
                pass

            def prop(self, data, prop_name, *args, **kwargs):
                drawn_props.append(prop_name)

        mock_op = SimpleNamespace(layout=MockLayout())
        MOZI_OT_export_scene.draw(mock_op, None)

        self.assertIn("max_atlas_size", drawn_props)
        self.assertNotIn("enable_ctm", drawn_props, "enable_ctm should be hidden from UI")

    def test_05_export_scene_always_includes_ctm(self):
        """Verifies that MOZI_OT_export_scene.execute always passes enable_ctm=True to export_scene_package."""
        from MoziToolKit.operators.scene import op_export_scene as op

        captured_args = {}

        def mock_export(**kwargs):
            captured_args.update(kwargs)
            return {"voxel_count": 42, "atlas_resolution": [1024, 1024]}

        mock_mesh = bpy.data.meshes.new("TestM")
        mock_obj = bpy.data.objects.new("TestActiveMesh", mock_mesh)
        mock_cloud_mesh = bpy.data.meshes.new("TestC")
        mock_cloud = bpy.data.objects.new("TestActiveMesh_VoxelCloud", mock_cloud_mesh)
        mock_cloud["mtk_is_voxel_cloud"] = True

        mock_point_cloud = SimpleNamespace(is_empty=lambda: False)

        context = MagicMock()
        context.active_object = mock_obj

        op_inst = SimpleNamespace(
            filepath="/tmp/test.mtkscene",
            max_atlas_size=2048,
            report=lambda *args, **kwargs: None,
        )

        try:
            with patch.object(op, "find_voxel_cloud", return_value=mock_cloud), \
                 patch.object(op, "extract_voxel_point_cloud", return_value=mock_point_cloud), \
                 patch.object(op, "export_scene_package", side_effect=mock_export), \
                 patch.object(op, "get_prefs", return_value=None):
                ret = MOZI_OT_export_scene.execute(op_inst, context)
                self.assertEqual(ret, {"FINISHED"})
                self.assertTrue(captured_args.get("enable_ctm"), "export_scene_package must always receive enable_ctm=True")
        finally:
            if mock_obj.name in bpy.data.objects:
                bpy.data.objects.remove(mock_obj, do_unlink=True)
            if mock_mesh.name in bpy.data.meshes:
                bpy.data.meshes.remove(mock_mesh, do_unlink=True)
            if mock_cloud.name in bpy.data.objects:
                bpy.data.objects.remove(mock_cloud, do_unlink=True)
            if mock_cloud_mesh.name in bpy.data.meshes:
                bpy.data.meshes.remove(mock_cloud_mesh, do_unlink=True)

    def test_06_scene_and_save_i18n_dictionary(self):
        """Verifies that all scene and save import/export Chinese translations are present."""
        expected_translations = {
            "MTK Scene Interchange (.mtkscene)": "MTK 场景交换包 (.mtkscene)",
            "Import MTK Scene (.mtkscene)": "导入 MTK 场景 (.mtkscene)",
            "Export MTK Scene (.mtkscene)": "导出 MTK 场景 (.mtkscene)",
            "Scene Capsule Info": "场景包信息",
            "File": "文件",
            "Bounds": "包围盒范围",
            "voxels": "体素",
            "states": "个方块状态",
            "biomes": "个生物群系",
            "entities": "个实体",
            "Mini-Atlas": "迷你图集",
            "Yes": "是",
            "No": "否",
            "Allow Host Fallback": "允许宿主资产回退",
            "PBR Atlas": "PBR 图集",
            "Maximum dimension (width and height) for the cropped Scene Mini-Atlas": "裁剪后场景迷你图集的最大边长 (宽高)",
            "Include connected-texture rules and sub-tiles in the exported scene package": "在导出的场景包中包含连接纹理规则与子图块",
            "Apply the connected-texture rules embedded in the scene package": "应用场景包中内置的连接纹理 (CTM) 规则",
            "Select an MTK world mesh, scene container, or companion point cloud": "请选择 MTK 世界网格、场景容器或伴生体素点云",
            "Active object has no companion Voxel Point Cloud": "活动物体没有伴生体素点云",
            "No companion Voxel Point Cloud found on active object.": "活动物体未找到伴生体素点云。",
        }

        hans = translations_dict.get("zh_HANS", {})
        for msgid, expected in expected_translations.items():
            self.assertIn(("*", msgid), hans, f"Missing dictionary entry for '{msgid}'")
            self.assertEqual(hans[("*", msgid)], expected)

        # Test tr() resolution in Chinese
        saved_lang = getattr(bpy.context.preferences.view, "language", "DEFAULT")
        saved_ui = getattr(bpy.context.preferences.view, "use_translate_interface", False)
        bpy.context.preferences.view.language = "zh_HANS"
        bpy.context.preferences.view.use_translate_interface = True
        try:
            self.assertEqual(tr("MTK Scene Interchange (.mtkscene)"), "MTK 场景交换包 (.mtkscene)")
            self.assertEqual(tr("Scene Capsule Info"), "场景包信息")
            self.assertEqual(tr("Mini-Atlas"), "迷你图集")
            self.assertEqual(tr("Allow Host Fallback"), "允许宿主资产回退")
        finally:
            bpy.context.preferences.view.language = saved_lang
            bpy.context.preferences.view.use_translate_interface = saved_ui


if __name__ == "__main__":
    unittest.main()
