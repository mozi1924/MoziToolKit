"""
Headless Automated Test Suite for MoziToolKit Pipeline Framework

Executed using Blender executable:
blender -b --python tests/run_tests.py
"""

import os
import sys
import unittest
from pathlib import Path

# Add project root directory to sys.path
PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy
import bmesh


class TestPipelineFramework(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Register addon if auto_load is present
        try:
            import auto_load
            auto_load.init()
            auto_load.register()
        except Exception as e:
            print(f"[Test Init] Extension registration note: {e}")

    def setUp(self):
        # Ensure we are in OBJECT mode before deleting objects
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        # Clear existing mesh objects
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)

        # Create a fresh test cube object
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
        self.cube = bpy.context.active_object
        self.cube.name = "TestCube"

    def test_pipeline_context_initialization(self):
        from pipeline.context import PipelineContext
        ctx = PipelineContext(context=bpy.context, params={"test_param": 123})
        self.assertEqual(ctx.active_object, self.cube)
        self.assertEqual(ctx.get_param("test_param"), 123)
        self.assertIn(self.cube, ctx.target_objects)

    def test_clear_custom_normals_step(self):
        from pipeline.presets import run_preset_pipeline
        # Add custom split normals
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.customdata_custom_splitnormals_add()
        bpy.ops.object.mode_set(mode="OBJECT")

        res, ctx = run_preset_pipeline("clear_custom_normals", bpy.context)
        self.assertTrue(res.is_success)
        self.assertFalse(self.cube.data.has_custom_normals)

    def test_select_hard_edges_step(self):
        from pipeline.presets import run_preset_pipeline
        bpy.ops.object.mode_set(mode="EDIT")
        res, ctx = run_preset_pipeline("select_hard_edges", bpy.context, {"sharp_angle": 30.0})
        self.assertTrue(res.is_success)

    def test_scale_uv_step(self):
        from pipeline.presets import run_preset_pipeline
        bpy.ops.object.mode_set(mode="EDIT")
        res, ctx = run_preset_pipeline("scale_uv", bpy.context, {"scale_factor": 0.5})
        self.assertTrue(res.is_success)
        self.assertGreater(ctx.get_data("scaled_uv_faces_count"), 0)

    def test_texture_interpolation_step(self):
        from pipeline.presets import run_preset_pipeline
        # Create a material with image texture
        mat = bpy.data.materials.new(name="TestMaterial")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        tex_node = nodes.new("ShaderNodeTexImage")
        img = bpy.data.images.new(name="TestImg", width=16, height=16)
        tex_node.image = img

        self.cube.data.materials.append(mat)
        bpy.ops.object.mode_set(mode="OBJECT")

        res, ctx = run_preset_pipeline("set_texture_interpolation_closest", bpy.context)
        self.assertTrue(res.is_success)
        self.assertEqual(tex_node.interpolation, "Closest")

    def test_adaptive_pixel_split_step(self):
        from pipeline.presets import run_preset_pipeline
        bpy.ops.object.mode_set(mode="OBJECT")
        res, ctx = run_preset_pipeline(
            "adaptive_pixel_split",
            bpy.context,
            {
                "auto_resolution": False,
                "resolution_width": 16,
                "resolution_height": 16,
                "pixels_per_face": 1,
                "selection_scope": "ALL",
            },
        )
        self.assertTrue(res.is_success)

    def test_auto_extrude_repair_step(self):
        from pipeline.presets import run_preset_pipeline
        bpy.ops.object.mode_set(mode="EDIT")
        res, ctx = run_preset_pipeline(
            "auto_extrude_repair",
            bpy.context,
            {"repair_uv": True, "add_mean_crease": True, "crease_value": 1.0, "uv_mode": "SMART"},
        )
        self.assertTrue(res.is_success)

    def test_operators_invoking_pipelines(self):
        # Test calling operators directly
        bpy.ops.object.mode_set(mode="EDIT")
        res = bpy.ops.mozi.select_hard_edges(sharp_angle=45.0)
        self.assertIn("FINISHED", res)

        res = bpy.ops.mozi.scale_uv(scale_factor=0.9)
        self.assertIn("FINISHED", res)


def run_all_tests():
    print("=" * 60)
    print("Running MoziToolKit Pipeline Automated Unit Tests...")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestPipelineFramework)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("\n✅ ALL TESTS PASSED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print("\n❌ SOME TESTS FAILED!")
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()
