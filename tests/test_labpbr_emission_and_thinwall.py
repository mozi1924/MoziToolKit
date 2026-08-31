"""Unit tests for LabPBR Hardcoded Emission, boolean Thin Wall socket, and Minecraft catalog."""

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

from utils.node_groups.labpbr import (
    LABPBR_GROUP_NAME,
    LABPBR_TEMPLATE_VERSION,
    LABPBR_INTERFACE,
    ensure_labpbr_decoder,
    assert_reference_shape,
    reference_shape_errors,
)
from utils.materials.catalog import (
    get_block_emission_strength,
    is_thin_wall_block,
    get_block_transmission_weight,
    is_transmissive_block,
    VANILLA_STATIC_EMISSION_LEVELS,
    VANILLA_THIN_WALL_EXACT_BLOCKS,
    VANILLA_TRANSMISSION_EXACT_BLOCKS,
)
from utils.materials.nodes.builder import rebuild_material


class TestLabPBRIssuesAndCatalog(unittest.TestCase):

    def setUp(self):
        for ng in list(bpy.data.node_groups):
            if LABPBR_GROUP_NAME in ng.name:
                bpy.data.node_groups.remove(ng)

    def test_labpbr_decoder_interface_and_sockets(self):
        """Verify LabPBR 1.3 Decoder v16 public interface and socket configurations."""
        ng = ensure_labpbr_decoder()
        self.assertIsNotNone(ng)
        self.assertEqual(ng.get("mozi_template_version"), 16)
        self.assertEqual(reference_shape_errors(ng), ())
        assert_reference_shape(ng)

        sockets = {s.name: s for s in ng.interface.items_tree if s.item_type == "SOCKET"}

        # Verify Thin Wall is NodeSocketBool with default False
        self.assertIn("Thin Wall", sockets)
        thin_wall = sockets["Thin Wall"]
        self.assertEqual(thin_wall.socket_type, "NodeSocketBool")
        self.assertEqual(thin_wall.default_value, False)

        # Verify Hardcoded Emission is NodeSocketFloat with 0.0..1000.0 range
        self.assertIn("Hardcoded Emission", sockets)
        hardcoded_emission = sockets["Hardcoded Emission"]
        self.assertEqual(hardcoded_emission.socket_type, "NodeSocketFloat")
        self.assertEqual(hardcoded_emission.default_value, 0.0)
        self.assertEqual(hardcoded_emission.min_value, 0.0)
        self.assertEqual(hardcoded_emission.max_value, 1000.0)

        # Verify Transmission Weight is NodeSocketFloat with 0.0..1.0 range
        self.assertIn("Transmission Weight", sockets)
        trans_weight = sockets["Transmission Weight"]
        self.assertEqual(trans_weight.socket_type, "NodeSocketFloat")
        self.assertEqual(trans_weight.default_value, 0.0)
        self.assertEqual(trans_weight.min_value, 0.0)
        self.assertEqual(trans_weight.max_value, 1.0)

        # Verify Sticker Threshold is NodeSocketFloat with 0.0..1.0 range (default 0.55)
        self.assertIn("Sticker Threshold", sockets)
        sticker_thresh = sockets["Sticker Threshold"]
        self.assertEqual(sticker_thresh.socket_type, "NodeSocketFloat")
        self.assertAlmostEqual(sticker_thresh.default_value, 0.55, places=4)
        self.assertEqual(sticker_thresh.min_value, 0.0)
        self.assertEqual(sticker_thresh.max_value, 1.0)

    def test_labpbr_decoder_wiring(self):
        """Verify that Emission, Transmission, Alpha, Clean Albedo, and Roughness mix nodes are correctly wired."""
        ng = ensure_labpbr_decoder()
        principled = ng.nodes.get("LabPBR Principled BSDF")
        self.assertIsNotNone(principled)

        # Check Thin Wall connection
        thin_links = [l for l in ng.links if l.to_node == principled and l.to_socket.name == "Thin Wall"]
        self.assertEqual(len(thin_links), 1)
        self.assertEqual(thin_links[0].from_socket.name, "Thin Wall")

        # Check Emission mix node
        mix_node = ng.nodes.get("Select Emission Mode")
        self.assertIsNotNone(mix_node)
        self.assertEqual(mix_node.data_type, "FLOAT")

        emit_links = [l for l in ng.links if l.to_node == principled and l.to_socket.name == "Emission Strength"]
        self.assertEqual(len(emit_links), 1)
        self.assertEqual(emit_links[0].from_node, mix_node)

        # Check Transmission and Alpha nodes
        eff_trans = ng.nodes.get("Final Transmission")
        self.assertIsNotNone(eff_trans)
        trans_links = [l for l in ng.links if l.to_node == principled and l.to_socket.name == "Transmission Weight"]
        self.assertEqual(len(trans_links), 1)
        self.assertEqual(trans_links[0].from_node, eff_trans)

        eff_alpha = ng.nodes.get("Final Alpha")
        self.assertIsNotNone(eff_alpha)
        alpha_links = [l for l in ng.links if l.to_node == principled and l.to_socket.name == "Alpha"]
        self.assertEqual(len(alpha_links), 1)
        self.assertEqual(alpha_links[0].from_node, eff_alpha)

        # Check Clean Albedo Color node
        clean_albedo = ng.nodes.get("Clean Albedo Color")
        self.assertIsNotNone(clean_albedo)

        # Check Roughness wiring (perceptual roughness directly into enable_roughness)
        enable_roughness = ng.nodes.get("Enable Roughness")
        self.assertIsNotNone(enable_roughness)
        rough_links = [l for l in ng.links if l.to_node == principled and l.to_socket.name == "Roughness"]
        self.assertEqual(len(rough_links), 1)
        self.assertEqual(rough_links[0].from_node, enable_roughness)

    def test_vanilla_catalog_static_emissions(self):
        """Verify static vanilla block emission calculations."""
        self.assertEqual(get_block_emission_strength("minecraft:glowstone"), 15.0)
        self.assertEqual(get_block_emission_strength("sea_lantern"), 15.0)
        self.assertEqual(get_block_emission_strength("torch"), 14.0)
        self.assertEqual(get_block_emission_strength("crying_obsidian"), 10.0)
        self.assertEqual(get_block_emission_strength("magma_block"), 3.0)
        self.assertEqual(get_block_emission_strength("stone"), 0.0)

    def test_vanilla_catalog_state_aware_emissions(self):
        """Verify state-dependent block emission calculations."""
        # Campfire
        self.assertEqual(get_block_emission_strength("campfire", {"lit": "true"}), 15.0)
        self.assertEqual(get_block_emission_strength("campfire", {"lit": "false"}), 0.0)
        self.assertEqual(get_block_emission_strength("soul_campfire", {"lit": "true"}), 10.0)

        # Furnace & Smoker
        self.assertEqual(get_block_emission_strength("furnace", {"lit": "true"}), 13.0)
        self.assertEqual(get_block_emission_strength("furnace", {"lit": "false"}), 0.0)
        self.assertEqual(get_block_emission_strength("blast_furnace", {"lit": "true"}), 13.0)
        self.assertEqual(get_block_emission_strength("smoker", {"lit": "true"}), 13.0)

        # Redstone Lamp & Torch
        self.assertEqual(get_block_emission_strength("redstone_lamp", {"lit": "true"}), 15.0)
        self.assertEqual(get_block_emission_strength("redstone_lamp", {"lit": "false"}), 0.0)
        self.assertEqual(get_block_emission_strength("redstone_torch", {"lit": "true"}), 7.0)
        self.assertEqual(get_block_emission_strength("redstone_torch", {"lit": "false"}), 0.0)

        # Copper Bulb variants
        self.assertEqual(get_block_emission_strength("copper_bulb", {"lit": "true"}), 15.0)
        self.assertEqual(get_block_emission_strength("exposed_copper_bulb", {"lit": "true"}), 12.0)
        self.assertEqual(get_block_emission_strength("weathered_copper_bulb", {"lit": "true"}), 8.0)
        self.assertEqual(get_block_emission_strength("oxidized_copper_bulb", {"lit": "true"}), 4.0)

        # Candles & Sea Pickle
        self.assertEqual(get_block_emission_strength("candle", {"lit": "true", "candles": 3}), 9.0)
        self.assertEqual(get_block_emission_strength("candle", {"lit": "false", "candles": 3}), 0.0)
        self.assertEqual(get_block_emission_strength("sea_pickle", {"waterlogged": "true", "pickles": 4}), 15.0)

        # Cave vines
        self.assertEqual(get_block_emission_strength("cave_vines", {"berries": "true"}), 14.0)
        self.assertEqual(get_block_emission_strength("cave_vines", {"berries": "false"}), 0.0)

    
    def test_non_emissive_blocks_and_textures_are_zero(self):
        """Verify that banners, colored beds/wool, corals, torchflower, etc. are NOT emissive."""
        non_emissives = [
            "banner",
            "white_banner",
            "light_blue_banner",
            "light_gray_banner",
            "light_blue_wool",
            "light_gray_bed",
            "light_blue_concrete",
            "light_weighted_pressure_plate",
            "lightning_rod",
            "fire_coral",
            "fire_coral_block",
            "fire_coral_fan",
            "torchflower",
            "torchflower_crop",
            "redstone_torch_off",
            "entity/banner/banner_base",
            "entity/shulker/shulker",
            "stone",
            "oak_planks",
        ]
        for name in non_emissives:
            self.assertEqual(
                get_block_emission_strength(name, texture_name=name),
                0.0,
                f"{name} should have 0.0 emission",
            )

    def test_vanilla_catalog_thin_wall_whitelist(self):
        """Verify that foliage, crops, and leaves are correctly identified for Thin Wall."""
        # Leaves
        self.assertTrue(is_thin_wall_block("minecraft:oak_leaves"))
        self.assertTrue(is_thin_wall_block("spruce_leaves"))
        self.assertTrue(is_thin_wall_block("cherry_leaves"))
        self.assertTrue(is_thin_wall_block("azalea_leaves"))

        # Crops & Flowers
        self.assertTrue(is_thin_wall_block("wheat"))
        self.assertTrue(is_thin_wall_block("carrots"))
        self.assertTrue(is_thin_wall_block("dandelion"))
        self.assertTrue(is_thin_wall_block("poppy"))
        self.assertTrue(is_thin_wall_block("sunflower"))
        self.assertTrue(is_thin_wall_block("pink_petals"))

        # Vines & Grass
        self.assertTrue(is_thin_wall_block("vine"))
        self.assertTrue(is_thin_wall_block("weeping_vines"))
        self.assertTrue(is_thin_wall_block("short_grass"))
        self.assertTrue(is_thin_wall_block("fern"))
        self.assertTrue(is_thin_wall_block("kelp"))
        self.assertTrue(is_thin_wall_block("sugar_cane"))

        # Non-vegetation solid blocks
        self.assertFalse(is_thin_wall_block("stone"))
        self.assertFalse(is_thin_wall_block("oak_planks"))
        self.assertFalse(is_thin_wall_block("dirt"))
        self.assertFalse(is_thin_wall_block("moss_block"))
        self.assertFalse(is_thin_wall_block("mushroom_stem"))

    def test_vanilla_catalog_transmission_whitelist(self):
        """Verify that unstained glass, stained glass, water, ice, and slime are identified for transmission."""
        transmissives = [
            "glass",
            "glass_pane",
            "minecraft:glass",
            "minecraft:glass_pane",
            "tinted_glass",
            "white_stained_glass",
            "red_stained_glass",
            "blue_stained_glass_pane",
            "water",
            "flowing_water",
            "water_still",
            "ice",
            "packed_ice",
            "blue_ice",
            "frosted_ice",
            "slime_block",
            "honey_block",
            "beacon",
        ]
        for name in transmissives:
            self.assertTrue(is_transmissive_block(name), f"{name} should be transmissive")
            self.assertEqual(get_block_transmission_weight(name), 1.0, f"{name} transmission weight should be 1.0")

        # Test Sticker Thresholds: 0.55 for glass vs 0.95 for water/ice/slime/honey
        from utils.materials.catalog import get_block_sticker_threshold
        self.assertEqual(get_block_sticker_threshold("glass"), 0.55)
        self.assertEqual(get_block_sticker_threshold("white_stained_glass"), 0.55)
        self.assertEqual(get_block_sticker_threshold("tinted_glass"), 0.55)
        self.assertEqual(get_block_sticker_threshold("water"), 0.95)
        self.assertEqual(get_block_sticker_threshold("water_still"), 0.95)
        self.assertEqual(get_block_sticker_threshold("ice"), 0.95)
        self.assertEqual(get_block_sticker_threshold("slime_block"), 0.95)
        self.assertEqual(get_block_sticker_threshold("honey_block"), 0.95)

        non_transmissives = [
            "stone",
            "oak_planks",
            "dirt",
            "oak_leaves",
            "glowstone",
            "iron_block",
        ]
        for name in non_transmissives:
            self.assertFalse(is_transmissive_block(name), f"{name} should NOT be transmissive")
            self.assertEqual(get_block_transmission_weight(name), 0.0, f"{name} transmission weight should be 0.0")

    def test_material_builder_applies_catalog_defaults(self):
        """Verify that rebuild_material configures Hardcoded Emission, Thin Wall, Transmission Weight, and Sticker Threshold."""
        mat = bpy.data.materials.new("minecraft_torch")
        tex_info = {
            "texture_name": "torch",
            "source_texture": "minecraft:block/torch",
        }
        success = rebuild_material(mat, tex_info)
        self.assertTrue(success)

        decoder = mat.node_tree.nodes.get("LabPBR 1.3 Decoder")
        self.assertIsNotNone(decoder)
        self.assertEqual(decoder.inputs["Enable PBR (0-1)"].default_value, 0.0)
        self.assertEqual(decoder.inputs["Hardcoded Emission"].default_value, 14.0)
        self.assertEqual(decoder.inputs["Thin Wall"].default_value, False)
        self.assertEqual(decoder.inputs["Transmission Weight"].default_value, 0.0)

        # Test leaves
        mat_leaves = bpy.data.materials.new("oak_leaves")
        tex_info_leaves = {
            "texture_name": "oak_leaves",
            "source_texture": "minecraft:block/oak_leaves",
        }
        success_leaves = rebuild_material(mat_leaves, tex_info_leaves)
        self.assertTrue(success_leaves)

        decoder_leaves = mat_leaves.node_tree.nodes.get("LabPBR 1.3 Decoder")
        self.assertIsNotNone(decoder_leaves)
        self.assertEqual(decoder_leaves.inputs["Hardcoded Emission"].default_value, 0.0)
        self.assertEqual(decoder_leaves.inputs["Thin Wall"].default_value, True)
        self.assertEqual(decoder_leaves.inputs["Transmission Weight"].default_value, 0.0)

        # Test uncolored glass (dual-layer dielectric refraction + surface sticker: transmission = 1.0, sticker threshold = 0.55)
        mat_glass = bpy.data.materials.new("glass")
        tex_info_glass = {
            "texture_name": "glass",
            "source_texture": "minecraft:block/glass",
        }
        success_glass = rebuild_material(mat_glass, tex_info_glass)
        self.assertTrue(success_glass)

        decoder_glass = mat_glass.node_tree.nodes.get("LabPBR 1.3 Decoder")
        self.assertIsNotNone(decoder_glass)
        self.assertEqual(decoder_glass.inputs["Hardcoded Emission"].default_value, 0.0)
        self.assertEqual(decoder_glass.inputs["Thin Wall"].default_value, False)
        self.assertEqual(decoder_glass.inputs["Transmission Weight"].default_value, 1.0)
        self.assertAlmostEqual(decoder_glass.inputs["Sticker Threshold"].default_value, 0.55, places=4)

        # Test stained glass (translucent dielectric + surface sticker: transmission = 1.0, sticker threshold = 0.55)
        mat_stained = bpy.data.materials.new("white_stained_glass")
        tex_info_stained = {
            "texture_name": "white_stained_glass",
            "source_texture": "minecraft:block/white_stained_glass",
        }
        success_stained = rebuild_material(mat_stained, tex_info_stained)
        self.assertTrue(success_stained)

        decoder_stained = mat_stained.node_tree.nodes.get("LabPBR 1.3 Decoder")
        self.assertIsNotNone(decoder_stained)
        self.assertEqual(decoder_stained.inputs["Hardcoded Emission"].default_value, 0.0)
        self.assertEqual(decoder_stained.inputs["Thin Wall"].default_value, False)
        self.assertEqual(decoder_stained.inputs["Transmission Weight"].default_value, 1.0)
        self.assertAlmostEqual(decoder_stained.inputs["Sticker Threshold"].default_value, 0.55, places=4)

        # Test water (translucent dielectric liquid + surface foam/ripple sticker: transmission = 1.0, sticker threshold = 0.95)
        mat_water = bpy.data.materials.new("water_still")
        tex_info_water = {
            "texture_name": "water_still",
            "source_texture": "minecraft:block/water_still",
        }
        success_water = rebuild_material(mat_water, tex_info_water)
        self.assertTrue(success_water)

        decoder_water = mat_water.node_tree.nodes.get("LabPBR 1.3 Decoder")
        self.assertIsNotNone(decoder_water)
        self.assertEqual(decoder_water.inputs["Hardcoded Emission"].default_value, 0.0)
        self.assertEqual(decoder_water.inputs["Thin Wall"].default_value, False)
        self.assertEqual(decoder_water.inputs["Transmission Weight"].default_value, 1.0)
        self.assertAlmostEqual(decoder_water.inputs["Sticker Threshold"].default_value, 0.95, places=4)

    def test_atlas_material_builder_wires_material_props(self):
        """Verify that build_atlas_chunk_materials wires Attr Material Props (Emission, Thin Wall, Transmission)."""
        from utils.materials.atlas.builder import add_packed_material_props_nodes
        mat = bpy.data.materials.new("test_atlas_chunk")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()
        decoder = nodes.new("ShaderNodeGroup")
        decoder.node_tree = ensure_labpbr_decoder()
        decoder.name = "LabPBR 1.3 Decoder"

        add_packed_material_props_nodes(nodes, links, decoder)

        attr_node = nodes.get("Attr Material Props")
        self.assertIsNotNone(attr_node)
        self.assertEqual(attr_node.attribute_name, "mtk_material_props")

        split_node = nodes.get("Split Material Props")
        self.assertIsNotNone(split_node)

        clamp_node = nodes.get("Clamp Thin Wall")
        self.assertIsNotNone(clamp_node)
        self.assertEqual(clamp_node.operation, "GREATER_THAN")
        self.assertEqual(clamp_node.inputs[1].default_value, 0.5)

        # Verify links to decoder
        emit_link = [l for l in links if l.to_node == decoder and l.to_socket.name == "Hardcoded Emission"]
        self.assertEqual(len(emit_link), 1)
        self.assertEqual(emit_link[0].from_node, split_node)
        self.assertEqual(emit_link[0].from_socket.name, "Red")

        thin_link = [l for l in links if l.to_node == decoder and l.to_socket.name == "Thin Wall"]
        self.assertEqual(len(thin_link), 1)
        self.assertEqual(thin_link[0].from_node, clamp_node)

        trans_link = [l for l in links if l.to_node == decoder and l.to_socket.name == "Transmission Weight"]
        self.assertEqual(len(trans_link), 1)
        self.assertEqual(trans_link[0].from_node, split_node)
        self.assertEqual(trans_link[0].from_socket.name, "Blue")

        thresh_link = [l for l in links if l.to_node == decoder and l.to_socket.name == "Sticker Threshold"]
        self.assertEqual(len(thresh_link), 1)
        safe_thresh_node = nodes.get("Safe Sticker Threshold")
        self.assertIsNotNone(safe_thresh_node)
        self.assertEqual(thresh_link[0].from_node, safe_thresh_node)
        self.assertEqual(safe_thresh_node.operation, "MAXIMUM")
        self.assertAlmostEqual(safe_thresh_node.inputs[1].default_value, 0.55, places=4)

    def test_livesync_bmesh_layers_include_material_props(self):
        """Verify that LiveSync geometry builder allocates and sets the material_props layer."""
        import bmesh
        from utils.live_sync.geometry_builder import _get_or_create_bmesh_layers
        from utils.live_sync.constants import MTK_MATERIAL_PROPS
        bm = bmesh.new()
        layers = _get_or_create_bmesh_layers(bm)
        self.assertIn("material_props", layers)
        self.assertIsNotNone(bm.faces.layers.float_color.get(MTK_MATERIAL_PROPS))
        bm.free()


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

