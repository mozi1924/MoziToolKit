"""
Unit tests for Minecraft Save Container Properties (MoziSaveProperties),
Collapsible Re-mesh Settings, Yefira Selection Reload, and Refresh Synchronization.
"""

from __future__ import annotations

import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    import bpy
except ImportError:
    bpy = MagicMock()

from MoziToolKit.operators.save import (
    MOZI_OT_refresh_save_mesh,
    MOZI_OT_save_load_yefira_selection,
    MOZI_OT_save_reset_settings,
    resolve_save_container,
)
from MoziToolKit.operators.save.properties import (
    MoziSaveProperties,
    get_save_properties,
    sync_save_properties_from_object,
    sync_save_properties_to_custom_props,
)
from MoziToolKit.ui.panel_save import _draw_save_container_ui
from MoziToolKit.utils.system.save_registry import get_save_registry


class _MockObject:
    def __init__(self, name: str, obj_type: str = "EMPTY", data: Any = None):
        self.name = name
        self.type = obj_type
        self.data = data
        self.parent = None
        self.children = []
        self._props = {}
        self.users_collection = [MagicMock()]
        self.location = (0.0, 0.0, 0.0)

    def __getitem__(self, key):
        return self._props[key]

    def __setitem__(self, key, value):
        self._props[key] = value

    def __delitem__(self, key):
        if key in self._props:
            del self._props[key]

    def __contains__(self, key):
        return key in self._props

    def get(self, key, default=None):
        return self._props.get(key, default)

    def select_set(self, val):
        pass


class _MockLayout:
    def __init__(self):
        self.labels = []
        self.props = []
        self.operators = []
        self.boxes = []
        self.alert = False

    def row(self, align=False):
        return self

    def column(self, align=False):
        return self

    def box(self):
        b = _MockLayout()
        self.boxes.append(b)
        return b

    def separator(self):
        pass

    def label(self, text="", icon="NONE"):
        self.labels.append((text, icon))

    def prop(self, data, prop_name, text="", icon="NONE", emboss=True, toggle=False):
        self.props.append((data, prop_name, text, icon))

    def operator(self, op_id, text="", icon="NONE"):
        op = MagicMock()
        op.bl_idname = op_id
        self.operators.append((op_id, text, icon))
        return op

    def all_props(self):
        res = list(self.props)
        for b in self.boxes:
            res.extend(b.all_props())
        return res

    def all_operators(self):
        res = list(self.operators)
        for b in self.boxes:
            res.extend(b.all_operators())
        return res


IS_REAL_BLENDER = (
    not isinstance(bpy, MagicMock)
    and hasattr(bpy, "app")
    and not isinstance(bpy.app, MagicMock)
    and hasattr(bpy.app, "version")
    and isinstance(bpy.app.version, tuple)
    and bpy.app.version[0] >= 4
    and hasattr(bpy, "data")
    and hasattr(bpy.data, "objects")
    and not isinstance(bpy.data.objects, MagicMock)
)


