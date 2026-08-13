"""
Integration tests for Replace Material step in Atlas Mode vs Standalone Mode in Blender.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import bpy
    HAS_BPY = True
except ImportError:
    HAS_BPY = False


class TestReplaceMaterialAtlasMode(unittest.TestCase):

    def setUp(self):
        if not HAS_BPY:
            self.skipTest("bpy module not available")

        self.jar_path = Path("/Users/jaxlocke/26.2-Fabric.jar")
        if not self.jar_path.exists():
            self.skipTest(f"JAR file not found: {self.jar_path}")

        # Clear existing scene objects and materials
        bpy.ops.wm.read_factory_settings(use_empty=True)

        # Create a test cube object with materials
        bpy.ops.mesh.primitive_cube_add()
        self.cube = bpy.context.active_object
        self.cube.name = "Test_Cube"

        # Create dummy original material 'stone'
        mat = bpy.data.materials.new(name="stone")
        self.cube.data.materials.append(mat)

    def test_standalone_mode(self):
        from pipeline.presets import run_preset_pipeline

        params = {
            "zip_path": str(self.jar_path),
            "material_mode": "STANDALONE",
            "pack_textures": True,
            "use_cache": True,
        }

        res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[self.cube])
        self.assertTrue(res.is_success, f"Standalone mode failed: {res.message}")
        self.assertIn("mtk:minecraft:stone", self.cube.material_slots[0].material.name)

    def test_atlas_mode(self):
        from pipeline.presets import run_preset_pipeline

        params = {
            "zip_path": str(self.jar_path),
            "material_mode": "ATLAS",
            "pack_textures": True,
            "use_cache": True,
        }

        res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[self.cube])
        self.assertTrue(res.is_success, f"Atlas mode failed: {res.message}")

        assigned_mat = self.cube.material_slots[0].material
        self.assertIn("mtk:atlas:", assigned_mat.name)

        # Check custom property on node tree
        self.assertIn("mtk:atlas_mapping", assigned_mat.node_tree)
        mapping_str = assigned_mat.node_tree["mtk:atlas_mapping"]
        self.assertIn("static_materials_count", mapping_str)

        # Check face attribute 'material_id' on mesh
        self.assertIn("material_id", self.cube.data.attributes)
        attr_values = [item.value for item in self.cube.data.attributes["material_id"].data]
        self.assertEqual(len(attr_values), len(self.cube.data.polygons))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
