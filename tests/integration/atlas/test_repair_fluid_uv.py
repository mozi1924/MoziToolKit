"""
Unit tests for Fluid UV repair (fixing inverted UV height mapping on sloped fluid side faces).
"""

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Bootstrap MoziToolKit package (also activates the isolated test sandbox)
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

try:
    import bpy
    import bmesh
    from mathutils import Vector
    try:
        from MoziToolKit.utils.mesh.fluid_uv import repair_face_fluid_uv, process_mesh_fluid_uv_repairs
        from MoziToolKit.pipeline.presets import get_preset_pipeline
        from MoziToolKit.pipeline.context import PipelineContext
    except ImportError:
        from utils.mesh.fluid_uv import repair_face_fluid_uv, process_mesh_fluid_uv_repairs
        from pipeline.presets import get_preset_pipeline
        from pipeline.context import PipelineContext
except ImportError:
    bpy = None
    bmesh = None


@unittest.skipIf(bpy is None, "Blender environment not available")
class TestRepairFluidUV(unittest.TestCase):
    def setUp(self):
        self.mesh = bpy.data.meshes.new("TestFluidUVMesh")
        self.bm = bmesh.new()
        self.uv_layer = self.bm.loops.layers.uv.new("UVMap")

    def tearDown(self):
        self.bm.free()
        if self.mesh.name in bpy.data.meshes:
            bpy.data.meshes.remove(self.mesh)

    def test_repair_inverted_sloped_face(self):
        """Test repairing a sloped quad face where top UV heights are inverted."""
        # 3D vertices: bottom is Y=0, top left is Y=0.2, top right is Y=0.8
        v0 = self.bm.verts.new(Vector((0.0, 0.0, 1.0)))  # Bottom right
        v1 = self.bm.verts.new(Vector((0.0, 0.0, 0.0)))  # Bottom left
        v2 = self.bm.verts.new(Vector((0.0, 0.2, 0.0)))  # Top left (low: 0.2)
        v3 = self.bm.verts.new(Vector((0.0, 0.8, 1.0)))  # Top right (high: 0.8)

        face = self.bm.faces.new([v0, v1, v2, v3])
        self.bm.faces.ensure_lookup_table()

        # Inverted UVs:
        # V0 (bottom right) -> UV (1.0, 0.0)
        # V1 (bottom left)  -> UV (0.0, 0.0)
        # V2 (top left, low 0.2)   -> UV (0.0, 0.8)  <-- INVERTED (too high)
        # V3 (top right, high 0.8) -> UV (1.0, 0.2)  <-- INVERTED (too low)
        loops = list(face.loops)
        loops[0][self.uv_layer].uv = Vector((1.0, 0.0))
        loops[1][self.uv_layer].uv = Vector((0.0, 0.0))
        loops[2][self.uv_layer].uv = Vector((0.0, 0.8))
        loops[3][self.uv_layer].uv = Vector((1.0, 0.2))

        # Check repair
        repaired = repair_face_fluid_uv(face, self.uv_layer)
        self.assertTrue(repaired)

        # After repair:
        # V2 (top left, low) should have UV V = 0.2
        # V3 (top right, high) should have UV V = 0.8
        self.assertAlmostEqual(loops[2][self.uv_layer].uv.y, 0.2, places=4)
        self.assertAlmostEqual(loops[3][self.uv_layer].uv.y, 0.8, places=4)
        # U coordinates should be unchanged
        self.assertAlmostEqual(loops[2][self.uv_layer].uv.x, 0.0, places=4)
        self.assertAlmostEqual(loops[3][self.uv_layer].uv.x, 1.0, places=4)

    def test_non_inverted_face_not_modified(self):
        """Test that correctly mapped sloped face is not modified when force=False."""
        v0 = self.bm.verts.new(Vector((0.0, 0.0, 1.0)))
        v1 = self.bm.verts.new(Vector((0.0, 0.0, 0.0)))
        v2 = self.bm.verts.new(Vector((0.0, 0.2, 0.0)))
        v3 = self.bm.verts.new(Vector((0.0, 0.8, 1.0)))

        face = self.bm.faces.new([v0, v1, v2, v3])
        self.bm.faces.ensure_lookup_table()

        loops = list(face.loops)
        loops[0][self.uv_layer].uv = Vector((1.0, 0.0))
        loops[1][self.uv_layer].uv = Vector((0.0, 0.0))
        loops[2][self.uv_layer].uv = Vector((0.0, 0.2))  # Correct
        loops[3][self.uv_layer].uv = Vector((1.0, 0.8))  # Correct

        repaired = repair_face_fluid_uv(face, self.uv_layer, force=False)
        self.assertFalse(repaired)

        self.assertAlmostEqual(loops[2][self.uv_layer].uv.y, 0.2, places=4)
        self.assertAlmostEqual(loops[3][self.uv_layer].uv.y, 0.8, places=4)

    def test_preset_pipeline_registered(self):
        """Verify preset pipeline 'repair_fluid_uv' is registered."""
        pipeline = get_preset_pipeline("repair_fluid_uv")
        self.assertIsNotNone(pipeline)
        self.assertEqual(len(pipeline.steps), 1)
        self.assertEqual(pipeline.steps[0].name, "Repair Fluid UV")

    def test_shared_fluid_uv_top_and_side_generation(self):
        """Verify get_fluid_top_uvs and get_fluid_side_uvs mathematical boundaries."""
        from utils.mesh.fluid_uv import (
            get_fluid_top_uvs,
            get_fluid_side_uvs,
            is_fluid_texture_name,
            is_flowing_fluid_texture,
        )
        import math

        self.assertTrue(is_fluid_texture_name("minecraft:block/water_flow"))
        self.assertTrue(is_fluid_texture_name("minecraft:block/lava_still"))
        self.assertFalse(is_fluid_texture_name("minecraft:block/stone"))

        self.assertTrue(is_flowing_fluid_texture("minecraft:block/water_flow"))
        self.assertTrue(is_flowing_fluid_texture("flowing_lava"))
        self.assertFalse(is_flowing_fluid_texture("minecraft:block/water_still"))

        # Stationary top: [0, 1]
        still_uvs = get_fluid_top_uvs(is_flowing=False)
        self.assertEqual(still_uvs, ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)))

        # Flowing top: [0.25, 0.75] window centered at (0.5, 0.5)
        flow_uvs = get_fluid_top_uvs(is_flowing=True, rotation=0.0)
        self.assertEqual(flow_uvs, ((0.25, 0.25), (0.25, 0.75), (0.75, 0.75), (0.75, 0.25)))

        # Flowing top with 45 degree rotation: all points remain strictly within [0.14, 0.86]
        flow_rot_uvs = get_fluid_top_uvs(is_flowing=True, rotation=math.pi / 4.0)
        for u, v in flow_rot_uvs:
            self.assertGreater(u, 0.14)
            self.assertLess(u, 0.86)
            self.assertGreater(v, 0.14)
            self.assertLess(v, 0.86)

        # Side face UVs
        side_uvs = get_fluid_side_uvs(0.8, 0.4)
        self.assertAlmostEqual(side_uvs[0][1], (1.0 - 0.8) * 0.5, places=4)
        self.assertAlmostEqual(side_uvs[3][1], (1.0 - 0.4) * 0.5, places=4)
        self.assertEqual(side_uvs[1], (0.0, 0.5))
        self.assertEqual(side_uvs[2], (0.5, 0.5))

    def test_normalize_static_fluid_face_uv_top_and_side(self):
        """Verify normalize_static_fluid_face_uv scales flowing top faces to 16x16 window."""
        from utils.mesh.fluid_uv import normalize_static_fluid_face_uv

        # Create mesh with top face (Z=1.0)
        mesh = bpy.data.meshes.new("TestStaticFluidMesh")
        verts = [(-0.5, -0.5, 1.0), (-0.5, 0.5, 1.0), (0.5, 0.5, 1.0), (0.5, -0.5, 1.0)]
        faces = [[0, 1, 2, 3]]
        mesh.from_pydata(verts, [], faces)
        mesh.update()


        uv_layer = mesh.uv_layers.new(name="UVMap")
        # Initialize full [0, 1] UVs
        uv_layer.data[0].uv = Vector((0.0, 0.0))
        uv_layer.data[1].uv = Vector((0.0, 1.0))
        uv_layer.data[2].uv = Vector((1.0, 1.0))
        uv_layer.data[3].uv = Vector((1.0, 0.0))

        # Normalize as flowing water
        res = normalize_static_fluid_face_uv(mesh.polygons[0], mesh, uv_layer, texture_name="water_flow")
        self.assertTrue(res)

        # Loop UVs should now be centered at (0.5, 0.5) with span [0.25, 0.75]
        self.assertAlmostEqual(uv_layer.data[0].uv.x, 0.25, places=4)
        self.assertAlmostEqual(uv_layer.data[0].uv.y, 0.25, places=4)
        self.assertAlmostEqual(uv_layer.data[2].uv.x, 0.75, places=4)
        self.assertAlmostEqual(uv_layer.data[2].uv.y, 0.75, places=4)

        bpy.data.meshes.remove(mesh)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

