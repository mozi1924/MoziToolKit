"""
Unit tests for multi-face block state resolution in MoziToolKit.
Tests:
1. StateBaker multi-face texture resolution for lit/unlit furnaces, beehives, respawn anchors, and snowy grass.
2. Direct Mesh Builder multi-face texture and material assignment.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy
from utils.mc_baker import StateBaker, clear_shared_baker_cache, get_shared_state_baker
from utils.live_sync import VoxelStorage, build_world_mesh


class TestYefiraMultifaceStates(unittest.TestCase):
    def setUp(self):
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in list(bpy.data.meshes):
            bpy.data.meshes.remove(mesh, do_unlink=True)

        clear_shared_baker_cache()
        get_shared_state_baker().resource_loader = None

    def test_furnace_lit_multiface_resolution(self):
        """Verify furnace[lit=true] resolves furnace_front_on only on North/-Z face."""
        baker = StateBaker(jar_path=None)

        # 1. Lit Furnace Facing North
        lit_f = baker.bake_block_state("minecraft:furnace[facing=north,lit=true]")
        # North is face index 5 in MC_DIRECTIONS (east=0, west=1, up=2, down=3, south=4, north=5)
        self.assertEqual(lit_f.faces[5].texture, "minecraft:block/furnace_front_on")
        self.assertEqual(lit_f.faces[0].texture, "minecraft:block/furnace_side")
        self.assertEqual(lit_f.faces[1].texture, "minecraft:block/furnace_side")
        self.assertEqual(lit_f.faces[2].texture, "minecraft:block/furnace_top")
        self.assertEqual(lit_f.faces[3].texture, "minecraft:block/furnace_top")
        self.assertEqual(lit_f.faces[4].texture, "minecraft:block/furnace_side")

        # 2. Unlit Furnace Facing North
        unlit_f = baker.bake_block_state("minecraft:furnace[facing=north,lit=false]")
        self.assertEqual(unlit_f.faces[5].texture, "minecraft:block/furnace_front")
        self.assertEqual(unlit_f.faces[2].texture, "minecraft:block/furnace_top")

    def test_other_multiface_blocks(self):
        """Verify beehive, respawn_anchor, and snowy grass block states."""
        baker = StateBaker(jar_path=None)

        # 1. Beehive with honey_level=5 facing north
        beehive = baker.bake_block_state("minecraft:beehive[facing=north,honey_level=5]")
        self.assertEqual(beehive.faces[5].texture, "minecraft:block/beehive_front_honey")
        self.assertEqual(beehive.faces[2].texture, "minecraft:block/beehive_top")
        self.assertEqual(beehive.faces[3].texture, "minecraft:block/beehive_bottom")
        self.assertEqual(beehive.faces[0].texture, "minecraft:block/beehive_side")

        # 2. Respawn anchor with charges=4
        anchor = baker.bake_block_state("minecraft:respawn_anchor[charges=4]")
        self.assertEqual(anchor.faces[2].texture, "minecraft:block/respawn_anchor_top")
        self.assertEqual(anchor.faces[3].texture, "minecraft:block/respawn_anchor_bottom")
        self.assertEqual(anchor.faces[0].texture, "minecraft:block/respawn_anchor_side4")

        # 3. Snowy grass block
        snowy_grass = baker.bake_block_state("minecraft:grass_block[snowy=true]")
        self.assertEqual(snowy_grass.faces[2].texture, "minecraft:block/grass_block_top")
        self.assertEqual(snowy_grass.faces[3].texture, "minecraft:block/dirt")
        self.assertEqual(snowy_grass.faces[0].texture, "minecraft:block/grass_block_snow")

    def test_direct_mesh_multiface_baking(self):
        """Verify Direct Mesh generation bakes multi-face blocks into polygons with valid UVs."""
        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:furnace[facing=north,lit=true]")
        storage.set_block(2, 0, 0, "minecraft:grass_block[snowy=true]")

        def loc(col, row, tex_id):
            return {"tile_column": col, "tile_row": row, "chunk_id": 0, "texture_id": tex_id}

        mapping_textures = {
            "minecraft:block/furnace_top": loc(1, 0, 10),
            "minecraft:block/furnace_side": loc(2, 0, 20),
            "minecraft:block/furnace_front_on": loc(4, 0, 40),
            "minecraft:block/grass_block_top": loc(19, 0, 190),
            "minecraft:block/grass_block_snow": loc(21, 0, 210),
            "minecraft:block/dirt": loc(22, 0, 220),
        }

        atlas_params = {
            "width": 1024,
            "height": 512,
            "tile_size": 16,
            "tiles_per_row": 64,
            "mapping": {"textures": mapping_textures},
        }

        res = build_world_mesh(bpy.context, storage, atlas_params=atlas_params)
        self.assertIsNotNone(res.world_obj)
        mesh = res.world_obj.data

        self.assertEqual(len(mesh.polygons), 12)
        self.assertIn("UVMap", mesh.uv_layers)


if __name__ == "__main__":
    unittest.main()
