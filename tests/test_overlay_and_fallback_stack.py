"""
Unit tests for Minecraft Resource Pack Fallback Stack, Overlay Texture Baking,
and Biome Tinting Integration in MoziToolKit.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image

import bpy

from utils.materials.resource_pack import ZipResourcePack, get_cache_dir
from utils.materials.pack_stack import ResourcePackStack, get_configured_pack_stack
from utils.materials.atlas_generator import AtlasGenerator
from utils.materials.biome import BiomeResolver
from pipeline.presets.presets import run_preset_pipeline


SPBR_PATH = Path("/Users/jaxlocke/Downloads/SPBR-21.zip")
JAR_PATH = Path("/Users/jaxlocke/26.2-Fabric.jar")


class TestOverlayAndFallbackStack(unittest.TestCase):
    """Test suite for Overlay texture extraction, Biome Tinting, and Fallback Stack cache invalidation."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="mtk_test_overlay_"))
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_pack_stack_hash_and_invalidation(self):
        """ResourcePackStack must produce deterministic stack_hash that updates when sources change."""
        if not SPBR_PATH.exists() or not JAR_PATH.exists():
            self.skipTest("SPBR or JAR archive not available on test machine")

        stack1 = ResourcePackStack([SPBR_PATH])
        hash1 = stack1.stack_hash
        self.assertIsNotNone(hash1)
        self.assertNotEqual(hash1, "empty_stack")

        stack2 = ResourcePackStack([SPBR_PATH, JAR_PATH])
        hash2 = stack2.stack_hash
        self.assertIsNotNone(hash2)
        # Stack hash with fallback JAR must differ from standalone primary pack hash
        self.assertNotEqual(hash1, hash2)

    def test_atlas_generator_overlay_baking_with_fallback(self):
        """AtlasGenerator must extract models from fallback JAR and bake grass_block_side overlay."""
        if not SPBR_PATH.exists() or not JAR_PATH.exists():
            self.skipTest("SPBR or JAR archive not available on test machine")

        pack = ZipResourcePack(str(SPBR_PATH))
        stack = ResourcePackStack([SPBR_PATH, JAR_PATH])

        gen = AtlasGenerator(pack.extract_dir, fallback_stack=stack)
        atlas_out = self.temp_dir / "atlas_output"
        for frac, msg, res in gen.build_iter(atlas_out):
            pass

        mapping_file = atlas_out / "atlas_mapping.json"
        self.assertTrue(mapping_file.exists())
        with open(mapping_file, "r", encoding="utf-8") as f:
            mapping = json.load(f)

        # grass_block_side must be mapped with has_overlay=True and overlay_texture='grass_block_side_overlay'
        loc = mapping.get("textures", {}).get("minecraft:block/grass_block_side") or mapping.get("textures", {}).get("grass_block_side")
        self.assertIsNotNone(loc)
        self.assertTrue(loc.get("has_overlay"))
        self.assertEqual(loc.get("overlay_texture"), "grass_block_side_overlay")
        self.assertEqual(loc.get("default_base_tint_weight"), 0.0)
        self.assertEqual(loc.get("default_overlay_tint_weight"), 1.0)
        self.assertEqual(loc.get("default_tint_weight"), 1.0)

        # Chunk 0 (blocks) must have overlay file
        chunk0 = mapping["chunks"][0]
        self.assertTrue(chunk0.get("has_overlay"))
        self.assertIn("overlay", chunk0.get("files", {}))

        overlay_img_file = atlas_out / chunk0["files"]["overlay"]
        self.assertTrue(overlay_img_file.exists())
        overlay_im = Image.open(overlay_img_file)
        self.assertIsNotNone(overlay_im.getbbox(), "Overlay texture canvas must contain non-transparent pixels")

    def test_material_replacement_overlay_and_biome_tint(self):
        """Replacing material with SPBR and fallback JAR must generate correct tint attributes and nodes."""
        if not SPBR_PATH.exists() or not JAR_PATH.exists():
            self.skipTest("SPBR or JAR archive not available on test machine")

        bpy.ops.mesh.primitive_cube_add(size=1)
        obj = bpy.context.active_object
        mesh = obj.data

        mat_top = bpy.data.materials.new("grass_block_top")
        mat_side = bpy.data.materials.new("grass_block_side")
        mat_dirt = bpy.data.materials.new("dirt")

        mesh.materials.append(mat_top)
        mesh.materials.append(mat_side)
        mesh.materials.append(mat_dirt)

        # Assign face materials
        mesh.polygons[5].material_index = 0
        mesh.polygons[4].material_index = 2
        for p in [0, 1, 2, 3]:
            mesh.polygons[p].material_index = 1

        params = {
            "zip_path": str(SPBR_PATH),
            "material_mode": "ATLAS",
            "biome_preset": "PLAINS",
            "pack_textures": True,
            "use_cache": True,
        }

        # Inject configured pack stack with fallback JAR
        from utils.system.menu_config import save_pack_stack_config
        save_pack_stack_config([
            {"name": "SPBR", "path": str(SPBR_PATH), "enabled": True, "pack_type": "RESOURCE_PACK"},
            {"name": "Vanilla JAR", "path": str(JAR_PATH), "enabled": True, "pack_type": "VANILLA"},
        ])

        res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[obj])
        self.assertEqual(res.status.name, "SUCCESS")

        # Verify face biome tint data attributes
        tint_data_attr = mesh.attributes.get("mtk_biome_tint_data")
        tint_col_attr = mesh.attributes.get("mtk_biome_tint_color")
        self.assertIsNotNone(tint_data_attr)
        self.assertIsNotNone(tint_col_attr)

        # Side faces (0, 1, 2, 3) must have: BaseTint=0.0, OverlayTint=1.0, TintWeight=1.0, Hardcoded=0.0
        for p in range(4):
            data_val = list(tint_data_attr.data[p].color)
            self.assertAlmostEqual(data_val[0], 0.0, places=3, msg="Base tint weight on grass block side must be 0.0")
            self.assertAlmostEqual(data_val[1], 1.0, places=3, msg="Overlay tint weight on grass block side must be 1.0")
            self.assertAlmostEqual(data_val[2], 1.0, places=3, msg="Tint weight on grass block side must be 1.0")

        # Top face (5) must have: BaseTint=1.0, OverlayTint=1.0, TintWeight=1.0
        top_data = list(tint_data_attr.data[5].color)
        self.assertAlmostEqual(top_data[0], 1.0, places=3)
        self.assertAlmostEqual(top_data[1], 1.0, places=3)
        self.assertAlmostEqual(top_data[2], 1.0, places=3)

        # Dirt bottom face (4) must have tint weight 0.0
        bottom_data = list(tint_data_attr.data[4].color)
        self.assertAlmostEqual(bottom_data[2], 0.0, places=3)

        # Verify material node setup has Overlay texture node connected to MC Biome Tint
        chunk_mat = obj.material_slots[0].material
        self.assertIsNotNone(chunk_mat)
        tex_overlay_node = None
        for n in chunk_mat.node_tree.nodes:
            if "Overlay" in n.name and n.type == "TEX_IMAGE":
                tex_overlay_node = n
                break
        self.assertIsNotNone(tex_overlay_node, "Chunk material must contain Overlay image texture node")
        self.assertIsNotNone(tex_overlay_node.image, "Overlay node must have an image assigned")


if __name__ == "__main__":
    unittest.main(argv=["dummy"])
