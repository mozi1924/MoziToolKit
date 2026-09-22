"""
Test suite for Texture/Alpha Bridge operations backed by libmtk_py.
Validates alpha sampling, transparency detection, and Blender operator integration.
"""

import math
import random
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
libmtk_release_path = PROJECT_DIR.parent / "libmozitoolkit" / "target" / "release"

for p in [str(libmtk_release_path), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import bridge.texture as tex_bridge

try:
    import bpy
    import bmesh
    HAS_BPY = True
except ImportError:
    bpy = None
    bmesh = None
    HAS_BPY = False


class TestTextureAlphaBridge(unittest.TestCase):
    def setUp(self):
        random.seed(42)

    def test_sample_uv_alpha(self):
        width, height = 4, 4
        # 4x4 image: left half opaque (a=1.0), right half transparent (a=0.0)
        pixels = []
        for y in range(height):
            for x in range(width):
                a = 1.0 if x < 2 else 0.0
                pixels.extend([1.0, 1.0, 1.0, a])

        # Sample left side (x=0, 1 -> u=0.1)
        a_left = tex_bridge.sample_uv_alpha(0.1, 0.5, width, height, pixels)
        self.assertAlmostEqual(a_left, 1.0, places=5)

        # Sample right side (x=2, 3 -> u=0.8)
        a_right = tex_bridge.sample_uv_alpha(0.8, 0.5, width, height, pixels)
        self.assertAlmostEqual(a_right, 0.0, places=5)

    def test_batch_analyze_transparent_faces(self):
        width, height = 4, 4
        pixels = []
        for y in range(height):
            for x in range(width):
                a = 1.0 if x < 2 else 0.0
                pixels.extend([1.0, 1.0, 1.0, a])

        # Face 0 on left (opaque), Face 1 on right (transparent)
        face0 = [(0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4)]
        face1 = [(0.6, 0.0), (0.9, 0.0), (0.9, 0.9), (0.6, 0.9)]

        results = tex_bridge.batch_analyze_transparent_faces([face0, face1], width, height, pixels)
        self.assertEqual(results, [False, True])

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_select_transparent_faces_operator_end_to_end(self):
        import operators
        import ui
        operators.register()
        ui.register()

        try:
            # Create a test mesh with 2 faces (grid)
            mesh = bpy.data.meshes.new("TestAlphaMesh")
            bm = bmesh.new()
            bmesh.ops.create_grid(bm, x_segments=2, y_segments=1, size=2.0)
            uv_layer = bm.loops.layers.uv.verify()

            # Face 0 UV: [0.0, 0.0] to [0.5, 1.0] (maps to transparent half)
            # Face 1 UV: [0.5, 0.0] to [1.0, 1.0] (maps to opaque half)
            bm.faces.ensure_lookup_table()
            f0 = bm.faces[0]
            f1 = bm.faces[1]

            # Assign UVs explicitly
            for loop in f0.loops:
                u = 0.25 if loop.vert.co.x > 0 else 0.0
                v = 1.0 if loop.vert.co.y > 0 else 0.0
                loop[uv_layer].uv = (u, v)

            for loop in f1.loops:
                u = 0.75 if loop.vert.co.x > 0 else 0.5
                v = 1.0 if loop.vert.co.y > 0 else 0.0
                loop[uv_layer].uv = (u, v)

            bm.to_mesh(mesh)
            bm.free()

            obj = bpy.data.objects.new("TestAlphaObj", mesh)
            bpy.context.collection.objects.link(obj)

            # Create an image with left side transparent (a=0), right side opaque (a=1)
            img = bpy.data.images.new("TestAlphaImg", width=4, height=4, alpha=True)
            pix = []
            for y in range(4):
                for x in range(4):
                    a = 0.0 if x < 2 else 1.0
                    pix.extend([1.0, 1.0, 1.0, a])
            img.pixels = pix

            # Create material with image
            mat = bpy.data.materials.new("TestAlphaMat")
            mat.use_nodes = True
            tex_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
            tex_node.name = "Albedo Texture"
            tex_node.image = img
            obj.data.materials.append(mat)

            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)

            # Enter Edit Mode
            bpy.ops.object.mode_set(mode="EDIT")

            # Execute operator
            res = bpy.ops.mozi.select_transparent_faces(
                alpha_threshold=0.01,
                sample_mode="CENTER",
                selection_mode="SET",
                selection_scope="ALL",
            )
            self.assertEqual(res, {"FINISHED"})

            # Check selection state in bmesh
            bm_check = bmesh.from_edit_mesh(mesh)
            bm_check.faces.ensure_lookup_table()
            self.assertTrue(bm_check.faces[0].select, "Face 0 (transparent) should be selected")
            self.assertFalse(bm_check.faces[1].select, "Face 1 (opaque) should NOT be selected")

            bpy.ops.object.mode_set(mode="OBJECT")

            # Cleanup
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(mesh)
            bpy.data.materials.remove(mat)
            bpy.data.images.remove(img)
        finally:
            try:
                ui.unregister()
            except Exception:
                pass
            try:
                operators.unregister()
            except Exception:
                pass


if __name__ == "__main__":
    if "--" in sys.argv:
        argv = [sys.argv[0]] + sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = [sys.argv[0]]
    unittest.main(argv=argv)
