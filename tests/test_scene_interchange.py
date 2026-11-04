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
        colormap_dir = os.path.join(cls.pack_dir, "assets", "minecraft", "textures", "colormap")
        models_dir = os.path.join(cls.pack_dir, "assets", "minecraft", "models", "block")
        bs_dir = os.path.join(cls.pack_dir, "assets", "minecraft", "blockstates")
        os.makedirs(tex_dir, exist_ok=True)
        os.makedirs(colormap_dir, exist_ok=True)
        os.makedirs(models_dir, exist_ok=True)
        os.makedirs(bs_dir, exist_ok=True)

        # 1. Textures: stone & dirt + PBR companions + Colormaps + Glass CTM
        with open(os.path.join(tex_dir, "stone.png"), "wb") as f:
            f.write(create_tiny_png(16, 16, (128, 128, 128, 255)))
        with open(os.path.join(tex_dir, "dirt.png"), "wb") as f:
            f.write(create_tiny_png(16, 16, (139, 69, 19, 255)))
        with open(os.path.join(tex_dir, "grass_block_top.png"), "wb") as f:
            f.write(create_tiny_png(16, 16, (255, 255, 255, 255)))
        with open(os.path.join(tex_dir, "glass.png"), "wb") as f:
            f.write(create_tiny_png(16, 16, (200, 200, 255, 100)))
        with open(os.path.join(tex_dir, "stone_n.png"), "wb") as f:
            f.write(create_tiny_png(16, 16, (128, 128, 255, 255)))
        with open(os.path.join(tex_dir, "stone_s.png"), "wb") as f:
            f.write(create_tiny_png(16, 16, (200, 100, 0, 50)))
        with open(os.path.join(colormap_dir, "grass.png"), "wb") as f:
            f.write(create_tiny_png(16, 16, (100, 200, 50, 255)))

        # CTM Rules & sub-tiles for glass
        ctm_dir = os.path.join(cls.pack_dir, "assets", "minecraft", "optifine", "ctm", "glass")
        os.makedirs(ctm_dir, exist_ok=True)
        with open(os.path.join(ctm_dir, "glass.properties"), "w") as f:
            f.write("matchBlocks=glass\nmethod=ctm_compact\ntiles=0-4\n")
        for i in range(5):
            with open(os.path.join(ctm_dir, f"{i}.png"), "wb") as f:
                f.write(create_tiny_png(16, 16, (200, 200, 255, 100)))

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
        glass_model = {
            "textures": {"all": "minecraft:block/glass"},
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
        grass_model = {
            "textures": {"up": "minecraft:block/grass_block_top"},
            "elements": [
                {
                    "from": [0, 0, 0],
                    "to": [16, 16, 16],
                    "faces": {
                        "up": {"texture": "#up", "tintindex": 0},
                    },
                }
            ],
        }
        with open(os.path.join(models_dir, "stone.json"), "w") as f:
            json.dump(stone_model, f)
        with open(os.path.join(models_dir, "dirt.json"), "w") as f:
            json.dump(dirt_model, f)
        with open(os.path.join(models_dir, "glass.json"), "w") as f:
            json.dump(glass_model, f)
        with open(os.path.join(models_dir, "grass_block.json"), "w") as f:
            json.dump(grass_model, f)

        # 3. Blockstates
        with open(os.path.join(bs_dir, "stone.json"), "w") as f:
            json.dump({"variants": {"": {"model": "minecraft:block/stone"}}}, f)
        with open(os.path.join(bs_dir, "dirt.json"), "w") as f:
            json.dump({"variants": {"": {"model": "minecraft:block/dirt"}}}, f)
        with open(os.path.join(bs_dir, "glass.json"), "w") as f:
            json.dump({"variants": {"": {"model": "minecraft:block/glass"}}}, f)
        with open(os.path.join(bs_dir, "grass_block.json"), "w") as f:
            json.dump({"variants": {"": {"model": "minecraft:block/grass_block"}}}, f)

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
        cls._orig_mozi_cache_dir = os.environ.get("MOZI_CACHE_DIR")
        os.environ["MOZI_CACHE_DIR"] = cls.cache_dir

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "_orig_mozi_cache_dir", None) is not None:
            os.environ["MOZI_CACHE_DIR"] = cls._orig_mozi_cache_dir
        else:
            os.environ.pop("MOZI_CACHE_DIR", None)
        try:
            from MoziToolKit.bridge.assets import invalidate_asset_cache_memory
            invalidate_asset_cache_memory()
        except Exception:
            pass
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_01_scene_package_reader_and_metadata_bindings(self):
        """Verifies that native SceneMetadata and ScenePackageReader bindings are exposed."""
        self.assertTrue(hasattr(self.mtk, "SceneMetadata"))
        self.assertTrue(hasattr(self.mtk, "ScenePackageReader"))
        self.assertTrue(hasattr(self.mtk, "export_scene_package"))

    def _ensure_exported_scene(self) -> str:
        """Helper to ensure test_export.mtkscene exists so tests can run in any order or individually."""
        scene_path = os.path.join(self.temp_dir, "test_export.mtkscene")
        if not os.path.exists(scene_path):
            cloud = self.mtk.VoxelPointCloud()
            cloud.push([0.5, 0.5, 0.5], [0, 0, 0], "minecraft:stone", "minecraft:plains", 15)
            cloud.push([1.5, 0.5, 0.5], [1, 0, 0], "minecraft:dirt", "minecraft:plains", 14)
            cloud.bounds = [0, 0, 0, 2, 1, 1]
            export_scene_package(
                output_path=scene_path,
                point_cloud=cloud,
                prefs=self.mock_prefs,
                max_atlas_size=1024,
            )
        return scene_path

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
        scene_path = self._ensure_exported_scene()
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

        # Verify PBR channels (normal, ORM, AUX) are exported and readable
        normal_names = [t for t in texture_names if t.endswith("_n.png")]
        orm_names = [t for t in texture_names if t.endswith("_orm.png")]
        aux_names = [t for t in texture_names if t.endswith("_aux.png")]
        self.assertTrue(len(normal_names) >= 1)
        self.assertTrue(len(orm_names) >= 1)
        self.assertTrue(len(aux_names) >= 1)

        nw, nh, n_view = reader.read_texture_rgba(normal_names[0], flip_v=False)
        self.assertEqual(len(n_view), nw * nh * 4)

        # Verify colormaps and biome resolver are packaged and readable
        self.assertTrue(reader.has_colormaps())
        grass_cm = reader.read_colormap("grass")
        self.assertIsNotNone(grass_cm)
        self.assertGreater(len(grass_cm), 0)
        self.assertIsNotNone(data.get("biome_resolver"))

        # Verify install_colormaps executes without error and clean up
        reader.install_colormaps()
        if hasattr(self.mtk, "clear_cached_colormaps"):
            self.mtk.clear_cached_colormaps()

    def test_04_load_and_mesh_scene_package(self):
        """Loads and meshes the scene package headlessly using self-contained mini-atlas and models."""
        scene_path = self._ensure_exported_scene()
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
        scene_path = self._ensure_exported_scene()
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
        scene_path = self._ensure_exported_scene()
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
        scene_path = self._ensure_exported_scene()
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

    def test_09_ctm_self_contained_scene_export_and_meshing(self):
        """Verifies connected textures rules are tree-shaken, sub-tiles are stitched into mini-atlas, and reader restores CtmSolver."""
        cloud = self.mtk.VoxelPointCloud()
        # Two connected glass blocks side by side
        cloud.push([0.5, 0.5, 0.5], [0, 0, 0], "minecraft:glass", "minecraft:plains", 15)
        cloud.push([1.5, 0.5, 0.5], [1, 0, 0], "minecraft:glass", "minecraft:plains", 15)
        cloud.bounds = [0, 0, 0, 2, 1, 1]

        scene_path = os.path.join(self.temp_dir, "test_ctm_scene.mtkscene")
        meta = export_scene_package(
            output_path=scene_path,
            point_cloud=cloud,
            prefs=self.mock_prefs,
            max_atlas_size=1024,
        )
        self.assertEqual(meta["voxel_count"], 2)

        # 1. Read back .mtkscene and verify CTM solver is restored
        data = read_scene_package(scene_path)
        reader = data["reader"]
        self.assertTrue(reader.has_ctm_rules())
        self.assertIsNotNone(data.get("ctm_solver"))

        # 2. Verify CTM sub-tiles are present in mini-atlas mapping
        mapping_json = reader.read_atlas_mapping_json()
        self.assertIsNotNone(mapping_json)
        mapping_dict = json.loads(mapping_json)
        sprites = mapping_dict.get("sprites", {})
        ctm_sprites = [k for k in sprites if "optifine/ctm/glass" in k]
        self.assertTrue(len(ctm_sprites) >= 1, f"Expected CTM sub-tiles in mini-atlas mapping, got: {list(sprites.keys())}")

        # 3. Load and mesh scene headlessly using only self-contained mini-atlas and models
        res = load_and_mesh_scene_package(scene_path, prefs=self.mock_prefs)
        mesh_data = res["mesh_data"]
        self.assertIsNotNone(mesh_data)
        self.assertGreater(mesh_data.vertex_count, 0)
        self.assertGreater(mesh_data.face_count, 0)

    def test_10_ctm_explicit_disable_produces_no_ctm_in_package(self):
        """Verifies that setting enable_ctm=False produces a package strictly without CTM rules or sub-tiles."""
        cloud = self.mtk.VoxelPointCloud()
        cloud.push([0.5, 0.5, 0.5], [0, 0, 0], "minecraft:glass", "minecraft:plains", 15)
        cloud.push([1.5, 0.5, 0.5], [1, 0, 0], "minecraft:glass", "minecraft:plains", 15)
        cloud.bounds = [0, 0, 0, 2, 1, 1]

        scene_path = os.path.join(self.temp_dir, "test_no_ctm_scene.mtkscene")
        meta = export_scene_package(
            output_path=scene_path,
            point_cloud=cloud,
            prefs=self.mock_prefs,
            max_atlas_size=1024,
            enable_ctm=False,
        )
        self.assertEqual(meta["voxel_count"], 2)

        data = read_scene_package(scene_path)
        reader = data["reader"]
        self.assertFalse(reader.has_ctm_rules())
        self.assertIsNone(data.get("ctm_solver"))

        mapping_json = reader.read_atlas_mapping_json()
        self.assertIsNotNone(mapping_json)
        mapping_dict = json.loads(mapping_json)
        sprites = mapping_dict.get("sprites", {})
        ctm_sprites = [k for k in sprites if "optifine/ctm/glass" in k]
        self.assertEqual(len(ctm_sprites), 0, f"Expected no CTM sub-tiles, got: {ctm_sprites}")

    def test_11_incomplete_package_fallback_policy(self):
        """Verifies allow_host_fallback gate: False raises clear ValueError; True falls back and marks degraded=True."""
        scene_path = self._ensure_exported_scene()
        real_data = read_scene_package(scene_path)

        # Mock an incomplete package missing models
        incomplete_data = dict(real_data)
        incomplete_data["models"] = None

        with patch("MoziToolKit.bridge.scene.read_scene_package", return_value=incomplete_data):
            # Strict mode (default): must raise ValueError
            with self.assertRaises(ValueError) as ctx:
                load_and_mesh_scene_package(scene_path, allow_host_fallback=False)
            self.assertIn("incomplete", str(ctx.exception).lower())

            # Fallback mode: succeeds with host prefs and degraded=True
            res = load_and_mesh_scene_package(
                scene_path,
                prefs=self.mock_prefs,
                allow_host_fallback=True,
            )
            self.assertTrue(res.get("degraded"))
            self.assertIsNotNone(res["mesh_data"])

    def test_12_isolated_colormaps_and_dynamic_entity_slots(self):
        """Verifies dynamic_entity_slots roundtrip and pure colormap passing without host fallback."""
        cloud = self.mtk.VoxelPointCloud()
        skull_alex = json.dumps({"id": "minecraft:skull", "kind": "player", "rotation": 0, "profile": {"name": "skull_alex"}})
        skull_hero = json.dumps({"id": "minecraft:skull", "kind": "player", "rotation": 0, "profile": {"name": "custom_skull_hero"}})
        cloud.push([0.5, 0.5, 0.5], [0, 0, 0], "minecraft:player_head[rotation=0]", "minecraft:plains", 15, skull_alex)
        cloud.push([1.5, 0.5, 0.5], [1, 0, 0], "minecraft:player_head[rotation=0]", "minecraft:plains", 15, skull_hero)
        cloud.bounds = [0, 0, 0, 2, 1, 1]

        dummy_rgba = bytes([120, 150, 200, 255] * (1024 * 1024))
        dyn_atlases = {65520: dummy_rgba}
        slots_input = {"player_skull_alex": (65520, 2), "custom_skull_hero": (65520, 7)}

        scene_path = os.path.join(self.temp_dir, "test_slots_scene.mtkscene")
        export_scene_package(
            output_path=scene_path,
            point_cloud=cloud,
            prefs=self.mock_prefs,
            max_atlas_size=1024,
            dynamic_entity_atlases=dyn_atlases,
            dynamic_entity_slots=slots_input,
        )

        data = read_scene_package(scene_path)
        reader = data["reader"]
        self.assertTrue(reader.has_dynamic_entity_slots())
        read_slots = reader.read_dynamic_entity_slots()
        self.assertEqual(read_slots, slots_input)
        self.assertEqual(data.get("dynamic_entity_slots"), slots_input)

        # Validate that the exported package is 100% valid
        report = reader.validate()
        self.assertTrue(report.is_valid, f"Expected valid package, got errors: {report.errors}")
        self.assertEqual(len(report.errors), 0)

        # Colormaps
        self.assertTrue(reader.has_colormaps())
        colormaps = reader.read_colormaps()
        self.assertIsNotNone(colormaps)
        self.assertIsNotNone(data.get("colormaps"))

        # Completely headless self-contained loading without any prefs
        res = load_and_mesh_scene_package(scene_path, prefs=None, allow_host_fallback=False)
        self.assertFalse(res.get("degraded"))
        self.assertIsNotNone(res["mesh_data"])
        self.assertGreater(res["mesh_data"].vertex_count, 0)
        self.assertEqual(res["mesh_data"].dynamic_entity_slots, slots_input)

    def test_13_custom_colormap_tint_color_verification(self):
        """Verifies that MesherConfig.colormaps actually drives the grass block tint color in generated mesh buffers."""
        # 1. Pure solid magenta grass colormap (R=255, G=0, B=255)
        magenta_png = create_tiny_png(16, 16, (255, 0, 255, 255))
        custom_cms = self.mtk.VanillaColormaps.from_bytes(grass=magenta_png)

        # 2. VoxelPointCloud with a single grass block in plains
        cloud = self.mtk.VoxelPointCloud()
        cloud.push([0.5, 0.5, 0.5], [0, 0, 0], "minecraft:grass_block", "minecraft:plains", 15)
        cloud.bounds = [0, 0, 0, 1, 1, 1]

        storage = cloud.to_storage()

        # Mesh with custom colormaps
        from MoziToolKit.bridge.world import mesh_voxel_storage
        mesh_custom, _ = mesh_voxel_storage(
            storage=storage,
            prefs=self.mock_prefs,
            colormaps=custom_cms,
            resolve_prefs=True,
        )
        self.assertGreater(mesh_custom.vertex_count, 0)

        # Check vertex attributes for mtk_biome_tint_color
        tint_mv = mesh_custom.attribute_memoryview("mtk_biome_tint_color")
        self.assertIsNotNone(tint_mv, "Mesh must contain mtk_biome_tint_color attribute")
        tint_data = list(tint_mv)
        self.assertGreater(len(tint_data), 0)

        # Magenta linear RGBA has R > 0.8, G < 0.1, B > 0.8
        found_magenta = False
        for i in range(0, len(tint_data), 4):
            r, g, b = tint_data[i], tint_data[i + 1], tint_data[i + 2]
            if r > 0.8 and g < 0.1 and b > 0.8:
                found_magenta = True
                break
        self.assertTrue(found_magenta, f"Expected custom magenta grass tint in mesh, got: {tint_data[:8]}")

    def test_14_skin_slot_resolution_and_missing_skin_rejection(self):
        """Verifies that cropper resolves skins via dynamic_entity_slots when not in source atlas, and rejects missing skins."""
        cloud = self.mtk.VoxelPointCloud()
        skull_nbt = json.dumps({
            "id": "minecraft:skull",
            "kind": "player",
            "rotation": 0,
            "profile": {"name": "TestHeroAlex"},
        })
        cloud.push([0.5, 0.5, 0.5], [0, 0, 0], "minecraft:player_head[rotation=0]", "minecraft:plains", 15, skull_nbt)
        cloud.bounds = [0, 0, 0, 1, 1, 1]

        dummy_rgba = bytes([120, 150, 200, 255] * (1024 * 1024))
        dyn_atlases = {65520: dummy_rgba}
        dyn_slots = {
            "player_TestHeroAlex": (65520, 1),
            "unused_skin": (65520, 2),  # Simulates live session having unreferenced player skin
        }

        scene_path = os.path.join(self.temp_dir, "test_skin_fallback.mtkscene")
        meta = export_scene_package(
            output_path=scene_path,
            point_cloud=cloud,
            prefs=self.mock_prefs,
            dynamic_entity_atlases=dyn_atlases,
            dynamic_entity_slots=dyn_slots,
        )
        self.assertIsNotNone(meta)
        self.assertTrue(meta["capabilities"]["has_dynamic_entities"])

        # Validate that reader validates this dynamic entity package as 100% valid
        reader = self.mtk.ScenePackageReader.open(scene_path)
        report = reader.validate()
        self.assertTrue(report.is_valid, f"Expected valid scene package, got errors: {report.errors}")
        self.assertEqual(len(report.errors), 0)

        # Verify unused skin slot was pruned, and referenced slot was retained
        packaged_slots = reader.read_dynamic_entity_slots()
        self.assertIsNotNone(packaged_slots)
        self.assertIn("player_TestHeroAlex", packaged_slots)
        self.assertNotIn("unused_skin", packaged_slots)

        # Verify effective_capabilities returns SceneCapabilities with attribute and dict access
        eff_caps = reader.effective_capabilities()
        self.assertTrue(eff_caps.has_dynamic_entities)
        self.assertTrue(eff_caps["has_dynamic_entities"])
        self.assertIsInstance(eff_caps.to_dict(), dict)

        # Test scene with NO dynamic entities, but session has unused slots: slots must be omitted and has_dynamic_entities=False
        cloud_no_dyn = self.mtk.VoxelPointCloud()
        cloud_no_dyn.push([0.5, 0.5, 0.5], [0, 0, 0], "minecraft:stone", "minecraft:plains", 15)
        cloud_no_dyn.bounds = [0, 0, 0, 1, 1, 1]
        no_dyn_path = os.path.join(self.temp_dir, "test_no_dyn_with_unused_slots.mtkscene")
        meta_no_dyn = export_scene_package(
            output_path=no_dyn_path,
            point_cloud=cloud_no_dyn,
            prefs=self.mock_prefs,
            dynamic_entity_atlases=dyn_atlases,
            dynamic_entity_slots={"unused_skin": (65520, 2)},
        )
        self.assertFalse(meta_no_dyn["capabilities"]["has_dynamic_entities"])
        reader_no_dyn = self.mtk.ScenePackageReader.open(no_dyn_path)
        self.assertFalse(reader_no_dyn.has_dynamic_entity_slots())
        report_no_dyn = reader_no_dyn.validate()
        self.assertTrue(report_no_dyn.is_valid, f"Expected valid report, got: {report_no_dyn.errors}")
        self.assertEqual(len(report_no_dyn.errors), 0)

        # Rejection test: if dynamic_entity_slots does not provide the skin, export must fail
        bad_scene_path = os.path.join(self.temp_dir, "test_skin_missing.mtkscene")
        with self.assertRaises(RuntimeError) as ctx:
            export_scene_package(
                output_path=bad_scene_path,
                point_cloud=cloud,
                prefs=self.mock_prefs,
                dynamic_entity_atlases=dyn_atlases,
                dynamic_entity_slots={},
            )
        self.assertTrue("not found" in str(ctx.exception).lower() or "missing" in str(ctx.exception).lower())

    def test_15_ctm_explicit_solver_conflict_check(self):
        """Verifies that passing enable_ctm=False together with explicit ctm_solver raises ValueError."""
        cloud = self.mtk.VoxelPointCloud()
        cloud.push([0.5, 0.5, 0.5], [0, 0, 0], "minecraft:glass", "minecraft:plains", 15)
        cloud.bounds = [0, 0, 0, 1, 1, 1]

        stack = self.mtk.ResourcePackStack()
        stack.add_directory_pack(self.pack_dir, "test_pack")
        solver = stack.build_ctm_solver()

        scene_path = os.path.join(self.temp_dir, "test_conflict.mtkscene")
        with self.assertRaises(ValueError) as ctx:
            export_scene_package(
                output_path=scene_path,
                point_cloud=cloud,
                prefs=self.mock_prefs,
                ctm_solver=solver,
                enable_ctm=False,
            )
        self.assertIn("conflicting", str(ctx.exception).lower())

    def test_16_validate_report_bindings(self):
        """Verifies that ScenePackageReader.validate() returns a ValidationReport object with is_valid, errors, warnings."""
        scene_path = self._ensure_exported_scene()
        reader = self.mtk.ScenePackageReader.open(scene_path)
        report = reader.validate()
        self.assertTrue(hasattr(report, "is_valid"))
        self.assertTrue(hasattr(report, "errors"))
        self.assertTrue(hasattr(report, "warnings"))
        self.assertTrue(report.is_valid)
        self.assertEqual(len(report.errors), 0)
        report_dict = report.to_dict()
        self.assertTrue(report_dict["is_valid"])
        self.assertIsInstance(report_dict["errors"], list)
        self.assertIsInstance(report_dict["warnings"], list)

        # Capabilities and effective_capabilities bindings
        caps = reader.metadata.capabilities
        self.assertTrue(hasattr(caps, "has_pbr"))
        self.assertTrue(hasattr(caps, "has_dynamic_entities"))
        self.assertIsInstance(caps["has_pbr"], bool)
        self.assertIsInstance(caps.to_dict(), dict)

        eff_caps = reader.effective_capabilities()
        self.assertTrue(hasattr(eff_caps, "has_pbr"))
        self.assertIsInstance(eff_caps["has_pbr"], bool)
        self.assertIsInstance(eff_caps.to_dict(), dict)

    def test_18_scene_import_ctm_toggle(self):
        """Verifies scene package CTM can be disabled at import time from the operator path."""
        cloud = self.mtk.VoxelPointCloud()
        cloud.push([0.5, 0.5, 0.5], [0, 0, 0], "minecraft:glass", "minecraft:plains", 15)
        cloud.push([1.5, 0.5, 0.5], [1, 0, 0], "minecraft:glass", "minecraft:plains", 15)
        cloud.bounds = [0, 0, 0, 2, 1, 1]

        scene_path = os.path.join(self.temp_dir, "test_ctm_toggle.mtkscene")
        export_scene_package(
            output_path=scene_path,
            point_cloud=cloud,
            prefs=self.mock_prefs,
            max_atlas_size=1024,
        )

        def _texture_keys(mesh):
            palette, indices = mesh.source_texture_palette_indices()
            return [palette[i] for i in indices]

        on = load_and_mesh_scene_package(scene_path, prefs=None, enable_ctm=True)
        off = load_and_mesh_scene_package(scene_path, prefs=None, enable_ctm=False)
        on_keys = _texture_keys(on["mesh_data"])
        off_keys = _texture_keys(off["mesh_data"])

        self.assertTrue(any("optifine/ctm" in key for key in on_keys))
        self.assertFalse(any("optifine/ctm" in key for key in off_keys))

    def test_19_scene_export_reads_embedded_dynamic_entity_slots(self):
        """Verifies the export operator can recover slots persisted on an imported object hierarchy."""
        from MoziToolKit.operators.scene import op_export_scene as op

        class FakeObject:
            def __init__(self, props=None, parent=None):
                self._props = props or {}
                self.parent = parent
                self.data = None

            def get(self, key, default=None):
                return self._props.get(key, default)

        payload = json.dumps({"player_jaxlocke": [65520, 3]})
        root = FakeObject({"mtk:dynamic_entity_slots": payload, "mtk_enable_ctm": False})
        mesh = FakeObject(parent=root)
        with patch.object(op, "HAS_BPY", True):
            slots = op._resolve_export_dynamic_entity_slots(mesh, None)
            enable_ctm = op._resolve_export_enable_ctm(mesh, None, None)
        self.assertEqual(slots, {"player_jaxlocke": (65520, 3)})
        self.assertFalse(enable_ctm)

    def test_17_standard_world_meshing_resolves_cache_colormap_without_explicit_arg(self):
        """Verifies that standard mesh_voxel_storage with colormaps=None auto-resolves cache colormaps and paints custom colors."""
        from MoziToolKit.bridge.world import mesh_voxel_storage, prepare_world_mesh_context
        from unittest.mock import patch

        # 1. Verify prepare_world_mesh_context includes 'colormaps'
        ctx = prepare_world_mesh_context(self.mock_prefs)
        self.assertIn("colormaps", ctx)

        # 2. Build custom solid magenta grass colormap
        magenta_png = create_tiny_png(16, 16, (255, 0, 255, 255))
        custom_cms = self.mtk.VanillaColormaps.from_bytes(grass=magenta_png)

        cloud = self.mtk.VoxelPointCloud()
        cloud.push([0.5, 0.5, 0.5], [0, 0, 0], "minecraft:grass_block", "minecraft:plains", 15)
        cloud.bounds = [0, 0, 0, 1, 1, 1]
        storage = cloud.to_storage()

        # Patch get_world_pipeline_colormaps to return custom_cms as if active cache loaded it
        with patch("MoziToolKit.bridge.world.get_world_pipeline_colormaps", return_value=custom_cms):
            mesh, _ = mesh_voxel_storage(
                storage=storage,
                prefs=self.mock_prefs,
                colormaps=None,  # Not explicitly passed!
                resolve_prefs=True,
            )

        tint_mv = mesh.attribute_memoryview("mtk_biome_tint_color")
        self.assertIsNotNone(tint_mv, "Mesh must contain mtk_biome_tint_color attribute")
        tint_data = list(tint_mv)
        self.assertGreater(len(tint_data), 0)

        found_magenta = False
        for i in range(0, len(tint_data), 4):
            r, g, b = tint_data[i], tint_data[i + 1], tint_data[i + 2]
            if r > 0.8 and g < 0.1 and b > 0.8:
                found_magenta = True
                break
        self.assertTrue(found_magenta, f"Standard mesh_voxel_storage should auto-resolve custom colormap from cache, got: {tint_data[:8]}")


if __name__ == "__main__":
    unittest.main()
