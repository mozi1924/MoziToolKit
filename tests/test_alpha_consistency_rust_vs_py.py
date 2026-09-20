"""
Parity and differential test suite for Transparent Face Analysis:
Comparing Python reference implementation vs Rust libmtk_py backend.
"""

import math
import random
import sys
import unittest
from pathlib import Path

libmtk_release_path = Path(__file__).resolve().parent.parent.parent / "libmozitoolkit" / "target" / "release"
if libmtk_release_path.exists():
    sys.path.insert(0, str(libmtk_release_path))

import bridge.texture as tex_bridge
from bridge.texture import (
    _py_batch_analyze_transparent_faces_f32,
    _py_is_face_transparent_f32,
    _py_sample_alpha_f32,
)

try:
    import libmtk_py as rust_backend
    HAS_RUST_BACKEND = hasattr(rust_backend, "batch_analyze_transparent_faces_f32")
except ImportError:
    rust_backend = None
    HAS_RUST_BACKEND = False

try:
    import bpy
    import bmesh
    HAS_BPY = True
except ImportError:
    bpy = None
    bmesh = None
    HAS_BPY = False


class TestAlphaConsistencyRustVsPy(unittest.TestCase):
    def setUp(self):
        random.seed(42)

    def test_rust_backend_available(self):
        self.assertTrue(HAS_RUST_BACKEND, "libmtk_py alpha functions must be available")

    def test_sample_alpha_f32_consistency(self):
        width, height = 16, 16
        # Generate random RGBA f32 pixel buffer
        pixels = [random.uniform(0.0, 1.0) for _ in range(width * height * 4)]

        # Test UV coordinates
        sample_points = [
            (0.0, 0.0),
            (0.5, 0.5),
            (0.99, 0.99),
            (1.0, 1.0),
            (0.25, 0.75),
            (-0.2, -0.3),  # Wrapped UVs
            (1.5, 2.3),
        ]
        for _ in range(50):
            sample_points.append((random.uniform(-5.0, 5.0), random.uniform(-5.0, 5.0)))

        for u, v in sample_points:
            for invert_y in (False, True):
                py_alpha = _py_sample_alpha_f32(width, height, pixels, u, v, invert_y)
                rust_alpha = rust_backend.sample_uv_alpha_f32(u, v, width, height, pixels, invert_y)
                self.assertAlmostEqual(py_alpha, rust_alpha, places=5, msg=f"Alpha mismatch at ({u}, {v}), invert_y={invert_y}")

    def test_batch_analyze_transparent_faces_consistency(self):
        width, height = 8, 8
        # Create an 8x8 texture where half the pixels are transparent (alpha < 0.01)
        pixels = []
        for y in range(height):
            for x in range(width):
                r, g, b = 1.0, 1.0, 1.0
                a = 0.0 if (x + y) % 2 == 0 else 1.0
                pixels.extend([r, g, b, a])

        # Generate 100 face UV polygons
        faces_uvs = []
        for _ in range(100):
            u_base = random.uniform(0.0, 0.8)
            v_base = random.uniform(0.0, 0.8)
            du = random.uniform(0.05, 0.2)
            dv = random.uniform(0.05, 0.2)
            quad = [
                (u_base, v_base),
                (u_base + du, v_base),
                (u_base + du, v_base + dv),
                (u_base, v_base + dv),
            ]
            faces_uvs.append(quad)

        for mode in ("CENTER", "ALL_CORNERS", "AVERAGE"):
            for threshold in (0.01, 0.5, 0.99):
                for invert_y in (False, True):
                    py_results = _py_batch_analyze_transparent_faces_f32(
                        faces_uvs, width, height, pixels, mode=mode, threshold=threshold, invert_y=invert_y
                    )
                    rust_results = rust_backend.batch_analyze_transparent_faces_f32(
                        faces_uvs, width, height, pixels, mode=mode, threshold=threshold, invert_y=invert_y
                    )
                    self.assertEqual(
                        py_results,
                        rust_results,
                        msg=f"Mismatch for mode={mode}, threshold={threshold}, invert_y={invert_y}",
                    )

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
    unittest.main()
