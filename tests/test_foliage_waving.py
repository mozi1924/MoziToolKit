"""
Unit tests for Foliage Waving Pipeline, Vertex Groups, and Geo Nodes.
"""

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
PARENT_DIR = PROJECT_DIR.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy
from tests._bootstrap import bootstrap_environment
bootstrap_environment()

from MoziToolKit.utils.foliage import (
    classify_texture_key,
    assign_foliage_vertex_groups,
    GROUP_NAME_ALL,
    GROUP_NAME_LEAVES,
    GROUP_NAME_PLANTS,
    get_or_create_foliage_node_group,
    apply_foliage_modifier,
)
from MoziToolKit.pipeline.presets import run_preset_pipeline


class TestFoliageWaving(unittest.TestCase):

    def setUp(self):
        # Create test mesh with 2 disjoint components: leaves quad (0,1,2,3), plant quad (4,5,6,7), and log quad (8,9,10,11)
        mesh = bpy.data.meshes.new("TestFoliageMesh")
        verts = [
            # Leaves quad
            (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
            # Plant quad
            (2, 0, 0), (3, 0, 0), (3, 1, 0), (2, 1, 0),
            # Log quad
            (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
        ]
        faces = [
            (0, 1, 2, 3), # leaves
            (4, 5, 6, 7), # plant
            (8, 9, 10, 11), # log
        ]
        mesh.from_pydata(verts, [], faces)
        mesh.update()

        attr = mesh.attributes.new(name="mtk_source_texture_key", type='STRING', domain='FACE')
        keys = [
            b"minecraft:block/oak_leaves",
            b"minecraft:block/dandelion",
            b"minecraft:block/oak_log",
        ]
        for i, k in enumerate(keys):
            attr.data[i].value = k

        self.obj = bpy.data.objects.new("TestFoliageObj", mesh)
        bpy.context.scene.collection.objects.link(self.obj)
        bpy.context.view_layer.objects.active = self.obj
        self.obj.select_set(True)

    def tearDown(self):
        if self.obj and self.obj.name in bpy.data.objects:
            bpy.data.objects.remove(self.obj, do_unlink=True)

    def test_classifier(self):
        self.assertEqual(classify_texture_key("minecraft:block/oak_leaves"), "LEAF")
        self.assertEqual(classify_texture_key("minecraft:block/cherry_leaves"), "LEAF")
        self.assertEqual(classify_texture_key("minecraft:block/dandelion"), "PLANT")
        self.assertEqual(classify_texture_key("minecraft:block/poppy"), "PLANT")
        self.assertEqual(classify_texture_key("minecraft:block/fern"), "PLANT")
        # Excluded
        self.assertIsNone(classify_texture_key("minecraft:block/grass_block_top"))
        self.assertIsNone(classify_texture_key("minecraft:block/dirt_path_top"))
        self.assertIsNone(classify_texture_key("minecraft:block/oak_log"))

    def test_assign_vertex_groups(self):
        res = assign_foliage_vertex_groups(self.obj, protect_rigid_vertices=True)
        self.assertIn(GROUP_NAME_ALL, self.obj.vertex_groups)
        self.assertIn(GROUP_NAME_LEAVES, self.obj.vertex_groups)
        self.assertIn(GROUP_NAME_PLANTS, self.obj.vertex_groups)

    def test_pipeline_execution(self):
        res, ctx = run_preset_pipeline(
            "foliage_waving",
            bpy.context,
            params={
                "foliage_target_scope": "ALL",
                "wind_direction": 90.0,
                "wiggle_amplitude": 0.05,
                "wiggle_speed": 2.5,
                "noise_scale": 1.0,
            },
            target_objects=[self.obj]
        )
        self.assertTrue(res.is_success)
        # Check modifier
        mod = [m for m in self.obj.modifiers if m.type == 'NODES']
        self.assertTrue(len(mod) > 0)
        self.assertEqual(mod[0].node_group.name, "MTK_Foliage_Wiggle")


if __name__ == "__main__":
    unittest.main()
