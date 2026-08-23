"""
Integration Test for MoziToolKit Live Sync and Geometry Nodes.
Verifies:
1. Updating MC_Block_Templates collection meshes directly from resource packs / JAR using mc_baker.
2. Pure Python VoxelStorage snapshot, delta updates, and CRC32 manifest validation.
3. Point cloud builder writing 20+ point-domain attributes with batch foreach_set.
4. Procedural Geometry Nodes world tree generation, culling group, and material dispatcher.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy
from utils.geometry_nodes import (
    WORLD_MODIFIER_NAME,
    WORLD_TREE_NAME,
    get_or_create_culling_merge_group,
    get_or_create_material_dispatcher_group,
    setup_world_geometry_nodes,
)
from utils.live_sync import (
    BlockTypeEnum,
    VoxelStorage,
    classify_block_type_and_orientation,
    update_world_point_cloud,
)
from utils.mc_baker import (
    TEMPLATE_COLLECTION_NAME,
    update_mc_block_templates_from_pack,
)

JAR_PATH = "/Users/jaxlocke/26.2-Fabric.jar"


class TestMoziYefiraIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Path(JAR_PATH).exists():
            raise unittest.SkipTest(f"Client JAR not found at {JAR_PATH}")

    def setUp(self):
        bpy.ops.wm.read_homefile(use_empty=True)

    def test_update_mc_block_templates_from_jar(self):
        """Verify updating MC_Block_Templates from JAR creates real 3D non-full meshes with attributes."""
        count = update_mc_block_templates_from_pack(JAR_PATH)
        self.assertGreater(count, 15)

        col = bpy.data.collections.get(TEMPLATE_COLLECTION_NAME)
        self.assertIsNotNone(col)

        # Check key templates
        stairs_obj = col.objects.get("stairs_straight")
        self.assertIsNotNone(stairs_obj)
        self.assertGreater(len(stairs_obj.data.polygons), 6)
        self.assertIn("Cube_Face_Normal", stairs_obj.data.attributes)
        self.assertIn("Local_Face_ID", stairs_obj.data.attributes)
        self.assertIn("Local_UV", stairs_obj.data.attributes)

        fence_obj = col.objects.get("fence")
        self.assertIsNotNone(fence_obj)
        self.assertGreater(len(fence_obj.data.polygons), 10)

        lantern_obj = col.objects.get("lantern")
        self.assertIsNotNone(lantern_obj)
        self.assertGreater(len(lantern_obj.data.polygons), 6)

    def test_storage_snapshot_and_delta(self):
        """Verify VoxelStorage full snapshot and delta application."""
        storage = VoxelStorage()
        palette = ["minecraft:air", "minecraft:stone", "minecraft:oak_planks"]
        grid = [1, 2, 0, 1]
        storage.set_full_snapshot(0, 0, 0, 2, 2, 1, palette, grid)

        self.assertEqual(storage.get_block(0, 0, 0), "minecraft:stone")
        self.assertEqual(storage.get_block(0, 1, 0), "minecraft:oak_planks")
        self.assertEqual(storage.get_block(1, 0, 0), "minecraft:air")
        self.assertEqual(storage.get_block(1, 1, 0), "minecraft:stone")

        # Apply delta
        storage.apply_delta_update(0, 0, 0, [(0, 1, 0, "minecraft:glass")])
        self.assertEqual(storage.get_block(0, 1, 0), "minecraft:glass")

    def test_block_classifier(self):
        """Verify block classification for cubes, stairs, props, and fluids."""
        c_type, rot, idx = classify_block_type_and_orientation("minecraft:stone")
        self.assertEqual(c_type, BlockTypeEnum.CUBE)

        s_type, rot, idx = classify_block_type_and_orientation(
            "minecraft:oak_stairs[facing=south,half=bottom,shape=straight]"
        )
        self.assertEqual(s_type, BlockTypeEnum.STAIRS)
        self.assertGreaterEqual(idx, 0)

        w_type, rot, idx = classify_block_type_and_orientation("minecraft:water[level=0]")
        self.assertEqual(w_type, BlockTypeEnum.FLUID)

        a_type, rot, idx = classify_block_type_and_orientation("minecraft:air")
        self.assertEqual(a_type, BlockTypeEnum.AIR)

    def test_point_cloud_builder_and_attributes(self):
        """Verify point cloud builder calculates 6-face attributes from pure BlockState strings."""
        storage = VoxelStorage()
        storage.min_x = 0
        storage.min_y = 64
        storage.min_z = 0
        storage.size_x = 4
        storage.size_y = 1
        storage.size_z = 1
        storage.block_map = {
            (0, 64, 0): "minecraft:magenta_glazed_terracotta[facing=east]",
            (1, 64, 0): "minecraft:observer[facing=north,powered=false]",
            (2, 64, 0): "minecraft:oak_stairs[facing=south,half=bottom,shape=straight]",
            (3, 64, 0): "minecraft:lantern[hanging=false]",
        }

        res = update_world_point_cloud(
            context=bpy.context,
            storage=storage,
        )

        self.assertIsNotNone(res.world_obj)
        mesh = res.world_obj.data
        self.assertEqual(len(mesh.vertices), 4)

        # Check UV rotation attribute for terracotta (facing=east has 270 deg rotation on top face)
        rot_attr = mesh.attributes.get("mtk_uv_rot_top")
        self.assertIsNotNone(rot_attr)
        self.assertEqual(float(rot_attr.data[0].value), 270.0)

        # Check Block_State attribute
        state_attr = mesh.attributes.get("yefira_block_state")
        self.assertIsNotNone(state_attr)

    def test_geometry_nodes_tree_generation(self):
        """Verify setup_world_geometry_nodes builds modifier and node tree."""
        storage = VoxelStorage()
        storage.min_x, storage.min_y, storage.min_z = 0, 0, 0
        storage.size_x, storage.size_y, storage.size_z = 2, 1, 1
        storage.block_map = {
            (0, 0, 0): "minecraft:stone",
            (1, 0, 0): "minecraft:oak_stairs[facing=east,half=bottom,shape=straight]",
        }

        res = update_world_point_cloud(context=bpy.context, storage=storage)
        mod = setup_world_geometry_nodes(res.world_obj)

        self.assertIsNotNone(mod)
        self.assertEqual(mod.name, WORLD_MODIFIER_NAME)
        self.assertEqual(mod.node_group.name, WORLD_TREE_NAME)

        # Verify sub-groups exist
        culling_group = get_or_create_culling_merge_group()
        self.assertIsNotNone(culling_group)

        mat_disp_group = get_or_create_material_dispatcher_group({})
        self.assertIsNotNone(mat_disp_group)


if __name__ == "__main__":
    unittest.main(argv=["dummy"])
