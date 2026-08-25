"""
Unit tests for Minecraft Biome Tinting, Overlay Atlas, and Colormap systems.
"""

import sys
import unittest
import tempfile
import shutil
import zipfile
import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
PARENT_DIR = PROJECT_DIR.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from PIL import Image
import bpy

from MoziToolKit.utils.materials.biome import (
    hex_to_linear_rgba,
    linear_rgba_to_hex,
    hex_to_rgb,
    hex_to_rgba,
    get_biome_colors,
    BiomeResolver,
    BIOME_PALETTES,
    HARDCODED_BLOCK_TINTS,
    TINT_TYPE_NONE,
    TINT_TYPE_GRASS,
    TINT_TYPE_FOLIAGE,
    TINT_TYPE_WATER,
    TINT_TYPE_HARDCODED,
)
from MoziToolKit.utils.materials.constants import (
    ATTR_BIOME_TINT_DATA,
    ATTR_BIOME_TINT_COLOR,
)
from MoziToolKit.utils.node_groups.biome import ensure_biome_tint, ensure_colormap_sampler
from MoziToolKit.utils.materials.nodes.builder import rebuild_material
from MoziToolKit.utils.materials.atlas.generator import AtlasGenerator
from MoziToolKit.utils.materials.atlas.builder import build_atlas_chunk_materials
from MoziToolKit.pipeline.presets import run_preset_pipeline


class TestBiomeColors(unittest.TestCase):
    """Test sRGB/Linear conversions and biome color palettes."""

    def test_hex_conversion(self):
        # White
        rgba = hex_to_linear_rgba("#FFFFFF")
        self.assertAlmostEqual(rgba[0], 1.0, places=3)
        self.assertAlmostEqual(rgba[1], 1.0, places=3)
        self.assertAlmostEqual(rgba[2], 1.0, places=3)
        self.assertAlmostEqual(rgba[3], 1.0, places=3)

        # Black
        rgba = hex_to_linear_rgba("#000000")
        self.assertAlmostEqual(rgba[0], 0.0, places=3)
        self.assertAlmostEqual(rgba[1], 0.0, places=3)
        self.assertAlmostEqual(rgba[2], 0.0, places=3)

        # Roundtrip test
        hex_val = "#91BD59"
        lin = hex_to_linear_rgba(hex_val)
        hex_out = linear_rgba_to_hex(lin)
        self.assertEqual(hex_val.upper(), hex_out.upper())

    def test_hex_to_rgb_and_rgba(self):
        """Verify hex_to_rgb and hex_to_rgba 6-digit and 8-digit handling."""
        rgb = hex_to_rgb("#FF8000")
        self.assertAlmostEqual(rgb[0], 1.0, places=2)
        self.assertAlmostEqual(rgb[1], 0.5019, places=2)
        self.assertAlmostEqual(rgb[2], 0.0, places=2)

        rgba = hex_to_rgba("#FF800080")
        self.assertAlmostEqual(rgba[0], 1.0, places=2)
        self.assertAlmostEqual(rgba[1], 0.5019, places=2)
        self.assertAlmostEqual(rgba[2], 0.0, places=2)
        self.assertAlmostEqual(rgba[3], 0.5019, places=2)

    def test_get_biome_colors(self):
        plains = get_biome_colors("PLAINS")
        self.assertIn("grass_hex", plains)
        self.assertIn("grass_linear", plains)
        self.assertIn("foliage_linear", plains)
        self.assertIn("water_linear", plains)
        self.assertIn("temperature", plains)
        self.assertIn("humidity", plains)

        swamp = get_biome_colors("SWAMP")
        self.assertEqual(swamp["grass_hex"].upper(), "#6A7039")

        # Unknown biome fallback to Plains
        unknown = get_biome_colors("NON_EXISTENT_BIOME")
        self.assertEqual(unknown["name"], "Plains")


