"""Unit tests for jmc2obj material matching, texture key extraction, and UV mapping."""

import unittest
import bpy
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.materials import (
    is_jmc2obj_material,
    jmc2obj_texture_candidates,
    extract_material_texture_keys,
    material_source_origin,
    get_material_match_preset,
    JMC2OBJ_PRESET,
    write_face_source_provenance,
    get_face_source_texture_key,
    get_face_source_origin,
    atlas_uv_from_rect,
    local_uv_from_rect,
    atlas_uv_from_local,
    local_uv_from_atlas,
    canonical_texture_key,
)


class TestJmc2objMatching(unittest.TestCase):
    def tearDown(self):
        for mat in list(bpy.data.materials):
            bpy.data.materials.remove(mat)
        for mesh in list(bpy.data.meshes):
            bpy.data.meshes.remove(mesh)
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)

    def test_jmc2obj_preset_detection(self):
        # 1. Standard block
        mat_block = bpy.data.materials.new(name="minecraft_block-oak_planks")
        self.assertTrue(is_jmc2obj_material(mat_block))
        self.assertEqual(material_source_origin(mat_block), "jmc2obj")
        self.assertEqual(get_material_match_preset(mat_block).identifier, "jmc2obj")

        # 2. Entity
        mat_entity = bpy.data.materials.new(name="minecraft_entity-chest-normal")
        self.assertTrue(is_jmc2obj_material(mat_entity))

        # 3. Item
        mat_item = bpy.data.materials.new(name="minecraft_item-apple")
        self.assertTrue(is_jmc2obj_material(mat_item))

        # 4. jmc2obj internal generated
        mat_banner = bpy.data.materials.new(name="jmc2obj_banner-pattern_base")
        self.assertTrue(is_jmc2obj_material(mat_banner))

        mat_redstone = bpy.data.materials.new(name="jmc2obj_block-redstone_dust_dot_on")
        self.assertTrue(is_jmc2obj_material(mat_redstone))

        # 5. Image node with tex/minecraft/ path
        mat_custom = bpy.data.materials.new(name="CustomMatName")
        mat_custom.use_nodes = True
        tex_node = mat_custom.node_tree.nodes.new("ShaderNodeTexImage")
        img = bpy.data.images.new("stone.png", width=16, height=16)
        img.filepath = "//tex/minecraft/block/stone.png"
        tex_node.image = img
        self.assertTrue(is_jmc2obj_material(mat_custom))

        # 6. Mozi material should not be jmc2obj
        mat_mozi = bpy.data.materials.new(name="mtk:minecraft:stone:123456789012")
        mat_mozi["mtk:source_texture"] = "stone"
        self.assertFalse(is_jmc2obj_material(mat_mozi))
        self.assertEqual(material_source_origin(mat_mozi), "mozi")

        # 7. Ice Cube material should not be jmc2obj
        mat_ice = bpy.data.materials.new(name="oak_planks")
        mat_ice["ice_cube.material_id"] = "minecraft:oak_planks"
        self.assertFalse(is_jmc2obj_material(mat_ice))
        self.assertEqual(material_source_origin(mat_ice), "ice_cube")

    def test_jmc2obj_key_extraction_blocks(self):
        mat = bpy.data.materials.new(name="minecraft_block-oak_planks")
        ns, cands = extract_material_texture_keys(mat)
        self.assertEqual(ns, "minecraft")
        self.assertIn("block/oak_planks", cands)
        self.assertIn("oak_planks", cands)

        # Deepslate tiles with subpath
        mat_deep = bpy.data.materials.new(name="minecraft_block-deepslate_tiles")
        ns, cands = extract_material_texture_keys(mat_deep)
        self.assertEqual(ns, "minecraft")
        self.assertIn("block/deepslate_tiles", cands)

    def test_jmc2obj_key_extraction_biome_variants(self):
        # Biome suffix stripping
        mat_grass = bpy.data.materials.new(name="minecraft_block-grass_block_top-desert")
        ns, cands = extract_material_texture_keys(mat_grass)
        self.assertEqual(ns, "minecraft")
        self.assertIn("block/grass_block_top-desert", cands)
        self.assertIn("block/grass_block_top", cands)
        self.assertIn("grass_block_top", cands)

        mat_leaves = bpy.data.materials.new(name="minecraft_block-oak_leaves-swamp")
        ns, cands = extract_material_texture_keys(mat_leaves)
        self.assertIn("block/oak_leaves", cands)

    def test_jmc2obj_key_extraction_entities_and_internals(self):
        # Chest
        mat_chest = bpy.data.materials.new(name="minecraft_entity-chest-normal")
        ns, cands = extract_material_texture_keys(mat_chest)
        self.assertEqual(ns, "minecraft")
        self.assertIn("entity/chest/normal", cands)

        # Banner pattern base
        mat_banner = bpy.data.materials.new(name="jmc2obj_banner-pattern_base")
        ns, cands = extract_material_texture_keys(mat_banner)
        self.assertEqual(ns, "minecraft")
        self.assertIn("entity/banner/base", cands)

        # Banner pattern stripe bottom
        mat_banner_bs = bpy.data.materials.new(name="jmc2obj_banner-pattern_bs")
        ns, cands = extract_material_texture_keys(mat_banner_bs)
        self.assertIn("entity/banner/stripe_bottom", cands)

        # Redstone dust dot
        mat_redstone = bpy.data.materials.new(name="jmc2obj_block-redstone_dust_dot_on")
        ns, cands = extract_material_texture_keys(mat_redstone)
        self.assertIn("block/redstone_dust_dot", cands)

    def test_jmc2obj_safe_candidate_tokens_for_beds_and_signs(self):
        # Bed must NOT contain bare color token ('red') to avoid matching llama blanket
        mat_bed = bpy.data.materials.new(name="minecraft_entity-bed-red")
        ns, cands = extract_material_texture_keys(mat_bed)
        self.assertEqual(ns, "minecraft")
        self.assertIn("entity/bed/red", cands)
        self.assertIn("block/red_bed", cands)
        self.assertNotIn("red", cands, "Bare color token 'red' must never be emitted for beds")

        # Signs must NOT contain bare wood token ('oak') to avoid matching boat
        mat_sign = bpy.data.materials.new(name="minecraft_entity-signs-oak")
        ns, cands = extract_material_texture_keys(mat_sign)
        self.assertEqual(ns, "minecraft")
        self.assertIn("entity/signs/oak", cands)
        self.assertIn("block/oak_planks", cands)
        self.assertNotIn("oak", cands, "Bare wood token 'oak' must never be emitted for signs")

        # Hanging signs
        mat_h_sign = bpy.data.materials.new(name="minecraft_entity-signs-hanging-birch")
        ns, cands = extract_material_texture_keys(mat_h_sign)
        self.assertIn("entity/signs/hanging/birch", cands)
        self.assertIn("block/birch_planks", cands)
        self.assertNotIn("birch", cands)

    def test_jmc2obj_semantic_alias_expansions(self):
        # Stairs
        mat_stairs = bpy.data.materials.new(name="minecraft_block-crimson_stairs")
        ns, cands = extract_material_texture_keys(mat_stairs)
        self.assertIn("block/crimson_planks", cands)

        # Walls
        mat_wall = bpy.data.materials.new(name="minecraft_block-stone_brick_wall")
        ns, cands = extract_material_texture_keys(mat_wall)
        self.assertIn("block/stone_bricks", cands)

        # Carpets
        mat_carpet = bpy.data.materials.new(name="minecraft_block-gray_carpet")
        ns, cands = extract_material_texture_keys(mat_carpet)
        self.assertIn("block/gray_wool", cands)

        # 6-sided Wood
        mat_wood = bpy.data.materials.new(name="minecraft_block-oak_wood")
        ns, cands = extract_material_texture_keys(mat_wood)
        self.assertIn("block/oak_log", cands)

        # Waxed variant
        mat_waxed = bpy.data.materials.new(name="minecraft_block-waxed_oxidized_cut_copper_slab")
        ns, cands = extract_material_texture_keys(mat_waxed)
        self.assertIn("block/oxidized_cut_copper", cands)

        # Wall torch
        mat_torch = bpy.data.materials.new(name="minecraft_block-soul_wall_torch")
        ns, cands = extract_material_texture_keys(mat_torch)
        self.assertIn("block/soul_torch", cands)

        # Potted plant
        mat_potted = bpy.data.materials.new(name="minecraft_block-potted_fern")
        ns, cands = extract_material_texture_keys(mat_potted)
        self.assertIn("block/fern", cands)

        # Magma block
        mat_magma = bpy.data.materials.new(name="minecraft_block-magma_block")
        ns, cands = extract_material_texture_keys(mat_magma)
        self.assertIn("block/magma", cands)


    def test_face_provenance_roundtrip(self):
        # Test mesh face provenance
        mesh = bpy.data.meshes.new("TestMesh")
        mesh.from_pydata(
            [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
            [],
            [(0, 1, 2, 3)],
        )
        self.assertEqual(len(mesh.polygons), 1)

        keys = [canonical_texture_key("minecraft", "block/oak_planks")]
        origins = ["jmc2obj"]
        write_face_source_provenance(mesh, keys, origins)

        self.assertEqual(get_face_source_texture_key(mesh, 0), "minecraft:block/oak_planks")
        self.assertEqual(get_face_source_origin(mesh, 0), "jmc2obj")

    def test_uv_transformation_standalone_and_atlas(self):
        # Standard local quad UV [0, 1]
        local_u, local_v = 0.5, 0.5

        # 1. Tile based atlas UV mapping
        # Suppose a 16x16 tile at col 2, row 3 in 512x512 atlas
        atlas_u, atlas_v = atlas_uv_from_local(
            local_u, local_v,
            tile_column=2, tile_row=3,
            tile_size=16.0, atlas_width=512.0, atlas_height=512.0
        )
        # Invert back
        restored_u, restored_v = local_uv_from_atlas(
            atlas_u, atlas_v,
            tile_column=2, tile_row=3,
            tile_size=16.0, atlas_width=512.0, atlas_height=512.0
        )
        self.assertAlmostEqual(local_u, restored_u, places=5)
        self.assertAlmostEqual(local_v, restored_v, places=5)

        # 2. Rect based atlas UV mapping
        atlas_u2, atlas_v2 = atlas_uv_from_rect(
            local_u, local_v,
            pixel_x=32.0, pixel_y=64.0,
            rect_width=16.0, rect_height=32.0,
            atlas_width=512.0, atlas_height=512.0
        )
        restored_u2, restored_v2 = local_uv_from_rect(
            atlas_u2, atlas_v2,
            pixel_x=32.0, pixel_y=64.0,
            rect_width=16.0, rect_height=32.0,
            atlas_width=512.0, atlas_height=512.0
        )
        self.assertAlmostEqual(local_u, restored_u2, places=5)
        self.assertAlmostEqual(local_v, restored_v2, places=5)

    def test_importer_adapter_architecture(self):
        from utils.materials import (
            get_importer_adapter,
            ICE_CUBE_ADAPTER,
            JMC2OBJ_ADAPTER,
            GENERIC_ADAPTER,
        )

        mat_jmc = bpy.data.materials.new(name="minecraft_block-dirt")
        self.assertEqual(get_importer_adapter(mat_jmc).identifier, JMC2OBJ_ADAPTER.identifier)

        mat_generic = bpy.data.materials.new(name="SomeCustomCube")
        self.assertEqual(get_importer_adapter(mat_generic).identifier, GENERIC_ADAPTER.identifier)

    def test_remap_uv_coordinate_pure_function(self):
        from utils.materials import remap_uv_coordinate

        # Test remap: incoming Atlas chunk tile -> target Standalone Frame 0
        old_loc = {"kind": "static", "tile_column": 1, "tile_row": 2}
        old_chunk = {"width": 256.0, "height": 256.0, "tile_size": 16.0}
        target_anim = {"frame_width": 16.0, "frame_height": 16.0, "img_width": 16.0, "img_height": 512.0}

        # Calculate a point in old atlas UV
        u_in = (1 + 0.5) * 16.0 / 256.0
        v_in = 1.0 - (2 + 1.0 - 0.5) * 16.0 / 256.0

        u_out, v_out = remap_uv_coordinate(
            u_in, v_in,
            orig_mode="ATLAS_CHUNK",
            old_loc=old_loc,
            old_chunk=old_chunk,
            target_anim_info=target_anim,
        )

        # Expected: local (0.5, 0.5) inside frame 0 of 16x512
        # Frame 0 is at top: Y in [1 - 16/512, 1] = [512-16/512, 1]
        self.assertAlmostEqual(u_out, 0.5, places=5)
        self.assertAlmostEqual(v_out, 1.0 - (0.5 * 16.0 / 512.0), places=5)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
