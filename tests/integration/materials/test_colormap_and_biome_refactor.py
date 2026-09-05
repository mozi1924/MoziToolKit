"""
Test suite for Biome Tinting System Refactor & Vanilla MC Alignment.
Verifies colormap sampling, 66-biome canonical registry, pack stack colormap extraction,
shader node group decoding, and smooth biome transition blending.
"""

import unittest
import math
from pathlib import Path
from PIL import Image

import bpy

from utils.materials.biome import (
    BIOME_PALETTES,
    HARDCODED_BLOCK_TINTS,
    TINT_TYPE_NONE,
    TINT_TYPE_GRASS,
    TINT_TYPE_FOLIAGE,
    TINT_TYPE_DRY_FOLIAGE,
    TINT_TYPE_WATER,
    TINT_TYPE_HARDCODED,
    hex_to_rgb,
    srgb_to_linear,
    hex_to_linear_rgb,
    hex_to_rgba,
    hex_to_linear_rgba,
    get_colormap_uv,
    sample_colormap_pixel,
    blend_biome_colors,
    get_biome_colors,
    classify_tint_category,
    BiomeResolver,
)
from utils.materials.pack import ZipResourcePack, ResourcePackStack
from utils.node_groups.biome import ensure_biome_tint, ensure_colormap_sampler
from utils.materials.pipeline.mesh_attributes import compute_biome_tint_attributes