class TestBiomeResolver(unittest.TestCase):
    """Test BiomeResolver tint categorization and overlay discovery."""

    def setUp(self):
        self.resolver = BiomeResolver()

    def test_tint_categorization(self):
        # Grass block top
        info_grass = self.resolver.get_tint_info("grass_block_top")
        self.assertEqual(info_grass["tint_type"], TINT_TYPE_GRASS)
        self.assertEqual(info_grass["tint_weight"], 1.0)
        self.assertFalse(info_grass["is_hardcoded"])

        # Foliage (oak leaves)
        info_leaves = self.resolver.get_tint_info("oak_leaves")
        self.assertEqual(info_leaves["tint_type"], TINT_TYPE_FOLIAGE)
        self.assertEqual(info_leaves["tint_weight"], 1.0)
        self.assertFalse(info_leaves["is_hardcoded"])

        # Water
        info_water = self.resolver.get_tint_info("water_still")
        self.assertEqual(info_water["tint_type"], TINT_TYPE_WATER)
        self.assertEqual(info_water["tint_weight"], 1.0)

        # Hardcoded tints (Spruce & Birch)
        info_spruce = self.resolver.get_tint_info("spruce_leaves")
        self.assertEqual(info_spruce["tint_type"], TINT_TYPE_HARDCODED)
        self.assertTrue(info_spruce["is_hardcoded"])
        self.assertEqual(info_spruce["hardcoded_hex"].upper(), "#619961")

        info_birch = self.resolver.get_tint_info("birch_leaves")
        self.assertEqual(info_birch["tint_type"], TINT_TYPE_HARDCODED)
        self.assertTrue(info_birch["is_hardcoded"])
        self.assertEqual(info_birch["hardcoded_hex"].upper(), "#80A755")

        # Untinted (Stone)
        info_stone = self.resolver.get_tint_info("stone")
        self.assertEqual(info_stone["tint_type"], TINT_TYPE_NONE)
        self.assertEqual(info_stone["tint_weight"], 0.0)

    def test_overlay_detection(self):
        overlay = self.resolver.get_overlay_texture("grass_block_side")
        self.assertEqual(overlay, "grass_block_side_overlay")

        # Check tint info on grass_block_side: face is tinted (1.0), base is untinted (0.0), overlay is tinted (1.0)
        info_side = self.resolver.get_tint_info("grass_block_side")
        self.assertEqual(info_side["tint_type"], TINT_TYPE_GRASS)
        self.assertEqual(info_side["tint_weight"], 1.0)
        self.assertEqual(info_side["base_tint_weight"], 0.0)
        self.assertEqual(info_side["overlay_tint_weight"], 1.0)
        self.assertTrue(info_side["has_overlay"])
        self.assertEqual(info_side["overlay_texture"], "grass_block_side_overlay")

        no_overlay = self.resolver.get_overlay_texture("stone")
        self.assertIsNone(no_overlay)

    def test_seagrass_tint_classification_is_none(self):
        """Verify seagrass and aquatic plants are NOT misclassified as grass tint."""
        resolver = BiomeResolver()
        underwater_stems = [
            "seagrass", "tall_seagrass_top", "tall_seagrass_bottom",
            "tall_seagrass", "seagrass_bottom", "kelp", "kelp_plant",
        ]
        for stem in underwater_stems:
            info = resolver.get_tint_info(stem)
            self.assertEqual(info["tint_type"], TINT_TYPE_NONE)
            self.assertEqual(info["tint_category"], "none")

        grass_stems = [
            "grass_block_top", "grass", "short_grass", "tall_grass_top",
            "tall_grass_bottom", "tall_grass", "fern", "large_fern_top", "large_fern_bottom",
        ]
        for stem in grass_stems:
            info = resolver.get_tint_info(stem)
            self.assertEqual(info["tint_type"], TINT_TYPE_GRASS)
            self.assertEqual(info["tint_category"], "grass")

        foliage_stems = ["oak_leaves", "jungle_leaves", "acacia_leaves", "dark_oak_leaves", "vine"]
        for stem in foliage_stems:
            info = resolver.get_tint_info(stem)
            self.assertEqual(info["tint_type"], TINT_TYPE_FOLIAGE)

    def test_model_tintindex_does_not_imply_biome_tint(self):
        """Vanilla stonecutter_saw has tintindex 0 but no biome colour provider."""
        resolver = BiomeResolver(models={
            "stonecutter": {
                "textures": {"saw": "minecraft:block/stonecutter_saw"},
                "elements": [{"faces": {"north": {"texture": "#saw", "tintindex": 0}}}],
            }
        })
        info = resolver.get_tint_info("stonecutter_saw")
        self.assertEqual(info["tint_type"], TINT_TYPE_NONE)
        self.assertEqual(info["tint_weight"], 0.0)


class TestBiomeNodeGroups(unittest.TestCase):
    """Test MC_Biome_Tint and MC_Biome_Colormap_Sampler node group definitions."""

    def test_ensure_biome_tint(self):
        group = ensure_biome_tint()
        self.assertIsNotNone(group)
        self.assertEqual(group.name, "MC_Biome_Tint")

        # Check required inputs
        input_names = [item.name for item in group.interface.items_tree if item.item_type == 'SOCKET' and item.in_out == 'INPUT']
        expected_inputs = [
            "Base Color", "Base Alpha", "Overlay Color", "Overlay Alpha",
            "Base Tint Weight", "Overlay Tint Weight", "Tint Weight",
            "Tint Color", "Hardcoded Color", "Use Hardcoded", "Enable Tint"
        ]
        for name in expected_inputs:
            self.assertIn(name, input_names)

        # Check outputs
        output_names = [item.name for item in group.interface.items_tree if item.item_type == 'SOCKET' and item.in_out == 'OUTPUT']
        self.assertIn("Color", output_names)
        self.assertIn("Alpha", output_names)

    def test_ensure_colormap_sampler(self):
        group = ensure_colormap_sampler()
        self.assertIsNotNone(group)
        self.assertEqual(group.name, "MC_Biome_Colormap_Sampler")


