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


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
