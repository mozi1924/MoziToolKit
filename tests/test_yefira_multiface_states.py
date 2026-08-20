"""
Unit tests for Yefira multi-face block state resolution in MoziToolKit.
"""

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

try:
    import bpy
    HAS_BPY = True
except ImportError:
    HAS_BPY = False

if HAS_BPY:
    from utils.materials.yefira import write_yefira_point_atlas_attributes


class TestYefiraMultifaceStates(unittest.TestCase):

    def setUp(self):
        if not HAS_BPY:
            self.skipTest("bpy module not available")

        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in list(bpy.data.meshes):
            bpy.data.meshes.remove(mesh, do_unlink=True)

    def test_furnace_lit_multiface_resolution(self):
        """Verify furnace[lit=true] resolves furnace_front_on only on North/-Z face."""
        mesh = bpy.data.meshes.new("TestFurnaceMesh")
        obj = bpy.data.objects.new("TestFurnaceObj", mesh)
        bpy.context.scene.collection.objects.link(obj)

        mesh.from_pydata([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], [], [])
        mesh.update()

        states = mesh.attributes.new("block_state", 'STRING', 'POINT')
        states.data[0].value = b"minecraft:furnace[facing=north,lit=true]"
        states.data[1].value = b"minecraft:furnace[facing=north,lit=false]"

        def loc(col, row, tex_id):
            return {"tile_column": col, "tile_row": row, "chunk_id": 0, "texture_id": tex_id}

        mapping = {
            "textures": {
                "minecraft:block/furnace_top": loc(1, 0, 10),
                "minecraft:block/furnace_side": loc(2, 0, 20),
                "minecraft:block/furnace_front": loc(3, 0, 30),
                "minecraft:block/furnace_front_on": loc(4, 0, 40),
            }
        }

        write_yefira_point_atlas_attributes(mesh, mapping)

        # Index 0 is lit furnace
        # Face 0: East (+X) -> furnace_side (2, 0)
        self.assertEqual(tuple(mesh.attributes["mtk_tile_east"].data[0].vector), (2.0, 0.0, 0.0))
        self.assertEqual(mesh.attributes["mtk_texture_east"].data[0].value, 20)

        # Face 1: West (-X) -> furnace_side (2, 0)
        self.assertEqual(tuple(mesh.attributes["mtk_tile_west"].data[0].vector), (2.0, 0.0, 0.0))
        self.assertEqual(mesh.attributes["mtk_texture_west"].data[0].value, 20)

        # Face 2: Top (+Y) -> furnace_top (1, 0)
        self.assertEqual(tuple(mesh.attributes["mtk_tile_top"].data[0].vector), (1.0, 0.0, 0.0))
        self.assertEqual(mesh.attributes["mtk_texture_top"].data[0].value, 10)

        # Face 3: Bottom (-Y) -> furnace_top (1, 0)
        self.assertEqual(tuple(mesh.attributes["mtk_tile_bottom"].data[0].vector), (1.0, 0.0, 0.0))
        self.assertEqual(mesh.attributes["mtk_texture_bottom"].data[0].value, 10)

        # Face 4: South (+Z) -> furnace_side (2, 0)
        self.assertEqual(tuple(mesh.attributes["mtk_tile_south"].data[0].vector), (2.0, 0.0, 0.0))
        self.assertEqual(mesh.attributes["mtk_texture_south"].data[0].value, 20)

        # Face 5: North (-Z) -> furnace_front_on (4, 0)
        self.assertEqual(tuple(mesh.attributes["mtk_tile_north"].data[0].vector), (4.0, 0.0, 0.0))
        self.assertEqual(mesh.attributes["mtk_texture_north"].data[0].value, 40)

        # Index 1 is unlit furnace
        # North (-Z) -> furnace_front (3, 0)
        self.assertEqual(tuple(mesh.attributes["mtk_tile_north"].data[1].vector), (3.0, 0.0, 0.0))
        self.assertEqual(mesh.attributes["mtk_texture_north"].data[1].value, 30)
        self.assertEqual(tuple(mesh.attributes["mtk_tile_top"].data[1].vector), (1.0, 0.0, 0.0))

    def test_other_multiface_blocks(self):
        """Verify beehive, respawn_anchor, observer, and grass_block states."""
        mesh = bpy.data.meshes.new("TestOtherMesh")
        obj = bpy.data.objects.new("TestOtherObj", mesh)
        bpy.context.scene.collection.objects.link(obj)

        mesh.from_pydata([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)], [], [])
        mesh.update()

        states = mesh.attributes.new("block_state", 'STRING', 'POINT')
        states.data[0].value = b"minecraft:beehive[facing=north,honey_level=5]"
        states.data[1].value = b"minecraft:respawn_anchor[charges=4]"
        states.data[2].value = b"minecraft:grass_block[snowy=true]"

        def loc(col, row, tex_id):
            return {"tile_column": col, "tile_row": row, "chunk_id": 0, "texture_id": tex_id}

        mapping = {
            "textures": {
                "minecraft:block/beehive_top": loc(5, 0, 50),
                "minecraft:block/beehive_bottom": loc(6, 0, 60),
                "minecraft:block/beehive_side": loc(7, 0, 70),
                "minecraft:block/beehive_front": loc(8, 0, 80),
                "minecraft:block/beehive_front_honey": loc(9, 0, 90),
                "minecraft:block/respawn_anchor_top_off": loc(10, 0, 100),
                "minecraft:block/respawn_anchor_top": loc(11, 0, 110),
                "minecraft:block/respawn_anchor_bottom": loc(12, 0, 120),
                "minecraft:block/respawn_anchor_side0": loc(13, 0, 130),
                "minecraft:block/respawn_anchor_side4": loc(14, 0, 140),
                "minecraft:block/grass_block_top": loc(19, 0, 190),
                "minecraft:block/grass_block_side": loc(20, 0, 200),
                "minecraft:block/grass_block_snow": loc(21, 0, 210),
                "minecraft:block/dirt": loc(22, 0, 220),
            }
        }

        write_yefira_point_atlas_attributes(mesh, mapping)

        # 1. Beehive with honey_level=5
        self.assertEqual(tuple(mesh.attributes["mtk_tile_north"].data[0].vector), (9.0, 0.0, 0.0))  # front_honey
        self.assertEqual(tuple(mesh.attributes["mtk_tile_top"].data[0].vector), (5.0, 0.0, 0.0))    # top
        self.assertEqual(tuple(mesh.attributes["mtk_tile_bottom"].data[0].vector), (6.0, 0.0, 0.0)) # bottom
        self.assertEqual(tuple(mesh.attributes["mtk_tile_east"].data[0].vector), (7.0, 0.0, 0.0))   # side

        # 2. Respawn anchor with charges=4
        self.assertEqual(tuple(mesh.attributes["mtk_tile_top"].data[1].vector), (11.0, 0.0, 0.0))   # top
        self.assertEqual(tuple(mesh.attributes["mtk_tile_bottom"].data[1].vector), (12.0, 0.0, 0.0))# bottom
        self.assertEqual(tuple(mesh.attributes["mtk_tile_east"].data[1].vector), (14.0, 0.0, 0.0))  # side4
        self.assertEqual(tuple(mesh.attributes["mtk_tile_north"].data[1].vector), (14.0, 0.0, 0.0)) # side4

        # 3. Snowy grass block
        self.assertEqual(tuple(mesh.attributes["mtk_tile_top"].data[2].vector), (19.0, 0.0, 0.0))   # top
        self.assertEqual(tuple(mesh.attributes["mtk_tile_bottom"].data[2].vector), (22.0, 0.0, 0.0))# dirt
        self.assertEqual(tuple(mesh.attributes["mtk_tile_east"].data[2].vector), (21.0, 0.0, 0.0))  # snow
        self.assertEqual(tuple(mesh.attributes["mtk_tile_north"].data[2].vector), (21.0, 0.0, 0.0)) # snow


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