class TestBiomeMaterialBuilding(unittest.TestCase):
    """Test Standalone and Atlas material node connections for Biome Tint."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_standalone_material_nodes(self):
        # Create a test texture
        tex_path = self.temp_dir / "grass_block_top.png"
        img = Image.new("RGBA", (16, 16), (128, 128, 128, 255))
        img.save(tex_path)

        mat = bpy.data.materials.new("TestGrassMat")
        texture_info = {
            "namespace": "minecraft",
            "texture_name": "grass_block_top",
            "albedo": tex_path,
        }
        success = rebuild_material(mat, texture_info)
        self.assertTrue(success)

        # Verify MC Biome Tint node exists and is connected
        nodes = mat.node_tree.nodes
        biome_tint_node = nodes.get("MC Biome Tint")
        self.assertIsNotNone(biome_tint_node)
        self.assertEqual(biome_tint_node.type, "GROUP")

        decoder_node = nodes.get("LabPBR 1.3 Decoder")
        self.assertIsNotNone(decoder_node)

        # Verify links: Biome Tint -> Decoder Albedo
        links = mat.node_tree.links
        col_linked = any(
            link.from_node == biome_tint_node and link.to_node == decoder_node
            and link.to_socket.name == "Albedo Color"
            for link in links
        )
        self.assertTrue(col_linked)

    def test_standalone_material_untinted_omits_biome_tint_node(self):
        """Untinted textures (stone, iron_sword, etc.) must not create MC Biome Tint node group."""
        tex_path = self.temp_dir / "stone.png"
        img = Image.new("RGBA", (16, 16), (128, 128, 128, 255))
        img.save(tex_path)

        mat = bpy.data.materials.new("TestStoneMat")
        texture_info = {
            "namespace": "minecraft",
            "texture_name": "stone",
            "albedo": tex_path,
        }
        success = rebuild_material(mat, texture_info)
        self.assertTrue(success)

        nodes = mat.node_tree.nodes
        biome_tint_node = nodes.get("MC Biome Tint")
        self.assertIsNone(biome_tint_node)

        decoder_node = nodes.get("LabPBR 1.3 Decoder")
        self.assertIsNotNone(decoder_node)

        # Verify Albedo connects directly to Decoder Albedo Color
        tex_albedo = nodes.get("Tex Static (Albedo)")
        self.assertIsNotNone(tex_albedo)
        direct_linked = any(
            link.from_node == tex_albedo and link.to_node == decoder_node
            and link.to_socket.name == "Albedo Color"
            for link in mat.node_tree.links
        )
        self.assertTrue(direct_linked)

    def test_standalone_material_overlay_nodes(self):
        """Textures with overlay (grass_block_side) must create MC Biome Tint and Overlay Image node."""
        base_path = self.temp_dir / "grass_block_side.png"
        overlay_path = self.temp_dir / "grass_block_side_overlay.png"
        Image.new("RGBA", (16, 16), (128, 64, 32, 255)).save(base_path)
        Image.new("RGBA", (16, 16), (200, 200, 200, 255)).save(overlay_path)

        mat = bpy.data.materials.new("TestGrassSideMat")
        texture_info = {
            "namespace": "minecraft",
            "texture_name": "grass_block_side",
            "albedo": base_path,
            "overlay": overlay_path,
        }
        success = rebuild_material(mat, texture_info)
        self.assertTrue(success)

        nodes = mat.node_tree.nodes
        biome_tint_node = nodes.get("MC Biome Tint")
        self.assertIsNotNone(biome_tint_node)

        tex_overlay = nodes.get("Tex Static (Overlay)")
        self.assertIsNotNone(tex_overlay)
        self.assertIsNotNone(tex_overlay.image)


class TestBiomePipelineIntegration(unittest.TestCase):
    """Test full pipeline execution with Biome Presets in Standalone and Atlas modes."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.zip_path = self.temp_dir / "test_pack.zip"

        # Create resource pack with grass, leaves, and stone
        with zipfile.ZipFile(self.zip_path, "w") as zf:
            for name in ["grass_block_top", "oak_leaves", "stone", "grass_block_side", "grass_block_side_overlay"]:
                im = Image.new("RGBA", (16, 16), (200, 200, 200, 255))
                im_path = self.temp_dir / f"{name}.png"
                im.save(im_path)
                zf.write(im_path, f"assets/minecraft/textures/block/{name}.png")

        # Create test mesh
        mesh = bpy.data.meshes.new("BiomeTestMesh")
        self.obj = bpy.data.objects.new("BiomeTestObj", mesh)
        bpy.context.scene.collection.objects.link(self.obj)

        # Simple quad
        mesh.from_pydata(
            [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
            [],
            [(0, 1, 2, 3)]
        )
        mesh.update()

        # Add initial placeholder material
        mat = bpy.data.materials.new("grass_block_top")
        mat.use_nodes = True
        self.obj.data.materials.append(mat)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        if self.obj:
            bpy.data.objects.remove(self.obj)

    def test_standalone_biome_preset_pipeline(self):
        params = {
            "zip_path": str(self.zip_path),
            "material_mode": "STANDALONE",
            "biome_preset": "SWAMP",
            "pack_textures": False,
            "use_cache": False,
        }
        res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[self.obj])
        self.assertTrue(res.is_success, msg=res.message)

        # Check mesh attributes
        mesh = self.obj.data
        tint_data_attr = mesh.attributes.get(ATTR_BIOME_TINT_DATA)
        tint_color_attr = mesh.attributes.get(ATTR_BIOME_TINT_COLOR)
        self.assertIsNotNone(tint_data_attr)
        self.assertIsNotNone(tint_color_attr)

        # Grass block should have tint_weight == 1.0
        self.assertAlmostEqual(tint_data_attr.data[0].color[2], 1.0, places=2)

        # Swamp grass color check (linear)
        swamp_colors = get_biome_colors("SWAMP")
        expected_r, expected_g, expected_b, _ = swamp_colors["grass_linear"]
        actual_col = tint_color_attr.data[0].color
        self.assertAlmostEqual(actual_col[0], expected_r, places=2)
        self.assertAlmostEqual(actual_col[1], expected_g, places=2)
        self.assertAlmostEqual(actual_col[2], expected_b, places=2)

    def test_atlas_biome_preset_pipeline(self):
        params = {
            "zip_path": str(self.zip_path),
            "material_mode": "ATLAS",
            "biome_preset": "JUNGLE",
            "pack_textures": False,
            "use_cache": False,
        }
        res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[self.obj])
        self.assertTrue(res.is_success, msg=res.message)

        # Check mesh attributes
        mesh = self.obj.data
        tint_data_attr = mesh.attributes.get(ATTR_BIOME_TINT_DATA)
        tint_color_attr = mesh.attributes.get(ATTR_BIOME_TINT_COLOR)
        self.assertIsNotNone(tint_data_attr)
        self.assertIsNotNone(tint_color_attr)
        self.assertAlmostEqual(tint_data_attr.data[0].color[2], 1.0, places=2)

        # Jungle grass color check
        jungle_colors = get_biome_colors("JUNGLE")
        expected_r, expected_g, expected_b, _ = jungle_colors["grass_linear"]
        actual_col = tint_color_attr.data[0].color
        self.assertAlmostEqual(actual_col[0], expected_r, places=2)
        self.assertAlmostEqual(actual_col[1], expected_g, places=2)
        self.assertAlmostEqual(actual_col[2], expected_b, places=2)

    def test_overlay_face_pipeline(self):
        # Change initial material to grass_block_side
        mat_side = bpy.data.materials.new("grass_block_side")
        mat_side.use_nodes = True
        self.obj.data.materials.clear()
        self.obj.data.materials.append(mat_side)

        params = {
            "zip_path": str(self.zip_path),
            "material_mode": "STANDALONE",
            "biome_preset": "PLAINS",
            "pack_textures": False,
            "use_cache": False,
        }
        res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[self.obj])
        self.assertTrue(res.is_success, msg=res.message)

        mesh = self.obj.data
        tint_data_attr = mesh.attributes.get(ATTR_BIOME_TINT_DATA)
        self.assertIsNotNone(tint_data_attr)

        # For grass_block_side: tint_weight=1.0, base_tint_weight=0.0 (dirt not tinted), overlay_tint_weight=1.0 (grass fringe tinted)
        tint_data = tint_data_attr.data[0].color
        self.assertAlmostEqual(tint_data[2], 1.0, places=2)
        self.assertAlmostEqual(tint_data[0], 0.0, places=2)
        self.assertAlmostEqual(tint_data[1], 1.0, places=2)