class TestBiomeRefactor(unittest.TestCase):

    def test_canonical_biomes_count_and_fields(self):
        """Verify all 66 biomes from 26.2 are present with all required properties."""
        self.assertEqual(len(BIOME_PALETTES), 66)
        
        # Test key biomes
        for b_name in ("PLAINS", "FOREST", "DARK_FOREST", "BADLANDS", "PALE_GARDEN", "SWAMP", "CHERRY_GROVE", "TAIGA"):
            self.assertIn(b_name, BIOME_PALETTES)
            data = BIOME_PALETTES[b_name]
            self.assertIn("grass", data)
            self.assertIn("foliage", data)
            self.assertIn("dry_foliage", data)
            self.assertIn("water", data)
            self.assertIn("temperature", data)
            self.assertIn("humidity", data)
            self.assertTrue(data["grass"].startswith("#"))
            self.assertTrue(data["foliage"].startswith("#"))
            self.assertTrue(data["dry_foliage"].startswith("#"))
            self.assertTrue(data["water"].startswith("#"))

    def test_exact_vanilla_colors(self):
        """Verify exact hex colors for canonical biomes."""
        plains = get_biome_colors("PLAINS")
        self.assertEqual(plains["grass_hex"], "#91BD59")
        self.assertEqual(plains["foliage_hex"], "#77AB2F")

        forest = get_biome_colors("FOREST")
        self.assertEqual(forest["grass_hex"], "#79C05A")
        self.assertEqual(forest["foliage_hex"], "#59AE30")

        dark_forest = get_biome_colors("DARK_FOREST")
        self.assertEqual(dark_forest["grass_hex"], "#507A32")

        badlands = get_biome_colors("BADLANDS")
        self.assertEqual(badlands["grass_hex"], "#90814D")
        self.assertEqual(badlands["foliage_hex"], "#9E814D")

        cherry = get_biome_colors("CHERRY_GROVE")
        self.assertEqual(cherry["grass_hex"], "#B6DB61")
        self.assertEqual(cherry["water_hex"], "#5DB7EF")

        pale_garden = get_biome_colors("PALE_GARDEN")
        self.assertEqual(pale_garden["grass_hex"], "#778272")
        self.assertEqual(pale_garden["foliage_hex"], "#878D76")
        self.assertEqual(pale_garden["dry_foliage_hex"], "#A0A69C")

    def test_colormap_uv_math(self):
        """Test triangular colormap UV coordinate math."""
        u, v = get_colormap_uv(0.8, 0.4)
        self.assertAlmostEqual(u, 0.2, places=4)
        self.assertAlmostEqual(v, 0.32, places=4)

        u_hot, v_hot = get_colormap_uv(2.0, 0.0)
        self.assertAlmostEqual(u_hot, 0.0, places=4)
        self.assertAlmostEqual(v_hot, 0.0, places=4)

        u_cold, v_cold = get_colormap_uv(-0.5, 0.5)
        self.assertAlmostEqual(u_cold, 1.0, places=4)
        self.assertAlmostEqual(v_cold, 0.0, places=4)

    def test_sample_colormap_pixel(self):
        """Test pixel sampling from a synthetic 256x256 image."""
        img = Image.new("RGB", (256, 256), color=(128, 200, 50))
        # Set pixel at i=50 ((1-0.8)*255), j=173 ((1-0.32)*255) to red
        img.putpixel((50, 173), (255, 0, 0))
        
        col = sample_colormap_pixel(img, 0.8, 0.4)
        self.assertAlmostEqual(col[0], 1.0, places=2)
        self.assertAlmostEqual(col[1], 0.0, places=2)
        self.assertAlmostEqual(col[2], 0.0, places=2)

    def test_blend_biome_colors(self):
        """Test smooth multi-biome transition blending (群系过渡)."""
        # 50% Plains + 50% Forest
        plains_col = get_biome_colors("PLAINS")["grass_linear"]
        forest_col = get_biome_colors("FOREST")["grass_linear"]
        
        blended = blend_biome_colors([("PLAINS", 0.5), ("FOREST", 0.5)], tint_type="grass")
        expected_r = (plains_col[0] + forest_col[0]) / 2.0
        expected_g = (plains_col[1] + forest_col[1]) / 2.0
        expected_b = (plains_col[2] + forest_col[2]) / 2.0

        self.assertAlmostEqual(blended[0], expected_r, places=4)
        self.assertAlmostEqual(blended[1], expected_g, places=4)
        self.assertAlmostEqual(blended[2], expected_b, places=4)

    def test_classify_tint_category(self):
        """Test tint category classification including dry_foliage and bush."""
        self.assertEqual(classify_tint_category("grass_block_top"), "grass")
        self.assertEqual(classify_tint_category("bush"), "grass")
        self.assertEqual(classify_tint_category("short_grass"), "grass")
        self.assertEqual(classify_tint_category("pink_petals_stem"), "grass")
        self.assertEqual(classify_tint_category("oak_leaves"), "foliage")
        self.assertEqual(classify_tint_category("leaf_litter"), "dry_foliage")
        self.assertEqual(classify_tint_category("pale_hanging_moss"), "dry_foliage")
        self.assertEqual(classify_tint_category("water_still"), "water")
        self.assertEqual(classify_tint_category("spruce_leaves"), "hardcoded")
        self.assertEqual(classify_tint_category("stone"), "none")

    def test_bush_and_custom_model_inheritance(self):
        """Test that BiomeResolver resolves parent inheritance chains and variable references."""
        models = {
            "tinted_cross": {
                "textures": {"particle": "#cross"},
                "elements": [
                    {
                        "from": [0.8, 0, 8], "to": [15.2, 16, 8],
                        "faces": {
                            "north": {"texture": "#cross", "tintindex": 0},
                            "south": {"texture": "#cross", "tintindex": 0},
                        }
                    }
                ]
            },
            "bush": {
                "parent": "minecraft:block/tinted_cross",
                "textures": {"cross": "block/bush"}
            },
            "custom_grass_block": {
                "textures": {
                    "side": "block/custom_grass_side",
                    "overlay": "block/custom_grass_side_overlay"
                }
            }
        }
        resolver = BiomeResolver(models=models)
        
        # Verify bush tint
        bush_tint = resolver.get_tint_info("bush")
        self.assertEqual(bush_tint["tint_type"], TINT_TYPE_GRASS)
        self.assertEqual(bush_tint["tint_category"], "grass")
        self.assertAlmostEqual(bush_tint["tint_weight"], 1.0)
        self.assertAlmostEqual(bush_tint["base_tint_weight"], 1.0)

        # Verify discovered overlay pair
        self.assertEqual(resolver.get_overlay_texture("custom_grass_side"), "custom_grass_side_overlay")

    def test_jar_model_loading_and_fallback(self):
        """Test loading models directly from a JAR file."""
        jar_path = Path("/Users/jaxlocke/26.2-Fabric.jar")
        if jar_path.exists():
            resolver = BiomeResolver()
            resolver.load_from_zip(jar_path)
            self.assertGreater(len(resolver.models), 50)
            
            # Verify discovered tints from vanilla JAR
            bush_info = resolver.get_tint_info("bush")
            self.assertEqual(bush_info["tint_type"], TINT_TYPE_GRASS)
            
            overlay = resolver.get_overlay_texture("grass_block_side")
            self.assertEqual(overlay, "grass_block_side_overlay")

    def test_colormap_sampler_node_group(self):
        """Test generation and socket structure of MC_Biome_Colormap_Sampler node group."""
        tree = ensure_colormap_sampler()
        self.assertIsNotNone(tree)
        inputs = [item.name for item in tree.interface.items_tree if getattr(item, "in_out", "") == "INPUT"] if hasattr(tree, "interface") else [s.name for s in tree.inputs]
        outputs = [item.name for item in tree.interface.items_tree if getattr(item, "in_out", "") == "OUTPUT"] if hasattr(tree, "interface") else [s.name for s in tree.outputs]
        self.assertIn("Temperature", inputs)
        self.assertIn("Humidity", inputs)
        self.assertIn("Colormap UV", outputs)

    def test_biome_tint_node_group(self):
        """Test generation and socket structure of MC_Biome_Tint node group."""
        tree = ensure_biome_tint()
        self.assertIsNotNone(tree)
        inputs = [item.name for item in tree.interface.items_tree if getattr(item, "in_out", "") == "INPUT"] if hasattr(tree, "interface") else [s.name for s in tree.inputs]
        outputs = [item.name for item in tree.interface.items_tree if getattr(item, "in_out", "") == "OUTPUT"] if hasattr(tree, "interface") else [s.name for s in tree.outputs]
        self.assertIn("Base Color", inputs)
        self.assertIn("Overlay Color", inputs)
        self.assertIn("Tint Color", inputs)
        self.assertIn("Color", outputs)
        self.assertIn("Alpha", outputs)

    def test_mesh_attributes_multi_biome_transition(self):
        """Test compute_biome_tint_attributes with multi-biome transition input."""
        poly_map = {
            0: {"tint_type": TINT_TYPE_GRASS, "tint_weight": 1.0},
            1: {"tint_type": TINT_TYPE_FOLIAGE, "tint_weight": 1.0},
            2: {"tint_type": TINT_TYPE_NONE, "tint_weight": 0.0},
        }
        # Single biome
        packed, colors, uvs = compute_biome_tint_attributes(3, poly_map, biome_preset="PLAINS")
        self.assertEqual(len(colors), 3)
        self.assertEqual(len(uvs), 3)
        self.assertAlmostEqual(colors[0][0], get_biome_colors("PLAINS")["grass_linear"][0], places=3)

        # Transition biome
        packed_tr, colors_tr, uvs_tr = compute_biome_tint_attributes(3, poly_map, biome_preset=[("PLAINS", 0.5), ("FOREST", 0.5)])
        self.assertEqual(len(colors_tr), 3)
        self.assertEqual(len(uvs_tr), 3)
        expected_grass = blend_biome_colors([("PLAINS", 0.5), ("FOREST", 0.5)], "grass")
        self.assertAlmostEqual(colors_tr[0][0], expected_grass[0], places=3)

    def test_rebuild_material_with_colormap_sampler(self):
        """Test that rebuild_material creates MC Biome Colormap Sampler and links to colormap texture."""
        from utils.materials.nodes.builder import rebuild_material
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Create a mock grass colormap
            col_dir = tmppath / "assets" / "minecraft" / "textures" / "colormap"
            col_dir.mkdir(parents=True, exist_ok=True)
            col_img = Image.new("RGB", (256, 256), color=(145, 189, 89))
            col_img.save(col_dir / "grass.png")
            
            # Create mock grass albedo
            tex_dir = tmppath / "assets" / "minecraft" / "textures" / "block"
            tex_dir.mkdir(parents=True, exist_ok=True)
            albedo_img = Image.new("RGBA", (16, 16), color=(100, 100, 100, 255))
            albedo_file = tex_dir / "bush.png"
            albedo_img.save(albedo_file)
            
            pack = ZipResourcePack(tmppath)
            stack = ResourcePackStack([pack])
            
            mat = bpy.data.materials.new("test_bush_material")
            tex_info = {
                "namespace": "minecraft",
                "texture_name": "bush",
                "albedo": str(albedo_file),
                "tint_info": {
                    "tint_type": TINT_TYPE_GRASS,
                    "tint_category": "grass",
                    "tint_weight": 1.0,
                    "base_tint_weight": 1.0,
                    "overlay_tint_weight": 1.0,
                    "has_overlay": False,
                    "is_hardcoded": False,
                }
            }
            
            ok = rebuild_material(
                mat=mat,
                texture_info=tex_info,
                pack_textures=False,
                biome_preset="FOREST",
                pack_stack=stack,
            )
            self.assertTrue(ok)
            
            # Verify nodes created in material node tree
            node_names = [n.name for n in mat.node_tree.nodes]
            self.assertIn("MC Biome Tint", node_names)
            self.assertIn("MC Biome Colormap Sampler", node_names)
            self.assertIn("Colormap Grass", node_names)
            
            sampler_node = mat.node_tree.nodes["MC Biome Colormap Sampler"]
            self.assertAlmostEqual(sampler_node.inputs["Temperature"].default_value, 0.7, places=2)
            self.assertAlmostEqual(sampler_node.inputs["Humidity"].default_value, 0.8, places=2)
            
            # Verify link: Sampler -> Colormap -> Biome Tint
            colormap_node = mat.node_tree.nodes["Colormap Grass"]
            self.assertIsNotNone(colormap_node.image)
            self.assertTrue(any(l.from_node == sampler_node and l.to_node == colormap_node for l in mat.node_tree.links))
            self.assertTrue(any(l.from_node == colormap_node and l.to_node.name == "MC Biome Tint" for l in mat.node_tree.links))

    def test_colormap_decoder_node_group(self):
        """Test generation and socket structure of MC_Biome_Colormap_Decoder node group."""
        from utils.node_groups.biome import ensure_colormap_decoder
        tree = ensure_colormap_decoder()
        self.assertIsNotNone(tree)
        inputs = [item.name for item in tree.interface.items_tree if getattr(item, "in_out", "") == "INPUT"] if hasattr(tree, "interface") else [s.name for s in tree.inputs]
        outputs = [item.name for item in tree.interface.items_tree if getattr(item, "in_out", "") == "OUTPUT"] if hasattr(tree, "interface") else [s.name for s in tree.outputs]
        self.assertIn("Tint Type", inputs)
        self.assertIn("Grass Color", inputs)
        self.assertIn("Foliage Color", inputs)
        self.assertIn("Dry Foliage Color", inputs)
        self.assertIn("Water Color", inputs)
        self.assertIn("Hardcoded Color", inputs)
        self.assertIn("Color", outputs)

    def test_atlas_material_with_colormap_decoder(self):
        """Test that atlas add_packed_biome_attribute_nodes connects ATTR_COLORMAP_UV and Colormap Decoder correctly."""
        from utils.materials.atlas.builder import add_packed_biome_attribute_nodes
        from utils.node_groups.biome import ensure_biome_tint
        from utils.materials.constants import ATTR_COLORMAP_UV, ATTR_BIOME_TINT_DATA
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            grass_cm = tmppath / "grass.png"
            Image.new("RGB", (256, 256), color=(145, 189, 89)).save(grass_cm)

            mat = bpy.data.materials.new("test_atlas_cm_material")
            mat.use_nodes = True
            nodes, links = mat.node_tree.nodes, mat.node_tree.links
            nodes.clear()

            tint_tree = ensure_biome_tint()
            biome_node = nodes.new("ShaderNodeGroup")
            biome_node.node_tree = tint_tree
            biome_node.name = "MC Biome Tint"

            colormaps = {"grass": str(grass_cm)}
            add_packed_biome_attribute_nodes(nodes, links, biome_node, colormaps=colormaps)

            node_names = [n.name for n in nodes]
            self.assertIn("Attr Colormap UV", node_names)
            self.assertIn("Attr Biome Tint Data", node_names)
            self.assertIn("MC Biome Colormap Decoder", node_names)
            self.assertIn("Colormap Grass", node_names)

            attr_uv = nodes["Attr Colormap UV"]
            self.assertEqual(attr_uv.attribute_name, ATTR_COLORMAP_UV)
            tex_grass = nodes["Colormap Grass"]
            decoder_node = nodes["MC Biome Colormap Decoder"]

            # Verify UV -> TexImage -> Decoder -> Biome Tint
            self.assertTrue(any(l.from_node == attr_uv and l.to_node == tex_grass for l in links))
            self.assertTrue(any(l.from_node == tex_grass and l.to_node == decoder_node for l in links))
            self.assertTrue(any(l.from_node == decoder_node and l.to_node == biome_node for l in links))


if __name__ == "__main__":
    unittest.main()
