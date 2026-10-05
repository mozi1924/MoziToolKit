"""Unit tests for LabPBR Hardcoded Emission, Thin Wall, Transmission, Sticker Threshold, and Minecraft catalog."""

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from unittest.mock import MagicMock

try:
    import bpy
    HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "meshes") and not isinstance(bpy.data, MagicMock)
except ImportError:
    bpy = None
    HAS_BPY = False

from utils.node_groups.labpbr import (
    LABPBR_GROUP_NAME,
    LABPBR_TEMPLATE_VERSION,
    LABPBR_INTERFACE,
    ensure_labpbr_decoder,
    assert_reference_shape,
    reference_shape_errors,
)
from bridge.material import (
    get_block_emission_strength,
    is_thin_wall_block,
    get_block_transmission_weight,
    get_block_sticker_threshold,
    is_transmissive_block,
    get_material_props,
    compute_flat_material_props,
    compute_mesh_material_props,
)


class TestLabPBRCatalogAndDecoders(unittest.TestCase):

    def setUp(self):
        if HAS_BPY:
            for ng in list(bpy.data.node_groups):
                if LABPBR_GROUP_NAME in ng.name:
                    bpy.data.node_groups.remove(ng)

    def test_vanilla_catalog_transmissions_and_stickers(self):
        """Verify transmission detection and sticker threshold thresholds for glass and fluids."""
        # Glass and Stained Glass (0.55 sticker threshold)
        self.assertTrue(is_transmissive_block("glass"))
        self.assertEqual(get_block_transmission_weight("glass"), 1.0)
        self.assertAlmostEqual(get_block_sticker_threshold("glass"), 0.55, places=4)

        self.assertTrue(is_transmissive_block("white_stained_glass"))
        self.assertEqual(get_block_transmission_weight("white_stained_glass"), 1.0)
        self.assertAlmostEqual(get_block_sticker_threshold("white_stained_glass"), 0.55, places=4)

        # Fluids and Ice (0.95 sticker threshold for foam/decals)
        self.assertTrue(is_transmissive_block("water"))
        self.assertTrue(is_transmissive_block("water_still"))
        self.assertTrue(is_transmissive_block("water_flow"))
        self.assertEqual(get_block_transmission_weight("water_still"), 1.0)
        self.assertAlmostEqual(get_block_sticker_threshold("water_still"), 0.95, places=4)

        self.assertTrue(is_transmissive_block("ice"))
        self.assertTrue(is_transmissive_block("blue_ice"))
        self.assertEqual(get_block_transmission_weight("ice"), 1.0)
        self.assertAlmostEqual(get_block_sticker_threshold("ice"), 0.95, places=4)

        self.assertTrue(is_transmissive_block("slime_block"))
        self.assertAlmostEqual(get_block_sticker_threshold("slime_block"), 0.95, places=4)

        self.assertTrue(is_transmissive_block("honey_block"))
        self.assertAlmostEqual(get_block_sticker_threshold("honey_block"), 0.95, places=4)

        # Non-transmissive solid blocks
        for name in ("stone", "dirt", "oak_planks", "iron_block", "oak_leaves"):
            self.assertFalse(is_transmissive_block(name), f"{name} should not be transmissive")
            self.assertEqual(get_block_transmission_weight(name), 0.0)

    def test_vanilla_catalog_emissions(self):
        """Verify static and state-dependent block emission calculations."""
        self.assertEqual(get_block_emission_strength("glowstone"), 15.0)
        self.assertEqual(get_block_emission_strength("sea_lantern"), 15.0)
        self.assertEqual(get_block_emission_strength("torch"), 14.0)
        self.assertEqual(get_block_emission_strength("wall_torch"), 14.0)
        self.assertEqual(get_block_emission_strength("crying_obsidian"), 10.0)
        self.assertEqual(get_block_emission_strength("magma_block"), 3.0)
        self.assertEqual(get_block_emission_strength("stone"), 0.0)

        # Campfire & Furnace
        self.assertEqual(get_block_emission_strength("campfire", {"lit": "true"}), 15.0)
        self.assertEqual(get_block_emission_strength("campfire", {"lit": "false"}), 0.0)
        self.assertEqual(get_block_emission_strength("furnace", {"lit": "true"}), 13.0)
        self.assertEqual(get_block_emission_strength("furnace", {"lit": "false"}), 0.0)

        # Candles
        self.assertEqual(get_block_emission_strength("candle", {"lit": "true", "candles": 3}), 9.0)
        self.assertEqual(get_block_emission_strength("candle", {"lit": "false", "candles": 3}), 0.0)

    def test_vanilla_catalog_thin_wall(self):
        """Verify thin wall whitelist for foliage and vegetation."""
        self.assertTrue(is_thin_wall_block("oak_leaves"))
        self.assertTrue(is_thin_wall_block("dandelion"))
        self.assertTrue(is_thin_wall_block("wheat"))
        self.assertTrue(is_thin_wall_block("vine"))
        self.assertFalse(is_thin_wall_block("stone"))
        self.assertFalse(is_thin_wall_block("oak_planks"))

    @unittest.skipUnless(HAS_BPY, "Requires Blender bpy environment")
    def test_labpbr_decoder_interface_and_sockets(self):
        """Verify LabPBR 1.3 Decoder public interface and sockets."""
        ng = ensure_labpbr_decoder()
        self.assertIsNotNone(ng)
        self.assertEqual(ng.get("mozi_template_version"), 18)
        self.assertEqual(reference_shape_errors(ng), ())
        assert_reference_shape(ng)

        sockets = {s.name: s for s in ng.interface.items_tree if s.item_type == "SOCKET"}

        # Verify sockets
        self.assertIn("Disable Subsurface", sockets)
        self.assertEqual(sockets["Disable Subsurface"].default_value, False)

        self.assertIn("Thin Wall", sockets)
        self.assertEqual(sockets["Thin Wall"].default_value, False)

        self.assertIn("Transmission Weight", sockets)
        self.assertEqual(sockets["Transmission Weight"].default_value, 0.0)

        self.assertIn("Sticker Threshold", sockets)
        self.assertAlmostEqual(sockets["Sticker Threshold"].default_value, 0.55, places=4)

        self.assertIn("Hardcoded Emission", sockets)
        self.assertEqual(sockets["Hardcoded Emission"].default_value, 0.0)

    @unittest.skipUnless(HAS_BPY, "Requires Blender bpy environment")
    def test_labpbr_decoder_wiring(self):
        """Verify that SSS, Transmission, Alpha, Clean Albedo, and Roughness mix nodes are correctly wired."""
        ng = ensure_labpbr_decoder()
        principled = ng.nodes.get("LabPBR Principled BSDF")
        self.assertIsNotNone(principled)

        # SSS wiring
        sss_mix = ng.nodes.get("Filter Subsurface Weight")
        self.assertIsNotNone(sss_mix)
        sss_links = [l for l in ng.links if l.to_node == principled and l.to_socket.name == "Subsurface Weight"]
        self.assertEqual(len(sss_links), 1)
        self.assertEqual(sss_links[0].from_node, sss_mix)

        # Transmission and Alpha
        final_trans = ng.nodes.get("Final Transmission")
        self.assertIsNotNone(final_trans)
        trans_links = [l for l in ng.links if l.to_node == principled and l.to_socket.name == "Transmission Weight"]
        self.assertEqual(len(trans_links), 1)
        self.assertEqual(trans_links[0].from_node, final_trans)

        final_alpha = ng.nodes.get("Final Alpha")
        self.assertIsNotNone(final_alpha)
        alpha_links = [l for l in ng.links if l.to_node == principled and l.to_socket.name == "Alpha"]
        self.assertEqual(len(alpha_links), 1)
        self.assertEqual(alpha_links[0].from_node, final_alpha)

    @unittest.skipUnless(HAS_BPY, "Requires Blender bpy environment")
    def test_standalone_builder_applies_catalog_properties(self):
        """Verify build_standalone_material sets Transmission, Sticker Threshold, Emission, and Thin Wall."""
        from utils.materials.builder.standalone_builder import build_standalone_material

        # 1. Glass
        mat_glass = build_standalone_material(
            texture_key="block/glass",
            albedo_path="/tmp/fake_glass.png",
            material_name="Test_Glass",
            block_name="glass",
        )
        self.assertIsNotNone(mat_glass)
        dec_glass = mat_glass.node_tree.nodes.get("LabPBR Decoder")
        self.assertIsNotNone(dec_glass)
        self.assertEqual(dec_glass.inputs["Transmission Weight"].default_value, 1.0)
        self.assertAlmostEqual(dec_glass.inputs["Sticker Threshold"].default_value, 0.55, places=4)
        self.assertEqual(dec_glass.inputs["Hardcoded Emission"].default_value, 0.0)
        self.assertEqual(dec_glass.inputs["Thin Wall"].default_value, False)

        # 2. Water
        mat_water = build_standalone_material(
            texture_key="block/water_still",
            albedo_path="/tmp/fake_water.png",
            material_name="Test_Water",
            block_name="water_still",
        )
        self.assertIsNotNone(mat_water)
        dec_water = mat_water.node_tree.nodes.get("LabPBR Decoder")
        self.assertIsNotNone(dec_water)
        self.assertEqual(dec_water.inputs["Transmission Weight"].default_value, 1.0)
        self.assertAlmostEqual(dec_water.inputs["Sticker Threshold"].default_value, 0.95, places=4)

        # 3. Torch
        mat_torch = build_standalone_material(
            texture_key="block/torch",
            albedo_path="/tmp/fake_torch.png",
            material_name="Test_Torch",
            block_name="torch",
        )
        self.assertIsNotNone(mat_torch)
        dec_torch = mat_torch.node_tree.nodes.get("LabPBR Decoder")
        self.assertIsNotNone(dec_torch)
        self.assertEqual(dec_torch.inputs["Hardcoded Emission"].default_value, 14.0)
        self.assertEqual(dec_torch.inputs["Transmission Weight"].default_value, 0.0)

        # 4. Leaves
        mat_leaves = build_standalone_material(
            texture_key="block/oak_leaves",
            albedo_path="/tmp/fake_leaves.png",
            material_name="Test_Leaves",
            block_name="oak_leaves",
        )
        self.assertIsNotNone(mat_leaves)
        dec_leaves = mat_leaves.node_tree.nodes.get("LabPBR Decoder")
        self.assertIsNotNone(dec_leaves)
        self.assertEqual(dec_leaves.inputs["Thin Wall"].default_value, True)

    @unittest.skipUnless(HAS_BPY, "Requires Blender bpy environment")
    def test_atlas_builder_wires_material_props(self):
        """Verify build_atlas_chunk_material wires Attr Material Props (Emission, Thin Wall, Transmission, Sticker)."""
        from utils.materials.builder.atlas_builder import build_atlas_chunk_material

        mat_atlas = build_atlas_chunk_material(
            chunk_id=0,
            albedo_path="/tmp/fake_atlas.png",
        )
        self.assertIsNotNone(mat_atlas)
        nodes = mat_atlas.node_tree.nodes
        links = mat_atlas.node_tree.links

        decoder = nodes.get("LabPBR Decoder")
        self.assertIsNotNone(decoder)

        attr_node = nodes.get("Attr Material Props")
        self.assertIsNotNone(attr_node)
        self.assertEqual(attr_node.attribute_name, "mtk_material_props")

        split_node = nodes.get("Split Material Props")
        self.assertIsNotNone(split_node)

        clamp_node = nodes.get("Clamp Thin Wall")
        self.assertIsNotNone(clamp_node)

        safe_thresh = nodes.get("Safe Sticker Threshold")
        self.assertIsNotNone(safe_thresh)

        # Verify links to decoder
        emit_link = [l for l in links if l.to_node == decoder and l.to_socket.name == "Hardcoded Emission"]
        self.assertEqual(len(emit_link), 1)
        self.assertEqual(emit_link[0].from_node, split_node)

        thin_link = [l for l in links if l.to_node == decoder and l.to_socket.name == "Thin Wall"]
        self.assertEqual(len(thin_link), 1)
        self.assertEqual(thin_link[0].from_node, clamp_node)

        trans_link = [l for l in links if l.to_node == decoder and l.to_socket.name == "Transmission Weight"]
        self.assertEqual(len(trans_link), 1)
        self.assertEqual(trans_link[0].from_node, split_node)

        thresh_link = [l for l in links if l.to_node == decoder and l.to_socket.name == "Sticker Threshold"]
        self.assertEqual(len(thresh_link), 1)
        self.assertEqual(thresh_link[0].from_node, safe_thresh)


if __name__ == "__main__":
    unittest.main()