class TestSaveProperties(unittest.TestCase):
    def setUp(self):
        if IS_REAL_BLENDER:
            self.skipTest("Uses lightweight mock data blocks for save properties unit testing")

        self.tmp_reg_dir = tempfile.TemporaryDirectory()
        self.reg_file = Path(self.tmp_reg_dir.name) / "save_registry.json"
        reg = get_save_registry()
        reg.registry_file = self.reg_file
        reg._cache = {}

        self.orig_objects = getattr(bpy.data, "objects", None)
        self.orig_meshes = getattr(bpy.data, "meshes", None)

        class MockObjectsDict(dict):
            def new(self, name, data=None):
                obj_type = "MESH" if data is not None else "EMPTY"
                obj = _MockObject(name, obj_type=obj_type, data=data)
                self[name] = obj
                return obj

            def get(self, name, default=None):
                return super().get(name, default)

        self.mock_objects = MockObjectsDict()
        bpy.data.objects = self.mock_objects

        class MockMeshesDict(dict):
            def new(self, name):
                m = MagicMock()
                m.name = name
                m.vertices = [1, 2, 3]
                m.polygons = [1]
                self[name] = m
                return m

            def get(self, name, default=None):
                return super().get(name, default)

        self.mock_meshes = MockMeshesDict()
        bpy.data.meshes = self.mock_meshes

        self.root = _MockObject("Save_TestWorld_overworld", "EMPTY")
        self.root["mtk:is_container"] = True
        self.root["mtk:container_type"] = "SAVE"
        self.root["mozi_save_uuid"] = "uuid-save-101"
        self.root["mtk_world_name"] = "TestWorld"
        self.root["mtk_mc_version"] = "1.21.4"
        self.root["mtk_dimension"] = "overworld"
        self.root["mtk_min_coord"] = [-32, -64, -32]
        self.root["mtk_max_coord"] = [32, 128, 32]
        self.root["mtk_enable_ao"] = True
        self.root["mtk_mesh_fluids"] = True
        self.root["mtk_weld_vertices"] = True
        self.root["mtk_origin_centered"] = True
        self.root["mtk_enable_ctm"] = True
        self.root["mtk_enable_animated_textures"] = True

        self.mesh = _MockObject("Save_TestWorld_overworld_Mesh", "MESH", MagicMock())
        self.mesh.parent = self.root
        self.mesh["mtk:is_save_mesh"] = True
        self.mesh["mozi_save_uuid"] = "uuid-save-101"
        self.mesh.data.vertices = [MagicMock()] * 10
        self.mesh.data.polygons = [MagicMock()] * 5
        self.root.children = [self.mesh]

    def tearDown(self):
        if not IS_REAL_BLENDER:
            if hasattr(self, "orig_objects") and self.orig_objects is not None:
                bpy.data.objects = self.orig_objects
            if hasattr(self, "orig_meshes") and self.orig_meshes is not None:
                bpy.data.meshes = self.orig_meshes
        if hasattr(self, "tmp_reg_dir"):
            try:
                self.tmp_reg_dir.cleanup()
            except Exception:
                pass

    def test_get_save_properties_initial_sync(self):
        """Verifies get_save_properties initializes from object custom properties cleanly without dirtying."""
        props = get_save_properties(self.root)
        self.assertIsNotNone(props)
        self.assertEqual(props.dimension, "overworld")
        self.assertEqual(tuple(props.min_coord), (-32, -64, -32))
        self.assertEqual(tuple(props.max_coord), (32, 128, 32))
        self.assertTrue(props.enable_ao)
        self.assertTrue(props.mesh_fluids)
        self.assertTrue(props.weld_vertices)
        self.assertTrue(props.origin_centered)
        self.assertTrue(props.enable_ctm)
        self.assertTrue(props.enable_animated_textures)
        self.assertFalse(props.is_dirty)

        # Child mesh also resolves root properties
        props_child = get_save_properties(self.mesh)
        self.assertEqual(props_child, props)

    def test_sync_save_properties_to_custom_props(self):
        """Verifies syncing MoziSaveProperties back into container custom properties."""
        props = get_save_properties(self.root)
        props.min_coord = (-16, 0, -16)
        props.max_coord = (16, 64, 16)
        props.dimension = "the_nether"
        props.enable_ao = False

        sync_save_properties_to_custom_props(props, self.root, self.mesh)
        self.assertEqual(self.root["mtk_min_coord"], [-16, 0, -16])
        self.assertEqual(self.root["mtk_max_coord"], [16, 64, 16])
        self.assertEqual(self.root["mtk_dimension"], "the_nether")
        self.assertFalse(self.root["mtk_enable_ao"])

        self.assertEqual(self.mesh["mtk_min_coord"], [-16, 0, -16])
        self.assertEqual(self.mesh["mtk_dimension"], "the_nether")

    def test_reset_settings_operator(self):
        """Verifies MOZI_OT_save_reset_settings reverts unapplied edits."""
        props = get_save_properties(self.root)
        props.min_coord = (-100, 0, -100)
        props.is_dirty = True

        ctx = types.SimpleNamespace(active_object=self.root)
        self.assertTrue(MOZI_OT_save_reset_settings.poll(ctx))

        op = MOZI_OT_save_reset_settings()
        op.report = MagicMock()
        res = op.execute(ctx)
        self.assertEqual(res, {"FINISHED"})
        self.assertEqual(tuple(props.min_coord), (-32, -64, -32))
        self.assertFalse(props.is_dirty)

    def test_yefira_selection_reload_operator(self):
        """Verifies MOZI_OT_save_load_yefira_selection reads yefira_selection.json into save properties."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "World"
            tmp_path.mkdir()
            (tmp_path / "level.dat").write_text("dummy")

            sel_data = {
                "version": 1,
                "dimension": "minecraft:the_nether",
                "pos1": {"x": -50, "y": 10, "z": -50},
                "pos2": {"x": 50, "y": 100, "z": 50},
            }
            (tmp_path / "yefira_selection.json").write_text(json.dumps(sel_data))

            reg = get_save_registry()
            reg.relink_save("uuid-save-101", tmp_path)

            ctx = types.SimpleNamespace(active_object=self.mesh)
            self.assertTrue(MOZI_OT_save_load_yefira_selection.poll(ctx))

            op = MOZI_OT_save_load_yefira_selection()
            op.report = MagicMock()
            res = op.execute(ctx)
            self.assertEqual(res, {"FINISHED"})

            props = get_save_properties(self.mesh)
            self.assertEqual(tuple(props.min_coord), (-50, 10, -50))
            self.assertEqual(tuple(props.max_coord), (50, 100, 50))
            self.assertEqual(props.dimension, "the_nether")
            self.assertTrue(props.is_dirty)

    def test_refresh_save_mesh_with_modified_properties(self):
        """Verifies that MOZI_OT_refresh_save_mesh honors modified MoziSaveProperties and updates custom properties."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "World"
            tmp_path.mkdir()
            (tmp_path / "level.dat").write_text("dummy")

            reg = get_save_registry()
            reg.relink_save("uuid-save-101", tmp_path)

            props = get_save_properties(self.root)
            props.min_coord = (-10, 0, -10)
            props.max_coord = (10, 50, 10)
            props.dimension = "the_end"
            props.enable_ao = False
            props.is_dirty = True

            class DummyRefreshOp:
                def __init__(self):
                    self.report = MagicMock()
                    self.run_async = False
                    self._runner = None

                def execute(self, ctx):
                    return MOZI_OT_refresh_save_mesh.execute(self, ctx)

            op = DummyRefreshOp()
            ctx = types.SimpleNamespace(
                active_object=self.mesh,
                selected_objects=[self.mesh],
                collection=MagicMock(),
                view_layer=types.SimpleNamespace(objects=types.SimpleNamespace(active=self.root)),
                mode="OBJECT",
            )

            mock_mesh = MagicMock()
            mock_mesh.used_materials.return_value = []
            mock_meta = {
                "level_name": "TestWorld",
                "version_name": "1.21.4",
                "data_version": 4189,
                "spawn": (0, 64, 0),
            }

            captured_args = {}

            def fake_load_and_mesh(**kwargs):
                captured_args.update(kwargs)
                return mock_mesh, mock_meta, MagicMock(), 10.0

            with patch("MoziToolKit.operators.save.op_refresh_save.can_execute_asset_pipeline", return_value=(True, "")), \
                 patch("MoziToolKit.operators.save.op_refresh_save.check_asset_cache_status", return_value="READY"), \
                 patch("MoziToolKit.operators.save.op_refresh_save.load_and_mesh_minecraft_save", side_effect=fake_load_and_mesh), \
                 patch("MoziToolKit.utils.save.hierarchy.inject_mesh_data"), \
                 patch("MoziToolKit.utils.save.hierarchy.ensure_world_materials"):
                res = op.execute(ctx)
                self.assertEqual(res, {"FINISHED"})

            # Verify that load_and_mesh_minecraft_save received the updated parameters
            self.assertEqual(captured_args["dimension"], "the_end")
            self.assertEqual(captured_args["min_block"], (-10, 0, -10))
            self.assertEqual(captured_args["max_block"], (10, 50, 10))
            self.assertFalse(captured_args["enable_ao"])

            # Verify that custom properties were updated and dirty flag cleared
            self.assertEqual(self.root["mtk_min_coord"], [-10, 0, -10])
            self.assertEqual(self.root["mtk_max_coord"], [10, 50, 10])
            self.assertEqual(self.root["mtk_dimension"], "the_end")
            self.assertFalse(props.is_dirty)

    def test_ui_panel_rendering_collapsed_and_expanded(self):
        """Verifies _draw_save_container_ui draws collapsible settings and dirty notices."""
        tmp_path = Path(self.tmp_reg_dir.name) / "World"
        tmp_path.mkdir(exist_ok=True)
        (tmp_path / "level.dat").write_text("dummy")
        reg = get_save_registry()
        reg.relink_save("uuid-save-101", tmp_path)

        layout = _MockLayout()
        ctx = types.SimpleNamespace(active_object=self.root)

        # 1. Collapsed state
        props = get_save_properties(self.root)
        props.show_rebuild_settings = False
        props.is_dirty = False
        _draw_save_container_ui(layout, ctx)

        prop_names = [p[1] for p in layout.all_props()]
        self.assertIn("show_rebuild_settings", prop_names)
        self.assertNotIn("dimension", prop_names)

        # 2. Expanded and dirty state
        layout2 = _MockLayout()
        props.show_rebuild_settings = True
        props.is_dirty = True
        _draw_save_container_ui(layout2, ctx)

        prop_names2 = [p[1] for p in layout2.all_props()]
        self.assertIn("dimension", prop_names2)
        self.assertIn("min_coord", prop_names2)
        self.assertIn("max_coord", prop_names2)
        self.assertIn("enable_ao", prop_names2)
        self.assertIn("mesh_fluids", prop_names2)
        self.assertIn("weld_vertices", prop_names2)
        self.assertIn("origin_centered", prop_names2)
        self.assertIn("enable_ctm", prop_names2)
        self.assertIn("enable_animated_textures", prop_names2)

        op_ids = [op[0] for op in layout2.all_operators()]
        self.assertIn("mozi.save_reset_settings", op_ids)
        self.assertIn("mozi.refresh_save_mesh", op_ids)


if __name__ == "__main__":
    unittest.main()
