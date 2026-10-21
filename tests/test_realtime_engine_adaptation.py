"""Render-engine adaptation is now a no-op for the standard PBR material graph."""

import unittest

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


from MoziToolKit.utils.materials.builder.atlas_builder import build_atlas_chunk_material
from MoziToolKit.utils.materials.builder.adaptation import (
    update_materials_render_engine_adaptation,
    depsgraph_render_engine_adaptation_handler,
)


class TestRealtimeEngineAdaptation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAS_BPY:
            raise unittest.SkipTest("bpy is required for engine adaptation tests")

    def setUp(self):
        self.img = bpy.data.images.new("TestAlbedo.png", width=16, height=16)

    def tearDown(self):
        if self.img:
            bpy.data.images.remove(self.img)

    def test_standard_pbr_material_has_no_engine_specific_nodes(self):
        mat = build_atlas_chunk_material(
            chunk_id=99,
            albedo_path="TestAlbedo.png",
            category="blocks",
            category_chunk_index=99,
            force_rebuild=True,
            render_engine="CYCLES",
        )
        self.assertIsNotNone(mat)
        self.assertIsNone(mat.node_tree.nodes.get("Material Transmission Scale"))
        self.assertIsNone(mat.node_tree.nodes.get("LabPBR Decoder"))

        scene = bpy.context.scene
        scene.render.engine = "BLENDER_EEVEE"
        depsgraph_render_engine_adaptation_handler(scene)
        self.assertEqual(update_materials_render_engine_adaptation(scene=scene), 0)

        scene.render.engine = "CYCLES"
        depsgraph_render_engine_adaptation_handler(scene)
        self.assertEqual(update_materials_render_engine_adaptation(scene=scene), 0)

        bpy.data.materials.remove(mat)


if __name__ == "__main__":
    unittest.main()
