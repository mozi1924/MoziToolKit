"""
Tests for Unknown Block Handling, Strategy Preferences, and .mtkscene Container Mesh Rebuilding.
Runs 100% inside real Blender 5.x LTS host environment with native bpy data structures.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import tempfile
import types
import unittest
import zlib
from pathlib import Path

import bpy

from MoziToolKit.bridge.assets import invalidate_asset_cache_memory
from MoziToolKit.bridge.engine import require_libmtk
from MoziToolKit.bridge.scene import export_scene_package, read_scene_package
from MoziToolKit.bridge.world import mesh_voxel_storage, scan_unknown_blocks
from MoziToolKit.operators.mesh.op_rebuild_mesh import (
    MOZI_OT_rebuild_mesh,
    resolve_mesh_rebuild_targets,
)
from MoziToolKit.utils.scene.hierarchy import apply_imported_scene_to_blender


def create_tiny_png(width: int = 16, height: int = 16, color: tuple = (255, 0, 0, 255)) -> bytes:
    """Creates a valid RGBA PNG using Python standard library."""
    r, g, b, a = color
    pixel = bytes([r, g, b, a])
    raw_data = bytearray()
    for _ in range(height):
        raw_data.append(0)
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


class TestUnknownBlocksAndSceneRebuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mtk = require_libmtk("test_unknown_blocks")
        cls.temp_dir = tempfile.mkdtemp(prefix="mtk_unknown_test_")
        cls.pack_dir = os.path.join(cls.temp_dir, "test_pack")
        cls.cache_dir = os.path.join(cls.temp_dir, "cache")
        os.makedirs(cls.cache_dir, exist_ok=True)

        tex_dir = os.path.join(cls.pack_dir, "assets", "minecraft", "textures", "block")
        models_dir = os.path.join(cls.pack_dir, "assets", "minecraft", "models", "block")
        bs_dir = os.path.join(cls.pack_dir, "assets", "minecraft", "blockstates")
        os.makedirs(tex_dir, exist_ok=True)
        os.makedirs(models_dir, exist_ok=True)
        os.makedirs(bs_dir, exist_ok=True)

        with open(os.path.join(tex_dir, "stone.png"), "wb") as f:
            f.write(create_tiny_png(16, 16, (128, 128, 128, 255)))

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
        with open(os.path.join(models_dir, "stone.json"), "w") as f:
            json.dump(stone_model, f)
        with open(os.path.join(bs_dir, "stone.json"), "w") as f:
            json.dump({"variants": {"": {"model": "minecraft:block/stone"}}}, f)

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

        pack_entry = types.SimpleNamespace(
            enabled=True,
            name="test_pack",
            path=cls.pack_dir,
        )
        cls.mock_prefs = types.SimpleNamespace(
            cache_dir=cls.cache_dir,
            resource_pack_path="",
            active_resource_pack_index=0,
            resource_packs=[pack_entry],
            thread_count=1,
            enable_animated_textures=True,
            unknown_block_strategy="FALLBACK_CUBE",
        )
        cls._orig_mozi_cache_dir = os.environ.get("MOZI_CACHE_DIR")
        os.environ["MOZI_CACHE_DIR"] = cls.cache_dir

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "_orig_mozi_cache_dir", None) is not None:
            os.environ["MOZI_CACHE_DIR"] = cls._orig_mozi_cache_dir
        else:
            os.environ.pop("MOZI_CACHE_DIR", None)
        try:
            invalidate_asset_cache_memory()
        except Exception:
            pass
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        self._created_objects: list[bpy.types.Object] = []
        self._created_meshes: list[bpy.types.Mesh] = []

    def tearDown(self):
        for obj in reversed(self._created_objects):
            try:
                if obj.name in bpy.data.objects:
                    bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass
        for mesh in reversed(self._created_meshes):
            try:
                if mesh.name in bpy.data.meshes:
                    bpy.data.meshes.remove(mesh)
            except Exception:
                pass

    def _track_obj(self, obj: bpy.types.Object) -> bpy.types.Object:
        self._created_objects.append(obj)
        return obj

    def _track_mesh(self, mesh: bpy.types.Mesh) -> bpy.types.Mesh:
        self._created_meshes.append(mesh)
        return mesh

    def test_01_scan_unknown_blocks_filters_placeholders_and_detects_unknowns(self):
        """Verifies that scan_unknown_blocks ignores air, fluids, placeholders, and skulls, and detects unknown blocks."""
        cloud = self.mtk.VoxelPointCloud()
        # Non-mesh / placeholders
        cloud.push([0.5, 0.5, 0.5], [0, 0, 0], "minecraft:air", "minecraft:plains", 15)
        cloud.push([1.5, 0.5, 0.5], [1, 0, 0], "minecraft:bubble_column", "minecraft:plains", 15)
        cloud.push([2.5, 0.5, 0.5], [2, 0, 0], "minecraft:light[level=15]", "minecraft:plains", 15)
        cloud.push([3.5, 0.5, 0.5], [3, 0, 0], "minecraft:barrier", "minecraft:plains", 15)
        cloud.push([4.5, 0.5, 0.5], [4, 0, 0], "minecraft:structure_void", "minecraft:plains", 15)
        # Fluid
        cloud.push([5.5, 0.5, 0.5], [5, 0, 0], "minecraft:water[level=0]", "minecraft:plains", 15)
        # Built-in entity
        cloud.push([6.5, 0.5, 0.5], [6, 0, 0], "minecraft:player_head[rotation=0]", "minecraft:plains", 15)
        # Truly unknown modded blocks
        cloud.push([7.5, 0.5, 0.5], [7, 0, 0], "custom_mod:magic_crystal", "minecraft:plains", 15)
        cloud.push([8.5, 0.5, 0.5], [8, 0, 0], "extra:super_ore[variant=ruby]", "minecraft:plains", 15)
        cloud.bounds = [0, 0, 0, 9, 1, 1]

        unknowns = scan_unknown_blocks(cloud, model_db=None, atlas=None, prefs=self.mock_prefs)
        self.assertEqual(len(unknowns), 2)
        self.assertIn("custom_mod:magic_crystal", unknowns)
        self.assertIn("extra:super_ore", unknowns)

    def test_02_unknown_block_strategy_fallback_cube_vs_ignore_air(self):
        """Verifies unknown_block_strategy creates 6 faces for FALLBACK_CUBE and 0 faces for IGNORE_AS_AIR."""
        cloud = self.mtk.VoxelPointCloud()
        cloud.push([0.5, 0.5, 0.5], [0, 0, 0], "unknown_mod:alien_block", "minecraft:plains", 15)
        cloud.bounds = [0, 0, 0, 1, 1, 1]
        storage = cloud.to_storage()

        # 1. FALLBACK_CUBE strategy
        mesh_fallback, _ = mesh_voxel_storage(
            storage=storage,
            resolve_prefs=False,
            unknown_block_strategy="FALLBACK_CUBE",
        )
        self.assertIsNotNone(mesh_fallback)
        self.assertEqual(mesh_fallback.quad_count, 6)

        # 2. IGNORE_AS_AIR strategy
        mesh_air, _ = mesh_voxel_storage(
            storage=storage,
            resolve_prefs=False,
            unknown_block_strategy="IGNORE_AS_AIR",
        )
        self.assertIsNotNone(mesh_air)
        self.assertEqual(mesh_air.quad_count, 0)

    def test_03_scene_container_mesh_rebuild_independent_of_vanilla_jar(self):
        """Verifies that an imported .mtkscene container can be rebuilt via mozi.rebuild_mesh without vanilla assets."""
        # 1. Create and export a standalone .mtkscene
        cloud = self.mtk.VoxelPointCloud()
        cloud.push([0.5, 0.5, 0.5], [0, 0, 0], "minecraft:stone", "minecraft:plains", 15)
        cloud.bounds = [0, 0, 0, 1, 1, 1]

        scene_path = os.path.join(self.temp_dir, "independent_rebuild.mtkscene")
        export_scene_package(
            output_path=scene_path,
            point_cloud=cloud,
            prefs=self.mock_prefs,
            max_atlas_size=1024,
        )

        data = read_scene_package(scene_path)
        data["scene_path"] = scene_path
        # Mesh geometry
        mesh_data, _ = mesh_voxel_storage(
            storage=cloud.to_storage(),
            model_db=data["models"],
            atlas=data["atlas"],
            resolve_prefs=False,
        )
        data["mesh_data"] = mesh_data

        # 2. Assemble in Blender
        res = apply_imported_scene_to_blender(data, scene_name="IndependentTest", prefs=self.mock_prefs)
        root_obj = self._track_obj(res["root_obj"])
        mesh_obj = self._track_obj(res["mesh_obj"])
        cloud_obj = self._track_obj(res["cloud_obj"])
        self._track_mesh(mesh_obj.data)
        self._track_mesh(cloud_obj.data)

        # Verify container metadata
        self.assertEqual(root_obj.get("mtk:container_type"), "SCENE")
        self.assertEqual(root_obj.get("mtk:scene_package_path"), scene_path)

        # 3. Create context targeting root_obj
        ctx = types.SimpleNamespace(
            active_object=root_obj,
            selected_objects=[root_obj],
            collection=bpy.context.scene.collection,
            window_manager=None,
            mode="OBJECT",
        )

        # Poll must succeed for SCENE containers even if can_execute_asset_pipeline fails
        self.assertTrue(MOZI_OT_rebuild_mesh.poll(ctx))

        # 4. Execute rebuild
        mock_op = types.SimpleNamespace(
            enable_ao=True,
            mesh_fluids=True,
            weld_vertices=True,
            origin_centered=True,
            run_async=False,
            force=False,
            report_calls=[],
            report=lambda level, msg: mock_op.report_calls.append((level, msg)),
        )

        ret = MOZI_OT_rebuild_mesh.execute(mock_op, ctx)
        self.assertEqual(ret, {"FINISHED"})
        # Verify polygons regenerated
        self.assertGreater(len(mesh_obj.data.polygons), 0)

    def test_04_rebuild_mesh_gate_on_unknown_blocks(self):
        """Verifies that rebuild_mesh halts when unknown blocks are present unless force=True."""
        # 1. Create a scene container with an unknown block in the companion point cloud
        cloud = self.mtk.VoxelPointCloud()
        cloud.push([0.5, 0.5, 0.5], [0, 0, 0], "unknown_space:dark_matter", "minecraft:plains", 15)
        cloud.bounds = [0, 0, 0, 1, 1, 1]

        scene_path = os.path.join(self.temp_dir, "unknown_rebuild.mtkscene")
        export_scene_package(
            output_path=scene_path,
            point_cloud=cloud,
            prefs=self.mock_prefs,
            max_atlas_size=1024,
        )

        data = read_scene_package(scene_path)
        data["scene_path"] = scene_path
        mesh_data, _ = mesh_voxel_storage(
            storage=cloud.to_storage(),
            model_db=data["models"],
            atlas=data["atlas"],
            resolve_prefs=False,
            unknown_block_strategy="FALLBACK_CUBE",
        )
        data["mesh_data"] = mesh_data

        res = apply_imported_scene_to_blender(data, scene_name="UnknownGateTest", prefs=self.mock_prefs)
        root_obj = self._track_obj(res["root_obj"])
        mesh_obj = self._track_obj(res["mesh_obj"])
        cloud_obj = self._track_obj(res["cloud_obj"])
        self._track_mesh(mesh_obj.data)
        self._track_mesh(cloud_obj.data)

        ctx = types.SimpleNamespace(
            active_object=root_obj,
            selected_objects=[root_obj],
            collection=bpy.context.scene.collection,
            window_manager=None,
            mode="OBJECT",
        )

        # Case A: force=False -> must cancel and report warning with block ID
        mock_op_no_force = types.SimpleNamespace(
            enable_ao=True,
            mesh_fluids=True,
            weld_vertices=True,
            origin_centered=True,
            run_async=False,
            force=False,
            report_calls=[],
            report=lambda level, msg: mock_op_no_force.report_calls.append((level, msg)),
        )
        ret_no_force = MOZI_OT_rebuild_mesh.execute(mock_op_no_force, ctx)
        self.assertEqual(ret_no_force, {"CANCELLED"})
        warn_msgs = [msg for lvl, msg in mock_op_no_force.report_calls if "WARNING" in lvl]
        self.assertTrue(any("unknown_space:dark_matter" in m for m in warn_msgs))

        # Case B: force=True -> must succeed and generate geometry
        mock_op_force = types.SimpleNamespace(
            enable_ao=True,
            mesh_fluids=True,
            weld_vertices=True,
            origin_centered=True,
            run_async=False,
            force=True,
            report_calls=[],
            report=lambda level, msg: mock_op_force.report_calls.append((level, msg)),
        )
        ret_force = MOZI_OT_rebuild_mesh.execute(mock_op_force, ctx)
        self.assertEqual(ret_force, {"FINISHED"})
        self.assertGreater(len(mesh_obj.data.polygons), 0)


if __name__ == "__main__":
    unittest.main()
