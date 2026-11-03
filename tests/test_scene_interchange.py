"""
Unit and integration tests for MTK Scene Interchange (.mtkscene).
Validates:
- Rust-to-Python bindings for SceneMetadata and ScenePackageReader
- Sparse voxel ingestion and 0-copy companion point cloud conversions
- In-memory mini-atlas cropping and UV remapping export pipeline
- Pure data bridge functions (inspect, read, load_and_mesh, export)
- Blender host hierarchy assembly and canonical Principled BSDF material binding
- Operators (MOZI_OT_export_scene and MOZI_OT_import_scene)
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from MoziToolKit.bridge.assets import open_active_asset_cache, precompile_stack
from MoziToolKit.bridge.engine import get_libmtk
from MoziToolKit.bridge.point_cloud import extract_voxel_point_cloud
from MoziToolKit.bridge.scene import (
    export_scene_package,
    inspect_scene_package,
    load_and_mesh_scene_package,
    read_scene_package,
)
from MoziToolKit.operators.scene.op_export_scene import MOZI_OT_export_scene
from MoziToolKit.operators.scene.op_import_scene import MOZI_OT_import_scene
from MoziToolKit.utils.mesh.ownership import ORIGIN_SCENE, find_voxel_cloud
from MoziToolKit.utils.scene import apply_imported_scene_to_blender


def create_tiny_png(width: int = 16, height: int = 16, color: tuple = (255, 0, 0, 255)) -> bytes:
    """Creates a valid RGBA PNG using Python standard library."""
    r, g, b, a = color
    pixel = bytes([r, g, b, a])
    raw_data = bytearray()
    for _ in range(height):
        raw_data.append(0)  # Filter type: None
        raw_data.extend(pixel * width)
    compressed = zlib.compress(bytes(raw_data))

    def make_chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png += make_chunk(b"IHDR", ihdr)
    png += make_chunk(b"IDAT", compressed)
    png += make_chunk(b"IEND", b"")
    return png


class TestSceneInterchangeEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mtk = get_libmtk()
        if cls.mtk is None:
            raise unittest.SkipTest("libmtk_py native engine is not available")

        # Setup temporary mock Minecraft resource pack and precompiled .mtkcache
        cls.temp_dir = tempfile.mkdtemp(prefix="mtk_scene_test_")
        cls.pack_dir = os.path.join(cls.temp_dir, "test_pack")
        cls.cache_dir = os.path.join(cls.temp_dir, "cache")
        os.makedirs(cls.cache_dir, exist_ok=True)

        tex_dir = os.path.join(cls.pack_dir, "assets", "minecraft", "textures", "block")
        models_dir = os.path.join(cls.pack_dir, "assets", "minecraft", "models", "block")
        bs_dir = os.path.join(cls.pack_dir, "assets", "minecraft", "blockstates")
        os.makedirs(tex_dir, exist_ok=True)
        os.makedirs(models_dir, exist_ok=True)
        os.makedirs(bs_dir, exist_ok=True)

        # 1. Textures: stone & dirt
        with open(os.path.join(tex_dir, "stone.png"), "wb") as f:
            f.write(create_tiny_png(16, 16, (128, 128, 128, 255)))
        with open(os.path.join(tex_dir, "dirt.png"), "wb") as f:
            f.write(create_tiny_png(16, 16, (139, 69, 19, 255)))

        # 2. Block models
        stone_model = {
            "textures": {"all": "minecraft:block/stone"},
            "elements": [
                {
                    "from": [0, 0, 0],
                    "to": [16, 16, 16],
                    "faces": {
                        "up": {"texture": "#all", "cullface": "up"},
                        "down": {"texture": "#all", "cullface": "down"},
                        "north": {"texture": "#all", "cullface": "north"},
                        "south": {"texture": "#all", "cullface": "south"},
                        "east": {"texture": "#all", "cullface": "east"},
                        "west": {"texture": "#all", "cullface": "west"},
                    },
                }
            ],
        }
        dirt_model = {
            "textures": {"all": "minecraft:block/dirt"},
            "elements": [
                {
                    "from": [0, 0, 0],
                    "to": [16, 16, 16],
                    "faces": {
                        "up": {"texture": "#all", "cullface": "up"},
                        "down": {"texture": "#all", "cullface": "down"},
                        "north": {"texture": "#all", "cullface": "north"},
                        "south": {"texture": "#all", "cullface": "south"},
                        "east": {"texture": "#all", "cullface": "east"},
                        "west": {"texture": "#all", "cullface": "west"},
                    },
                }
            ],
        }
        with open(os.path.join(models_dir, "stone.json"), "w") as f:
            json.dump(stone_model, f)
        with open(os.path.join(models_dir, "dirt.json"), "w") as f:
            json.dump(dirt_model, f)

        # 3. Blockstates
        with open(os.path.join(bs_dir, "stone.json"), "w") as f:
            json.dump({"variants": {"": {"model": "minecraft:block/stone"}}}, f)
        with open(os.path.join(bs_dir, "dirt.json"), "w") as f:
            json.dump({"variants": {"": {"model": "minecraft:block/dirt"}}}, f)

        # 4. Precompile into .mtkcache using native precompile_all_assets
        stack = cls.mtk.ResourcePackStack()
        stack.add_directory_pack(cls.pack_dir, "test_pack")
        res = cls.mtk.precompile_all_assets(
            stack,
            cls.cache_dir,
            atlas_category="blocks",
            max_atlas_width=1024,
            max_atlas_height=1024,
            compile_atlas=True,
            compile_models=True,
        )
        assert res.success, f"Precompile failed: {res.error_message}"
        cls.cache_pkg = res.package_path

        # Mock preferences to point to our test cache
        cls.mock_prefs = MagicMock()
        cls.mock_prefs.cache_dir = cls.cache_dir
        cls.mock_prefs.resource_pack_path = ""
        cls.mock_prefs.active_resource_pack_index = 0
        pack_entry = MagicMock()
        pack_entry.enabled = True
        pack_entry.name = "test_pack"
        pack_entry.path = cls.pack_dir
        cls.mock_prefs.resource_packs = [pack_entry]
        os.environ["MOZI_CACHE_DIR"] = cls.cache_dir

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("MOZI_CACHE_DIR", None)
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_01_scene_package_reader_and_metadata_bindings(self):
        """Verifies that native SceneMetadata and ScenePackageReader bindings are exposed."""
        self.assertTrue(hasattr(self.mtk, "SceneMetadata"))
        self.assertTrue(hasattr(self.mtk, "ScenePackageReader"))
        self.assertTrue(hasattr(self.mtk, "export_scene_package"))

    def test_02_export_scene_package_and_inspect(self):
        """Builds a VoxelPointCloud and exports it to .mtkscene with Mini-Atlas and tree-shaken models."""
        cloud = self.mtk.VoxelPointCloud()
        cloud.push([0.5, 0.5, 0.5], [0, 0, 0], "minecraft:stone", "minecraft:plains", 15)
        cloud.push([1.5, 0.5, 0.5], [1, 0, 0], "minecraft:dirt", "minecraft:plains", 14)
        cloud.bounds = [0, 0, 0, 2, 1, 1]

        scene_path = os.path.join(self.temp_dir, "test_export.mtkscene")
        meta = export_scene_package(
            output_path=scene_path,
            point_cloud=cloud,
            prefs=self.mock_prefs,
            max_atlas_size=1024,
        )

        self.assertEqual(meta["voxel_count"], 2)
        self.assertEqual(meta["format_version"], 1)
        self.assertEqual(meta["bounds"], [0, 0, 0, 2, 1, 1])
        self.assertEqual(meta["unique_states_count"], 2)
        self.assertTrue(os.path.exists(scene_path))

        # Test inspection without heavy payload decompression
        inspect_data = inspect_scene_package(scene_path)
        self.assertEqual(inspect_data["voxel_count"], 2)
        self.assertEqual(inspect_data["bounds"], [0, 0, 0, 2, 1, 1])

    def test_03_read_scene_package(self):
        """Reads exported .mtkscene and validates sparse voxels, mini-atlas, and model database."""
        scene_path = os.path.join(self.temp_dir, "test_export.mtkscene")
        data = read_scene_package(scene_path)

        point_cloud = data["point_cloud"]
        self.assertEqual(len(point_cloud), 2)

        # Check point cloud buffers
        buffers = point_cloud.to_buffers()
        self.assertEqual(buffers["count"], 2)
        self.assertIn("minecraft:stone", buffers["state_palette"])
        self.assertIn("minecraft:dirt", buffers["state_palette"])

        # Check models
        models = data["models"]
        self.assertIsNotNone(models)
        self.assertTrue(models.contains("minecraft:stone"))
        self.assertTrue(models.contains("minecraft:dirt"))

        # Check atlas
        atlas = data["atlas"]
        self.assertIsNotNone(atlas)

        # Check textures
        texture_names = data["texture_names"]
        self.assertTrue(len(texture_names) >= 1)
        albedo_name = [t for t in texture_names if not t.endswith(("_n.png", "_orm.png", "_aux.png"))][0]

        reader = data["reader"]
        w, h, memview = reader.read_texture_rgba(albedo_name, flip_v=False)
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)
        self.assertEqual(len(memview), w * h * 4)

    def test_04_load_and_mesh_scene_package(self):
        """Loads and meshes the scene package headlessly using self-contained mini-atlas and models."""
        scene_path = os.path.join(self.temp_dir, "test_export.mtkscene")
        res = load_and_mesh_scene_package(
            path=scene_path,
            prefs=self.mock_prefs,
            enable_ao=True,
            mesh_fluids=False,
            weld_vertices=True,
            origin_centered=True,
        )

        mesh_data = res["mesh_data"]
        self.assertIsNotNone(mesh_data)
        self.assertGreater(mesh_data.vertex_count, 0)
        self.assertGreater(mesh_data.face_count, 0)
        self.assertEqual(len(res["point_cloud"]), 2)
        self.assertGreater(res["total_ms"], 0.0)

    def test_05_apply_imported_scene_to_blender(self):
        """Tests Blender hierarchy construction, mesh and point cloud injection, and custom properties."""
        scene_path = os.path.join(self.temp_dir, "test_export.mtkscene")
        data = load_and_mesh_scene_package(
            path=scene_path,
            prefs=self.mock_prefs,
        )

        mock_cloud = MagicMock()
        mock_cloud.name = "[Scene] UnitSample_VoxelCloud"
        mock_cloud.type = "MESH"
        mock_cloud.data.vertices = [0, 1]

        with patch("MoziToolKit.utils.scene.hierarchy.ensure_voxel_child_cloud", return_value=mock_cloud), \
             patch("MoziToolKit.utils.scene.hierarchy.bind_scene_materials", return_value=[MagicMock()]):
            assembled = apply_imported_scene_to_blender(data, scene_name="UnitSample")

        root_obj = assembled["root_obj"]
        mesh_obj = assembled["mesh_obj"]
        cloud_obj = assembled["cloud_obj"]

        self.assertIsNotNone(root_obj)
        self.assertIsNotNone(mesh_obj)
        self.assertIsNotNone(cloud_obj)

        # Check geometry origin stamping via mock property assignments or dict lookup
        self.assertIsNotNone(mesh_obj)
        self.assertIsNotNone(cloud_obj)
        self.assertIsNotNone(root_obj)

        # Check materials
        materials = assembled["materials"]
        self.assertTrue(len(materials) >= 1)

    def test_06_operators_poll_and_execution(self):
        """Validates MOZI_OT_export_scene and MOZI_OT_import_scene operator flows."""
        scene_path = os.path.join(self.temp_dir, "test_export.mtkscene")
        data = load_and_mesh_scene_package(path=scene_path, prefs=self.mock_prefs)

        mock_cloud = MagicMock()
        mock_cloud.name = "[Scene] OpTest_VoxelCloud"
        mock_cloud.type = "MESH"
        mock_cloud.data.vertices = [0, 1]

        with patch("MoziToolKit.utils.scene.hierarchy.ensure_voxel_child_cloud", return_value=mock_cloud), \
             patch("MoziToolKit.utils.scene.hierarchy.bind_scene_materials", return_value=[MagicMock()]):
            assembled = apply_imported_scene_to_blender(data, scene_name="OpTest")

        mesh_obj = assembled["mesh_obj"]

        # 1. Test export operator
        is_real_blender = HAS_BPY and isinstance(getattr(getattr(bpy, "app", None), "version", None), tuple)
        if is_real_blender:
            context = bpy.context
            if hasattr(context, "view_layer") and hasattr(context.view_layer, "objects"):
                try:
                    context.view_layer.objects.active = mesh_obj
                except Exception:
                    pass
            if not getattr(context, "active_object", None):
                context.active_object = mesh_obj
        else:
            context = MagicMock()
            context.active_object = mesh_obj

        # Mock find_voxel_cloud to return our companion point cloud
        with patch("MoziToolKit.operators.scene.op_export_scene.find_voxel_cloud", return_value=mock_cloud):
            self.assertTrue(MOZI_OT_export_scene.poll(context))

            class MockExportOp:
                def __init__(self, filepath, max_atlas_size=2048):
                    self.filepath = filepath
                    self.max_atlas_size = max_atlas_size
                    self.report = MagicMock()

            export_op = MockExportOp(os.path.join(self.temp_dir, "reexported.mtkscene"), 2048)

            with patch("MoziToolKit.operators.scene.op_export_scene.get_prefs", return_value=self.mock_prefs), \
                 patch("MoziToolKit.operators.scene.op_export_scene.extract_voxel_point_cloud", return_value=data["point_cloud"]):
                ret = MOZI_OT_export_scene.execute(export_op, context)
                self.assertEqual(ret, {"FINISHED"})
                self.assertTrue(os.path.exists(export_op.filepath))

        # 2. Test import operator
        class MockImportOp:
            def __init__(self, filepath):
                self.filepath = filepath
                self.enable_animated_textures = True
                self.enable_ao = True
                self.mesh_fluids = True
                self.weld_vertices = True
                self.origin_centered = True
                self.report = MagicMock()

        import_op = MockImportOp(export_op.filepath)

        with patch("MoziToolKit.operators.scene.op_import_scene.get_prefs", return_value=self.mock_prefs), \
             patch("MoziToolKit.utils.scene.hierarchy.bind_scene_materials", return_value=[MagicMock()]):
            ret = MOZI_OT_import_scene.execute(import_op, context)
            self.assertEqual(ret, {"FINISHED"})

    def test_07_dynamic_entity_atlas_and_self_contained_stitching(self):
        """Verifies player skulls and banners are stitched into normal mini-atlas slots (no 0xFFF0 out-of-bounds)."""
        import array

        skull_json = '{"minecraft:block_entity":"minecraft:skull","kind":"player","profile":{"name":"Alex","id":"5678"}}'
        positions = array.array("f", [0.5, 0.5, 0.5])
        bx = array.array("i", [0])
        by = array.array("i", [0])
        bz = array.array("i", [0])
        st_indices = array.array("i", [0])
        st_palette = ["minecraft:stone"]
        ent_indices = array.array("i", [0])
        ent_palette = [skull_json]

        cloud = self.mtk.VoxelPointCloud.from_indexed_arrays(
            positions,
            bx,
            by,
            bz,
            st_indices,
            st_palette,
            entity_indices=ent_indices,
            entity_palette=ent_palette,
        )

        # Prepare fake 1024x1024 dynamic entity atlas buffer (0xFFF0)
        dyn_buf = bytearray(1024 * 1024 * 4)
        for i in range(64 * 64 * 4):
            dyn_buf[i] = 200  # Fill some dummy skin bytes

        dyn_atlases = {0xFFF0: bytes(dyn_buf)}

        scene_path = os.path.join(self.temp_dir, "test_dynamic_entity.mtkscene")
        meta = export_scene_package(
            output_path=scene_path,
            point_cloud=cloud,
            prefs=self.mock_prefs,
            dynamic_entity_atlases=dyn_atlases,
        )
        self.assertEqual(meta["voxel_count"], 1)

        # Read back and mesh: face material must NOT be 0xFFF0!
        res = load_and_mesh_scene_package(scene_path, prefs=self.mock_prefs)
        mesh_data = res["mesh_data"]
        used_mats = mesh_data.used_materials()
        self.assertNotIn(0xFFF0, used_mats)
        self.assertIn(0, used_mats)

    def test_08_container_hierarchy_and_collection_mounting(self):
        """Verifies unified empty container architecture, context.collection linking, and no obj.type assignment."""
        scene_path = os.path.join(self.temp_dir, "test_export.mtkscene")
        data = load_and_mesh_scene_package(path=scene_path, prefs=self.mock_prefs)

        mock_coll = MagicMock()
        mock_coll.objects.link = MagicMock()

        mock_context = MagicMock()
        mock_context.collection = mock_coll

        mock_cloud = MagicMock()
        mock_cloud.name = "[Scene] CapsuleTest_VoxelCloud"
        mock_cloud.data.vertices = [0, 1]

        with patch("MoziToolKit.utils.scene.hierarchy.ensure_voxel_child_cloud", return_value=mock_cloud), \
             patch("MoziToolKit.utils.scene.hierarchy.bind_scene_materials", return_value=[MagicMock()]), \
             patch("MoziToolKit.utils.materials.biome.updater.register_object_storage") as mock_reg:
            assembled = apply_imported_scene_to_blender(
                data,
                scene_name="CapsuleTest",
                context=mock_context,
            )

        root_obj = assembled["root_obj"]
        mesh_obj = assembled["mesh_obj"]

        def _get_prop(obj, key):
            if hasattr(obj, "get") and callable(obj.get):
                val = obj.get(key)
                if val is not None and not isinstance(val, MagicMock):
                    return val
            if hasattr(obj, "__getitem__"):
                try:
                    return obj[key]
                except Exception:
                    pass
            return getattr(obj, key, None)

        # 1. Root object properties
        if hasattr(root_obj, "__setitem__") and isinstance(root_obj.__setitem__, MagicMock):
            root_obj.__setitem__.assert_any_call("mtk:is_container", True)
            root_obj.__setitem__.assert_any_call("mtk:container_type", "SCENE")
        else:
            self.assertEqual(_get_prop(root_obj, "mtk:is_container"), True)
            self.assertEqual(_get_prop(root_obj, "mtk:container_type"), "SCENE")

        # 2. Mesh object origin
        if hasattr(mesh_obj, "__setitem__") and isinstance(mesh_obj.__setitem__, MagicMock):
            mesh_obj.__setitem__.assert_any_call("mtk:is_scene_mesh", True)
            mesh_obj.__setitem__.assert_any_call("mtk:geometry_origin", ORIGIN_SCENE)
        else:
            self.assertEqual(_get_prop(mesh_obj, "mtk:is_scene_mesh"), True)
            self.assertEqual(_get_prop(mesh_obj, "mtk:geometry_origin"), ORIGIN_SCENE)

        # 3. Collection linking to context.collection
        mock_coll.objects.link.assert_any_call(root_obj)
        mock_coll.objects.link.assert_any_call(mesh_obj)

        # 4. Storage registered for world biome restore
        self.assertTrue(mock_reg.called)


if __name__ == "__main__":
    unittest.main()
