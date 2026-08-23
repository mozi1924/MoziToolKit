"""
Integration Test for MoziToolKit and Yefira Bridge.
Verifies:
1. Updating MC_Block_Templates collection meshes directly from resource packs / JAR using mc_baker.
2. Point cloud builder calculating 6-face attributes, UV rotations, and bounds natively in Python.
"""

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

YEFIRA_DIR = Path("/Volumes/Data/yefira/dcc_plugins/yefira_blender").resolve()
if str(YEFIRA_DIR.parent) not in sys.path:
    sys.path.insert(0, str(YEFIRA_DIR.parent))

import bpy
from utils.mc_baker import update_mc_block_templates_from_pack, TEMPLATE_COLLECTION_NAME
from yefira_blender.core.storage import VoxelStorage
from yefira_blender.core.point_cloud_builder import update_world_point_cloud

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

    def test_point_cloud_builder_native_mc_baker(self):
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


if __name__ == "__main__":
    unittest.main(argv=["dummy"])
