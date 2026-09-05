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

# Bootstrap MoziToolKit package (also activates the isolated test sandbox)
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

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
    TINT_TYPE_DRY_FOLIAGE,
    TINT_TYPE_WATER,
    TINT_TYPE_HARDCODED,
    get_colormap_uv,
    sample_colormap_pixel,
    blend_biome_colors,
    classify_tint_category,
)
from MoziToolKit.utils.materials.pack import ZipResourcePack, ResourcePackStack
from MoziToolKit.utils.materials.constants import (
    ATTR_BIOME_TINT_DATA,
    ATTR_BIOME_TINT_COLOR,
    ATTR_COLORMAP_UV,
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

    def test_canonical_biomes_count_and_fields(self):
        """Verify all 66 biomes from 26.2 are present with all required properties."""
        self.assertEqual(len(BIOME_PALETTES), 66)
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
        img.putpixel((50, 173), (255, 0, 0))
        col = sample_colormap_pixel(img, 0.8, 0.4)
        self.assertAlmostEqual(col[0], 1.0, places=2)
        self.assertAlmostEqual(col[1], 0.0, places=2)
        self.assertAlmostEqual(col[2], 0.0, places=2)

    def test_blend_biome_colors(self):
        """Test smooth multi-biome transition blending (群系过渡)."""
        plains_col = get_biome_colors("PLAINS")["grass_linear"]
        forest_col = get_biome_colors("FOREST")["grass_linear"]
        blended = blend_biome_colors([("PLAINS", 0.5), ("FOREST", 0.5)], tint_type="grass")
        expected_r = (plains_col[0] + forest_col[0]) / 2.0
        expected_g = (plains_col[1] + forest_col[1]) / 2.0
        expected_b = (plains_col[2] + forest_col[2]) / 2.0
        self.assertAlmostEqual(blended[0], expected_r, places=4)
        self.assertAlmostEqual(blended[1], expected_g, places=4)
        self.assertAlmostEqual(blended[2], expected_b, places=4)


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
            "Tint Color", "Enable Tint"
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
        from utils.materials.pack import ResourcePackStack
        stack = ResourcePackStack([self.zip_path])
        stack.precompile(material_mode="STANDALONE")

        params = {
            "pack_stack": stack,
            "material_mode": "STANDALONE",
            "biome_preset": "SWAMP",
            "pack_textures": False,
            "use_cache": True,
        }
        res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[self.obj])
        self.assertTrue(res.is_success, msg=res.message)

        # Standalone mode contract: NO atlas or biome tint attributes on the mesh
        mesh = self.obj.data
        tint_data_attr = mesh.attributes.get(ATTR_BIOME_TINT_DATA)
        tint_color_attr = mesh.attributes.get(ATTR_BIOME_TINT_COLOR)
        self.assertIsNone(tint_data_attr)
        self.assertIsNone(tint_color_attr)

        # Standalone mode contract: parameters are written directly to material node inputs
        mat = self.obj.data.materials[0]
        self.assertIsNotNone(mat)
        self.assertTrue(mat.use_nodes)
        biome_tint_node = mat.node_tree.nodes.get("MC Biome Tint")
        self.assertIsNotNone(biome_tint_node)

        # Grass block should have tint_weight == 1.0
        self.assertAlmostEqual(biome_tint_node.inputs["Tint Weight"].default_value, 1.0, places=2)

        # Swamp grass color check (linear)
        swamp_colors = get_biome_colors("SWAMP")
        expected_r, expected_g, expected_b, _ = swamp_colors["grass_linear"]
        actual_col = biome_tint_node.inputs["Tint Color"].default_value
        self.assertAlmostEqual(actual_col[0], expected_r, places=2)
        self.assertAlmostEqual(actual_col[1], expected_g, places=2)
        self.assertAlmostEqual(actual_col[2], expected_b, places=2)

    def test_atlas_biome_preset_pipeline(self):
        from utils.materials.pack import ResourcePackStack
        stack = ResourcePackStack([self.zip_path])
        stack.precompile(material_mode="ATLAS")

        params = {
            "pack_stack": stack,
            "material_mode": "ATLAS",
            "biome_preset": "JUNGLE",
            "pack_textures": False,
            "use_cache": True,
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

        from utils.materials.pack import ResourcePackStack
        stack = ResourcePackStack([self.zip_path])
        stack.precompile(material_mode="STANDALONE")

        params = {
            "pack_stack": stack,
            "material_mode": "STANDALONE",
            "biome_preset": "PLAINS",
            "pack_textures": False,
            "use_cache": True,
        }
        res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[self.obj])
        self.assertTrue(res.is_success, msg=res.message)

        # In standalone mode, mesh has no tint attributes; material node has overlay weights configured
        mesh = self.obj.data
        tint_data_attr = mesh.attributes.get(ATTR_BIOME_TINT_DATA)
        self.assertIsNone(tint_data_attr)

        mat = self.obj.data.materials[0]
        self.assertIsNotNone(mat)
        biome_tint_node = mat.node_tree.nodes.get("MC Biome Tint")
        self.assertIsNotNone(biome_tint_node)
        self.assertAlmostEqual(biome_tint_node.inputs["Base Tint Weight"].default_value, 0.0, places=2)
        self.assertAlmostEqual(biome_tint_node.inputs["Overlay Tint Weight"].default_value, 1.0, places=2)

    def test_atlas_overlay_addressing_and_cleanup(self):
        """Verify overlay companion is mapped to base tile and cleanup releases memory."""
        out_dir = Path(self.temp_dir) / "atlas_overlay_out"
        gen = AtlasGenerator(self.zip_path)
        gen.build(out_dir)

        mapping_file = out_dir / "atlas_mapping.json"
        self.assertTrue(mapping_file.exists())
        with open(mapping_file, "r", encoding="utf-8") as f:
            mapping = json.load(f)

        texs = mapping.get("textures", {})
        # grass_block_side should have has_overlay = True
        side_loc = texs.get("minecraft:block/grass_block_side") or texs.get("grass_block_side")
        self.assertIsNotNone(side_loc)
        self.assertTrue(side_loc.get("has_overlay"))

        # grass_block_side_overlay should resolve to the same chunk and pixel coordinates
        overlay_loc = texs.get("minecraft:block/grass_block_side_overlay") or texs.get("grass_block_side_overlay")
        self.assertIsNotNone(overlay_loc)
        self.assertEqual(overlay_loc.get("chunk_id"), side_loc.get("chunk_id"))
        self.assertEqual(overlay_loc.get("pixel_x"), side_loc.get("pixel_x"))
        self.assertEqual(overlay_loc.get("pixel_y"), side_loc.get("pixel_y"))

        # Test addressing resolver
        from MoziToolKit.utils.materials.atlas.addressing import AtlasAddressResolver
        resolver = AtlasAddressResolver(mapping)
        res = resolver.lookup_texture("minecraft:block/grass_block_side_overlay")
        self.assertIsNotNone(res)
        self.assertTrue(res.get("has_overlay"))
        self.assertEqual(res.get("pixel_x"), side_loc.get("pixel_x"))

        # Check cleanup cleared internal dicts
        self.assertEqual(len(gen.static_textures), 0)
        self.assertEqual(len(gen.static_by_ns_cat), 0)

    def test_animated_pbr_channel_vertical_tiling(self):
        """Verify 1-frame PBR companion textures tile vertically across multi-frame animated textures."""
        from MoziToolKit.utils.materials.atlas.chunk_packer import _paste_channel_tiled_vertically

        # Create canvas for 4-frame animation strip (16x64)
        canvas = Image.new("RGBA", (16, 64), (0, 0, 0, 0))
        # Create 1-frame PBR companion (16x16) with distinct pixel at (2, 2)
        single_frame_pbr = Image.new("RGBA", (16, 16), (100, 100, 100, 255))
        single_frame_pbr.putpixel((2, 2), (255, 0, 0, 255))

        _paste_channel_tiled_vertically(canvas, single_frame_pbr, x_offset=0, target_w=16, target_h=64)

        # Verify that each of the 4 frames received the tiled PBR frame without vertical stretching
        for frame_idx in range(4):
            y_base = frame_idx * 16
            # The pixel at (2, 2) relative to frame should be red
            self.assertEqual(canvas.getpixel((2, y_base + 2)), (255, 0, 0, 255))
            # The pixel at (2, 3) relative to frame should be the base color (not stretched red)
            self.assertEqual(canvas.getpixel((2, y_base + 3)), (100, 100, 100, 255))

    def test_biome_enum_items(self):
        """Verify BIOME_ENUM_ITEMS export and structure."""
        from MoziToolKit.utils.materials.biome import BIOME_ENUM_ITEMS
        self.assertGreaterEqual(len(BIOME_ENUM_ITEMS), 66)
        self.assertEqual(BIOME_ENUM_ITEMS[0][0], "PLAINS")
        for item in BIOME_ENUM_ITEMS:
            self.assertEqual(len(item), 3)
            self.assertIsInstance(item[0], str)
            self.assertIsInstance(item[1], str)
            self.assertIsInstance(item[2], str)

    def test_operator_replace_material_biome_prop(self):
        """Verify MOZI_OT_replace_material exposes biome_preset property."""
        from MoziToolKit.operators.object.op_replace_material import MOZI_OT_replace_material
        self.assertTrue(
            "biome_preset" in getattr(MOZI_OT_replace_material, "__annotations__", {})
            or hasattr(MOZI_OT_replace_material, "biome_preset")
        )

    def test_custom_biome_tint_attributes_routing(self):
        """Verify compute_biome_tint_attributes routes custom biomes to HARDCODED and standard biomes to GRASS."""
        from MoziToolKit.utils.materials.pipeline.mesh_attributes import compute_biome_tint_attributes
        poly_map = {
            0: {"tint_type": TINT_TYPE_GRASS, "tint_weight": 1.0},
            1: {"tint_type": TINT_TYPE_FOLIAGE, "tint_weight": 1.0},
        }

        # 1. Custom grass biome (SWAMP, BADLANDS, CHERRY_GROVE)
        packed_swamp, colors_swamp, uvs_swamp = compute_biome_tint_attributes(2, poly_map, biome_preset="SWAMP")
        # Swamp grass has custom color -> tint_type should be TINT_TYPE_HARDCODED (4.0)
        self.assertEqual(packed_swamp[0][3], float(TINT_TYPE_HARDCODED))
        swamp_colors = get_biome_colors("SWAMP")
        self.assertEqual(colors_swamp[0], swamp_colors["grass_linear"])

        # 2. Standard colormap biome (PLAINS, JUNGLE)
        packed_plains, colors_plains, uvs_plains = compute_biome_tint_attributes(2, poly_map, biome_preset="PLAINS")
        # Plains grass uses standard colormap -> tint_type should be TINT_TYPE_GRASS (1.0)
        self.assertEqual(packed_plains[0][3], float(TINT_TYPE_GRASS))

    def test_instant_biome_update_atlas(self):
        """Verify update_object_biome updates Atlas mesh face attributes instantly."""
        from MoziToolKit.utils.materials.biome.updater import update_object_biome, is_mtk_object
        from MoziToolKit.utils.materials.pipeline.mesh_attributes import (
            ATTR_BIOME_TINT_DATA,
            ATTR_BIOME_TINT_COLOR,
            ATTR_SOURCE_TEXTURE_KEY,
            ATTR_ATLAS_CHUNK_ID,
        )

        mesh = bpy.data.meshes.new("test_atlas_obj_mesh")
        obj = bpy.data.objects.new("test_atlas_obj", mesh)
        bpy.context.collection.objects.link(obj)

        import bmesh
        bm = bmesh.new()
        v1 = bm.verts.new((0, 0, 0))
        v2 = bm.verts.new((1, 0, 0))
        v3 = bm.verts.new((1, 1, 0))
        v4 = bm.verts.new((0, 1, 0))
        bm.faces.new((v1, v2, v3, v4))
        bm.to_mesh(mesh)
        bm.free()

        attr_key = mesh.attributes.new(name=ATTR_SOURCE_TEXTURE_KEY, type='STRING', domain='FACE')
        attr_key.data[0].value = b"minecraft:block/grass_block_top"
        attr_chunk = mesh.attributes.new(name=ATTR_ATLAS_CHUNK_ID, type='INT', domain='FACE')
        attr_chunk.data[0].value = 0

        self.assertTrue(is_mtk_object(obj))

        # Switch to SWAMP
        success = update_object_biome(obj, "SWAMP")
        self.assertTrue(success)
        self.assertEqual(obj.get("mtk:biome_preset"), "SWAMP")

        tint_data = mesh.attributes.get(ATTR_BIOME_TINT_DATA)
        tint_color = mesh.attributes.get(ATTR_BIOME_TINT_COLOR)
        self.assertIsNotNone(tint_data)
        self.assertIsNotNone(tint_color)
        self.assertEqual(tint_data.data[0].color[3], float(TINT_TYPE_HARDCODED))

        # Switch to JUNGLE
        success = update_object_biome(obj, "JUNGLE")
        self.assertTrue(success)
        self.assertEqual(obj.get("mtk:biome_preset"), "JUNGLE")
        self.assertEqual(tint_data.data[0].color[3], float(TINT_TYPE_GRASS))

        bpy.data.objects.remove(obj)

    def test_instant_biome_update_standalone(self):
        """Verify update_object_biome updates Standalone material nodes instantly."""
        from MoziToolKit.utils.materials.biome.updater import update_object_biome
        from MoziToolKit.utils.node_groups.biome import ensure_biome_tint, ensure_colormap_sampler

        mesh = bpy.data.meshes.new("test_standalone_obj_mesh")
        obj = bpy.data.objects.new("test_standalone_obj", mesh)
        bpy.context.collection.objects.link(obj)

        mat = bpy.data.materials.new(name="mtk:minecraft:grass_block_top")
        mat.use_nodes = True
        obj.data.materials.append(mat)

        nt = mat.node_tree
        tint_group = ensure_biome_tint()
        tint_node = nt.nodes.new("ShaderNodeGroup")
        tint_node.name = "MC Biome Tint"
        tint_node.node_tree = tint_group

        sampler_group = ensure_colormap_sampler()
        sampler_node = nt.nodes.new("ShaderNodeGroup")
        sampler_node.name = "MC Biome Colormap Sampler"
        sampler_node.node_tree = sampler_group

        # Switch to SWAMP
        success = update_object_biome(obj, "SWAMP")
        self.assertTrue(success)
        swamp_colors = get_biome_colors("SWAMP")
        self.assertAlmostEqual(tint_node.inputs["Tint Color"].default_value[0], swamp_colors["grass_linear"][0], places=2)

        # Switch to JUNGLE
        success = update_object_biome(obj, "JUNGLE")
        self.assertTrue(success)
        jungle_colors = get_biome_colors("JUNGLE")
        self.assertAlmostEqual(sampler_node.inputs["Temperature"].default_value, jungle_colors["temperature"], places=2)
        self.assertAlmostEqual(sampler_node.inputs["Humidity"].default_value, jungle_colors["humidity"], places=2)

        bpy.data.objects.remove(obj)

    def test_mesh_attributes_multi_biome_transition(self):
        """Test compute_biome_tint_attributes with multi-biome transition input."""
        from MoziToolKit.utils.materials.pipeline.mesh_attributes import compute_biome_tint_attributes
        poly_map = {
            0: {"tint_type": TINT_TYPE_GRASS, "tint_weight": 1.0},
            1: {"tint_type": TINT_TYPE_FOLIAGE, "tint_weight": 1.0},
            2: {"tint_type": TINT_TYPE_NONE, "tint_weight": 0.0},
        }
        packed, colors, uvs = compute_biome_tint_attributes(3, poly_map, biome_preset="PLAINS")
        self.assertEqual(len(colors), 3)
        self.assertEqual(len(uvs), 3)
        self.assertAlmostEqual(colors[0][0], get_biome_colors("PLAINS")["grass_linear"][0], places=3)

        packed_tr, colors_tr, uvs_tr = compute_biome_tint_attributes(3, poly_map, biome_preset=[("PLAINS", 0.5), ("FOREST", 0.5)])
        self.assertEqual(len(colors_tr), 3)
        self.assertEqual(len(uvs_tr), 3)
        expected_grass = blend_biome_colors([("PLAINS", 0.5), ("FOREST", 0.5)], "grass")
        self.assertAlmostEqual(colors_tr[0][0], expected_grass[0], places=3)

    def test_rebuild_material_with_colormap_sampler(self):
        """Test that rebuild_material creates MC Biome Colormap Sampler and links to colormap texture."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            col_dir = tmppath / "assets" / "minecraft" / "textures" / "colormap"
            col_dir.mkdir(parents=True, exist_ok=True)
            col_img = Image.new("RGB", (256, 256), color=(145, 189, 89))
            col_img.save(col_dir / "grass.png")

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

            node_names = [n.name for n in mat.node_tree.nodes]
            self.assertIn("MC Biome Tint", node_names)
            self.assertIn("MC Biome Colormap Sampler", node_names)
            self.assertIn("Colormap Grass", node_names)

            sampler_node = mat.node_tree.nodes["MC Biome Colormap Sampler"]
            self.assertAlmostEqual(sampler_node.inputs["Temperature"].default_value, 0.7, places=2)
            self.assertAlmostEqual(sampler_node.inputs["Humidity"].default_value, 0.8, places=2)

            colormap_node = mat.node_tree.nodes["Colormap Grass"]
            self.assertIsNotNone(colormap_node.image)
            self.assertTrue(any(l.from_node == sampler_node and l.to_node == colormap_node for l in mat.node_tree.links))
            self.assertTrue(any(l.from_node == colormap_node and l.to_node.name == "MC Biome Tint" for l in mat.node_tree.links))

    def test_colormap_decoder_node_group(self):
        """Test generation and socket structure of MC_Biome_Colormap_Decoder node group."""
        from MoziToolKit.utils.node_groups.biome import ensure_colormap_decoder
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
        from MoziToolKit.utils.materials.atlas.builder import add_packed_biome_attribute_nodes
        from MoziToolKit.utils.node_groups.biome import ensure_biome_tint

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

            self.assertTrue(any(l.from_node == attr_uv and l.to_node == tex_grass for l in links))
            self.assertTrue(any(l.from_node == tex_grass and l.to_node == decoder_node for l in links))
            self.assertTrue(any(l.from_node == decoder_node and l.to_node == biome_node for l in links))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])


