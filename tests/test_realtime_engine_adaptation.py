"""
Unit tests for real-time render engine adaptation (Cycles <-> EEVEE) across material shader trees.
"""

import unittest
from pathlib import Path

try:
    from unittest.mock import MagicMock
    import bpy
    HAS_BPY = (
        bpy is not None
        and not isinstance(bpy, MagicMock)
        and hasattr(bpy, "data")
        and hasattr(bpy.data, "meshes")
        and not isinstance(bpy.data, MagicMock)
        and hasattr(bpy, "app")
        and hasattr(bpy.app, "version")
    )
except ImportError:
    bpy = None
    HAS_BPY = False


from utils.materials.builder.atlas_builder import build_atlas_chunk_material
from utils.materials.builder.standalone_builder import build_standalone_material
from utils.materials.builder.adaptation import (
    update_materials_render_engine_adaptation,
    depsgraph_render_engine_adaptation_handler,
)


class TestRealtimeEngineAdaptation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAS_BPY:
            raise unittest.SkipTest("bpy is required for engine adaptation tests")

    def setUp(self):
        # Create a dummy image for testing
        self.img = bpy.data.images.new("TestAlbedo.png", width=16, height=16)

    def tearDown(self):
        if self.img:
            bpy.data.images.remove(self.img)

    def test_atlas_material_transmission_realtime_switching(self):
        """Verify that Atlas Chunk material transmission scale dynamically updates between Cycles and EEVEE."""
        mat = build_atlas_chunk_material(
            chunk_id=99,
            albedo_path="TestAlbedo.png",
            category="blocks",
            category_chunk_index=99,
            force_rebuild=True,
            render_engine="CYCLES",
        )
        self.assertIsNotNone(mat)
        scale_node = mat.node_tree.nodes.get("Material Transmission Scale")
        self.assertIsNotNone(scale_node)
        self.assertAlmostEqual(scale_node.inputs[1].default_value, 1.0)

        # 1. Simulate switching render engine to EEVEE
        scene = bpy.context.scene
        scene.render.engine = "BLENDER_EEVEE"

        # Trigger adaptation handler
        depsgraph_render_engine_adaptation_handler(scene)

        # Verify transmission scale updated to 0.0 in EEVEE
        self.assertAlmostEqual(scale_node.inputs[1].default_value, 0.0)

        # 2. Simulate switching back to CYCLES
        scene.render.engine = "CYCLES"
        depsgraph_render_engine_adaptation_handler(scene)

        # Verify transmission scale restored to 1.0 in CYCLES
        self.assertAlmostEqual(scale_node.inputs[1].default_value, 1.0)

        bpy.data.materials.remove(mat)

    def test_standalone_material_transmission_realtime_switching(self):
        """Verify that Standalone glass material transmission weight dynamically adapts to render engine."""
        mat = build_standalone_material(
            texture_key="block/glass",
            albedo_path="TestAlbedo.png",
            block_name="minecraft:glass",
            render_engine="CYCLES",
        )
        self.assertIsNotNone(mat)

        decoder_node = mat.node_tree.nodes.get("LabPBR Decoder")
        if not decoder_node:
            decoder_node = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)

        self.assertIsNotNone(decoder_node)
        self.assertAlmostEqual(decoder_node.inputs["Transmission Weight"].default_value, 1.0)

        # Switch to EEVEE
        scene = bpy.context.scene
        scene.render.engine = "BLENDER_EEVEE"
        depsgraph_render_engine_adaptation_handler(scene)

        # Transmission should now be 0.0 in EEVEE for clean alpha blending
        self.assertAlmostEqual(decoder_node.inputs["Transmission Weight"].default_value, 0.0)

        # Switch back to CYCLES
        scene.render.engine = "CYCLES"
        depsgraph_render_engine_adaptation_handler(scene)
        self.assertAlmostEqual(decoder_node.inputs["Transmission Weight"].default_value, 1.0)


        bpy.data.materials.remove(mat)


if __name__ == "__main__":
    unittest.main()
