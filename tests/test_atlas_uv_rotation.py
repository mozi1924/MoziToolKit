"""Unit tests for Atlas UV rotation detection, straightening, and shader tiling integration."""

import math
import sys
import unittest
from pathlib import Path

# Add project root and parent directory to sys.path
PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy
import bmesh
from mathutils import Vector

from utils.materials.constants import ATTR_UV_ROTATION
from utils.mesh.uv_rotation import (
    detect_face_uv_rotation,
    straighten_face_uv,
    process_mesh_uv_rotations,
    is_orthogonal_angle,
)
from utils.materials.atlas_builder import build_atlas_chunk_materials
from utils.node_groups.atlas_uv_tiling import ensure_atlas_uv_tiling


class TestAtlasUVRotation(unittest.TestCase):
    def setUp(self):
        # Create a test mesh and bmesh
        self.mesh = bpy.data.meshes.new("TestUVRotMesh")
        self.bm = bmesh.new()
        self.uv_layer = self.bm.loops.layers.uv.new("UVMap")

    def tearDown(self):
        self.bm.free()
        if self.mesh.name in bpy.data.meshes:
            bpy.data.meshes.remove(self.mesh)

    def test_orthogonal_angle_detection(self):
        self.assertTrue(is_orthogonal_angle(0.0))
        self.assertTrue(is_orthogonal_angle(math.pi / 2.0))
        self.assertTrue(is_orthogonal_angle(math.pi))
        self.assertTrue(is_orthogonal_angle(-math.pi / 2.0))
        self.assertFalse(is_orthogonal_angle(math.pi / 4.0))  # 45 deg
        self.assertFalse(is_orthogonal_angle(3.0 * math.pi / 4.0))  # 135 deg
        self.assertFalse(is_orthogonal_angle(-math.pi / 4.0))  # -45 deg

    def test_jmc2obj_liquid_cases(self):
        """Test all 8 liquid flow cases from jmc2obj Liquid.java model exporter."""
        cases = {
            "flow_s": ([(0, 0), (1, 0), (1, 1), (0, 1)], 0.0, False),
            "flow_sw": ([(0.5, -0.2071), (1.2071, 0.5), (0.5, 1.2071), (-0.2071, 0.5)], math.pi / 4.0, True),
            "flow_w": ([(1, 0), (1, 1), (0, 1), (0, 0)], 0.0, False),  # 90 deg orthogonal within bounds
            "flow_nw": ([(1.2071, 0.5), (0.5, 1.2071), (-0.2071, 0.5), (0.5, -0.2071)], 3.0 * math.pi / 4.0, True),
            "flow_n": ([(1, 1), (0, 1), (0, 0), (1, 0)], 0.0, False),  # 180 deg orthogonal within bounds
            "flow_ne": ([(0.5, 1.2071), (-0.2071, 0.5), (0.5, -0.2071), (1.2071, 0.5)], -3.0 * math.pi / 4.0, True),
            "flow_e": ([(0, 1), (0, 0), (1, 0), (1, 1)], 0.0, False),  # -90 deg orthogonal within bounds
            "flow_se": ([(-0.2071, 0.5), (0.5, -0.2071), (1.2071, 0.5), (0.5, 1.2071)], -math.pi / 4.0, True),
        }

        for name, (uv_coords, expected_angle, should_straighten) in cases.items():
            bm = bmesh.new()
            uv_lay = bm.loops.layers.uv.new("UVMap")
            verts = [
                bm.verts.new((-0.5, -0.5, 0.0)),
                bm.verts.new((0.5, -0.5, 0.0)),
                bm.verts.new((0.5, 0.5, 0.0)),
                bm.verts.new((-0.5, 0.5, 0.0)),
            ]
            face = bm.faces.new(verts)
            for i, loop in enumerate(face.loops):
                loop[uv_lay].uv = Vector(uv_coords[i])

            mesh_obj = bpy.data.meshes.new(f"Mesh_{name}")
            bm.to_mesh(mesh_obj)
            bm.free()

            poly = mesh_obj.polygons[0]
            uv_layer_data = mesh_obj.uv_layers[0]

            detected_angle = detect_face_uv_rotation(poly, uv_layer_data)
            if should_straighten:
                self.assertAlmostEqual(detected_angle, expected_angle, places=3, msg=f"Failed angle for {name}")
                angle, straightened = straighten_face_uv(poly, uv_layer_data)
                self.assertTrue(straightened, msg=f"Should straighten {name}")
                self.assertAlmostEqual(angle, expected_angle, places=3)

                # Check all UVs are now within [0, 1]
                for li in poly.loop_indices:
                    uv = uv_layer_data.data[li].uv
                    self.assertGreaterEqual(uv.x, -0.01, msg=f"U below 0 for {name}")
                    self.assertLessEqual(uv.x, 1.01, msg=f"U above 1 for {name}")
                    self.assertGreaterEqual(uv.y, -0.01, msg=f"V below 0 for {name}")
                    self.assertLessEqual(uv.y, 1.01, msg=f"V above 1 for {name}")
            else:
                self.assertAlmostEqual(detected_angle, 0.0, places=3, msg=f"Should be 0.0 for {name}")
                angle, straightened = straighten_face_uv(poly, uv_layer_data)
                self.assertFalse(straightened, msg=f"Should not straighten {name}")

            bpy.data.meshes.remove(mesh_obj)

    def test_shader_atlas_builder_uv_rotation_wiring(self):
        """Verify build_atlas_chunk_materials wires ATTR_UV_ROTATION into MC_Atlas_UV_Tiling."""
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            atlas_dir = Path(tmp_dir)
            for name in ["chunk_000_albedo.png", "chunk_001_albedo.png"]:
                img = bpy.data.images.new(name, width=64, height=64)
                img.filepath_raw = str(atlas_dir / name)
                img.file_format = "PNG"
                img.save()
                bpy.data.images.remove(img)

            mapping = {
                "atlas_version": 1,
                "tile_size": 16,
                "chunks": [
                    {
                        "chunk_id": 0,
                        "kind": "static",
                        "width": 64,
                        "height": 64,
                        "tile_size": 16,
                        "files": {"albedo": "chunk_000_albedo.png"}
                    },
                    {
                        "chunk_id": 1,
                        "kind": "animation",
                        "width": 64,
                        "height": 64,
                        "tile_size": 16,
                        "files": {"albedo": "chunk_001_albedo.png"}
                    }
                ]
            }
            with open(atlas_dir / "atlas_mapping.json", "w", encoding="utf-8") as fp:
                json.dump(mapping, fp)

            materials = build_atlas_chunk_materials(atlas_dir, pack_textures=False)

            # 1. Static Material
            mat_static = materials[0]
            nodes_static = {n.name: n for n in mat_static.node_tree.nodes}
            self.assertIn("Attr UV Rotation", nodes_static)
            self.assertIn("Combine UV Rotation", nodes_static)
            self.assertIn("MC Atlas UV Tiling", nodes_static)

            attr_rot_static = nodes_static["Attr UV Rotation"]
            comb_rot_static = nodes_static["Combine UV Rotation"]
            tiling_static = nodes_static["MC Atlas UV Tiling"]

            self.assertEqual(attr_rot_static.attribute_name, ATTR_UV_ROTATION)
            self.assertEqual(comb_rot_static.inputs["Z"].links[0].from_node, attr_rot_static)
            self.assertEqual(tiling_static.inputs["Rotation"].links[0].from_node, comb_rot_static)

            # 2. Animated Material
            mat_anim = materials[1]
            nodes_anim = {n.name: n for n in mat_anim.node_tree.nodes}
            self.assertIn("Attr UV Rotation", nodes_anim)
            self.assertIn("Combine UV Rotation", nodes_anim)
            self.assertIn("MC Atlas UV Tiling Current (Albedo)", nodes_anim)
            self.assertIn("MC Atlas UV Tiling Next (Albedo)", nodes_anim)

            attr_rot_anim = nodes_anim["Attr UV Rotation"]
            comb_rot_anim = nodes_anim["Combine UV Rotation"]
            tiling_curr = nodes_anim["MC Atlas UV Tiling Current (Albedo)"]
            tiling_next = nodes_anim["MC Atlas UV Tiling Next (Albedo)"]

            self.assertEqual(attr_rot_anim.attribute_name, ATTR_UV_ROTATION)
            self.assertEqual(comb_rot_anim.inputs["Z"].links[0].from_node, attr_rot_anim)
            self.assertEqual(tiling_curr.inputs["Rotation"].links[0].from_node, comb_rot_anim)
            self.assertEqual(tiling_next.inputs["Rotation"].links[0].from_node, comb_rot_anim)

    def test_process_mesh_uv_rotations_batch(self):
        """Test process_mesh_uv_rotations on a mesh with mixed unrotated and rotated faces."""
        bm = bmesh.new()
        uv_lay = bm.loops.layers.uv.new("UVMap")

        # Face 0: Standard (unrotated)
        v0 = bm.verts.new((0, 0, 0))
        v1 = bm.verts.new((1, 0, 0))
        v2 = bm.verts.new((1, 1, 0))
        v3 = bm.verts.new((0, 1, 0))
        f0 = bm.faces.new([v0, v1, v2, v3])
        std_uvs = [(0, 0), (1, 0), (1, 1), (0, 1)]
        for i, loop in enumerate(f0.loops):
            loop[uv_lay].uv = Vector(std_uvs[i])

        # Face 1: Rotated 45 degrees (jmc2obj flow_sw)
        v4 = bm.verts.new((2, 0, 0))
        v5 = bm.verts.new((3, 0, 0))
        v6 = bm.verts.new((3, 1, 0))
        v7 = bm.verts.new((2, 1, 0))
        f1 = bm.faces.new([v4, v5, v6, v7])
        rot_uvs = [(0.5, -0.2071), (1.2071, 0.5), (0.5, 1.2071), (-0.2071, 0.5)]
        for i, loop in enumerate(f1.loops):
            loop[uv_lay].uv = Vector(rot_uvs[i])

        mesh_obj = bpy.data.meshes.new("BatchTestMesh")
        bm.to_mesh(mesh_obj)
        bm.free()

        rotations = process_mesh_uv_rotations(mesh_obj)
        self.assertEqual(len(rotations), 2)
        self.assertAlmostEqual(rotations[0], 0.0, places=3)
        self.assertAlmostEqual(rotations[1], math.pi / 4.0, places=3)

        # Verify face 1 UV was straightened
        uv_layer = mesh_obj.uv_layers.active
        for li in mesh_obj.polygons[1].loop_indices:
            uv = uv_layer.data[li].uv
            self.assertGreaterEqual(uv.x, -0.01)
            self.assertLessEqual(uv.x, 1.01)
            self.assertGreaterEqual(uv.y, -0.01)
            self.assertLessEqual(uv.y, 1.01)

        bpy.data.meshes.remove(mesh_obj)

    def test_right_triangle_and_triangulated_quad_not_rotated(self):
        """Verify right triangles with diagonal hypotenuses are NOT falsely detected as rotated."""
        bm = bmesh.new()
        uv_lay = bm.loops.layers.uv.new("UVMap")

        # Triangle 1: Hypotenuse as first edge (0,0) -> (1,1) -> (0,1)
        t1_v = [bm.verts.new((0, 0, 0)), bm.verts.new((1, 1, 0)), bm.verts.new((0, 1, 0))]
        f_t1 = bm.faces.new(t1_v)
        f_t1.loops[0][uv_lay].uv = Vector((0.0, 0.0))
        f_t1.loops[1][uv_lay].uv = Vector((1.0, 1.0))
        f_t1.loops[2][uv_lay].uv = Vector((0.0, 1.0))

        # Triangle 2: Standard right triangle (0,0) -> (1,0) -> (1,1)
        t2_v = [bm.verts.new((2, 0, 0)), bm.verts.new((3, 0, 0)), bm.verts.new((3, 1, 0))]
        f_t2 = bm.faces.new(t2_v)
        f_t2.loops[0][uv_lay].uv = Vector((0.0, 0.0))
        f_t2.loops[1][uv_lay].uv = Vector((1.0, 0.0))
        f_t2.loops[2][uv_lay].uv = Vector((1.0, 1.0))

        mesh_obj = bpy.data.meshes.new("TriangleTestMesh")
        bm.to_mesh(mesh_obj)
        bm.free()

        uv_data = mesh_obj.uv_layers.active
        # Both triangles have orthogonal edges, so rotation must be 0.0 and neither should be straightened
        rot1 = detect_face_uv_rotation(mesh_obj.polygons[0], uv_data)
        rot2 = detect_face_uv_rotation(mesh_obj.polygons[1], uv_data)
        self.assertAlmostEqual(rot1, 0.0, places=3)
        self.assertAlmostEqual(rot2, 0.0, places=3)

        angle1, straightened1 = straighten_face_uv(mesh_obj.polygons[0], uv_data)
        angle2, straightened2 = straighten_face_uv(mesh_obj.polygons[1], uv_data)
        self.assertFalse(straightened1)
        self.assertFalse(straightened2)

        bpy.data.meshes.remove(mesh_obj)


if __name__ == "__main__":
    unittest.main(argv=["dummy"])

