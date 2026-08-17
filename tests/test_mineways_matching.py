"""Unit tests for Mineways material matching, texture key extraction, and provenance."""

import unittest
import bpy
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.materials import (
    is_mineways_material,
    mineways_texture_candidates,
    extract_material_texture_keys,
    material_source_origin,
    get_material_match_preset,
    MINEWAYS_PRESET,
    write_face_source_provenance,
    get_face_source_texture_key,
    get_face_source_origin,
)


class TestMinewaysMatching(unittest.TestCase):
    def tearDown(self):
        for mat in list(bpy.data.materials):
            bpy.data.materials.remove(mat)
        for mesh in list(bpy.data.meshes):
            bpy.data.meshes.remove(mesh)
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)

    def test_mineways_preset_detection(self):
        # 1. Single material mode default
        mat_single = bpy.data.materials.new(name="MC_material")
        self.assertTrue(is_mineways_material(mat_single))
        self.assertEqual(material_source_origin(mat_single), "mineways")
        self.assertEqual(get_material_match_preset(mat_single).identifier, "mineways")

        # 2. Synthesized / biome tinted tile material with _y suffix
        mat_synthesized = bpy.data.materials.new(name="grass_block_top_y")
        self.assertTrue(is_mineways_material(mat_synthesized))

        mat_synthesized_side = bpy.data.materials.new(name="grass_block_side_y")
        self.assertTrue(is_mineways_material(mat_synthesized_side))

        # 3. Mineways internal synthesized prefix mw_ / mwo_
        mat_mw = bpy.data.materials.new(name="mw_chest_normal")
        self.assertTrue(is_mineways_material(mat_mw))

        # 4. Material with Mineways terrain atlas texture node
        mat_atlas = bpy.data.materials.new(name="CustomBlockMat")
        mat_atlas.use_nodes = True
        tex_node = mat_atlas.node_tree.nodes.new("ShaderNodeTexImage")
        img = bpy.data.images.new("terrainRGBA.png", width=512, height=512)
        tex_node.image = img
        self.assertTrue(is_mineways_material(mat_atlas))
        self.assertEqual(material_source_origin(mat_atlas), "mineways")

        # 5. Material with synthesized _y image node
        mat_tile = bpy.data.materials.new(name="OakLeavesMat")
        mat_tile.use_nodes = True
        tex_node2 = mat_tile.node_tree.nodes.new("ShaderNodeTexImage")
        img2 = bpy.data.images.new("oak_leaves_y.png", width=16, height=16)
        tex_node2.image = img2
        self.assertTrue(is_mineways_material(mat_tile))
        self.assertEqual(material_source_origin(mat_tile), "mineways")

        # 6. Explicit metadata
        mat_meta = bpy.data.materials.new(name="SomeCustomMaterial")
        mat_meta["mtk:source_importer"] = "mineways"
        self.assertTrue(is_mineways_material(mat_meta))
        self.assertEqual(material_source_origin(mat_meta), "mineways")

        # 7. Non-Mineways materials should return False
        mat_mozi = bpy.data.materials.new(name="mtk:minecraft:stone:123456789012")
        mat_mozi["mtk:source_texture"] = "stone"
        self.assertFalse(is_mineways_material(mat_mozi))

        mat_jmc = bpy.data.materials.new(name="minecraft_block-oak_planks")
        self.assertFalse(is_mineways_material(mat_jmc))

    def test_mineways_key_extraction_tiles(self):
        # 1. Synthesized tile name (grass_block_top_y)
        mat_grass = bpy.data.materials.new(name="grass_block_top_y")
        ns, cands = extract_material_texture_keys(mat_grass)
        self.assertEqual(ns, "minecraft")
        self.assertIn("grass_block_top", cands)
        self.assertIn("block/grass_block_top", cands)

        # 2. Synthesized image texture attached to a material
        mat_leaves = bpy.data.materials.new(name="Leaves")
        mat_leaves.use_nodes = True
        tex_node = mat_leaves.node_tree.nodes.new("ShaderNodeTexImage")
        img = bpy.data.images.new("oak_leaves_y.png", width=16, height=16)
        tex_node.image = img
        ns, cands = extract_material_texture_keys(mat_leaves)
        self.assertIn("oak_leaves", cands)
        self.assertIn("block/oak_leaves", cands)

    def test_mineways_key_extraction_block_aliases(self):
        # 1. Stationary water
        mat_water = bpy.data.materials.new(name="Stationary_Water")
        ns, cands = mineways_texture_candidates(mat_water)
        self.assertIn("block/water_still", cands)
        self.assertIn("block/water_flow", cands)

        # 2. Redstone wire
        mat_wire = bpy.data.materials.new(name="Redstone_Wire")
        ns, cands = mineways_texture_candidates(mat_wire)
        self.assertIn("block/redstone_dust_line0", cands)
        self.assertIn("block/redstone_dust_dot", cands)

        # 3. Lit redstone lamp
        mat_lamp = bpy.data.materials.new(name="Lit_Redstone_Lamp")
        ns, cands = mineways_texture_candidates(mat_lamp)
        self.assertIn("block/redstone_lamp_on", cands)

        # 4. Monster spawner
        mat_spawner = bpy.data.materials.new(name="Monster_Spawner")
        ns, cands = mineways_texture_candidates(mat_spawner)
        self.assertIn("block/spawner", cands)

        # 5. Stained clay
        mat_clay = bpy.data.materials.new(name="Stained_Clay")
        ns, cands = mineways_texture_candidates(mat_clay)
        self.assertIn("block/terracotta", cands)

    def test_mineways_semantic_expansions(self):
        # Slabs
        mat_slab = bpy.data.materials.new(name="Dark_Prismarine_Slab")
        ns, cands = mineways_texture_candidates(mat_slab)
        self.assertIn("block/dark_prismarine", cands)

        # Stairs
        mat_stairs = bpy.data.materials.new(name="Oak_Wood_Stairs")
        ns, cands = mineways_texture_candidates(mat_stairs)
        self.assertIn("block/oak_wood", cands)

        # Wool / Carpets
        mat_carpet = bpy.data.materials.new(name="Red_Carpet")
        ns, cands = mineways_texture_candidates(mat_carpet)
        self.assertIn("block/red_wool", cands)

    def test_face_provenance_recording(self):
        mesh = bpy.data.meshes.new("MinewaysMesh")
        mesh.from_pydata(
            [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
            [],
            [(0, 1, 2, 3)],
        )
        keys = ["minecraft:block/oak_planks"]
        origins = ["mineways"]
        write_face_source_provenance(mesh, keys, origins)

        self.assertEqual(get_face_source_origin(mesh, 0), "mineways")
        self.assertEqual(get_face_source_texture_key(mesh, 0), "minecraft:block/oak_planks")

    def test_missing_texture_and_node_label_detection(self):
        # Material has generic name "Material.001", image file is missing, but node label/name has tex/stone.png
        mat = bpy.data.materials.new(name="Material.001")
        mat.use_nodes = True
        tex_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex_node.image = None
        tex_node.label = "tex/stone.png"

        self.assertTrue(is_mineways_material(mat))
        ns, cands = extract_material_texture_keys(mat)
        self.assertEqual(ns, "minecraft")
        self.assertIn("block/stone", cands)

        # Node has informative Mineways custom name/label grass_block_top_y
        mat2 = bpy.data.materials.new(name="Material.002")
        mat2.use_nodes = True
        tex_node2 = mat2.node_tree.nodes.new("ShaderNodeTexImage")
        tex_node2.image = None
        tex_node2.name = "grass_block_top_y"
        self.assertTrue(is_mineways_material(mat2))
        ns2, cands2 = extract_material_texture_keys(mat2)
        self.assertIn("block/grass_block_top", cands2)


if __name__ == "__main__":
    unittest.main()
