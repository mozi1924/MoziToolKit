"""Unit tests for MC_Atlas_UV_Tiling node group."""

import sys
import unittest
import math
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy
import bmesh
from mathutils import Vector

# Bootstrap MoziToolKit package (also activates the isolated test sandbox)
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

from utils.node_groups.atlas_uv_tiling import ensure_atlas_uv_tiling, ATLAS_UV_TILING_VERSION
from utils.materials.constants import ATTR_UV_TILING_TRANSFORM
from utils.mesh import (
    normalize_face_uv_for_atlas_tiling,
    face_uv_requires_atlas_tiling,
    restore_atlas_tiling_uv,
)


class TestAtlasUVTiling(unittest.TestCase):
    def test_optimized_face_uv_is_normalized_and_reconstructable(self):
        """A merged jmc2obj face remains a single quad while retaining its repeats."""
        mesh = bpy.data.meshes.new("TiledUVFace")
        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.new("UVMap")
        verts = [
            bm.verts.new((0.0, 0.0, 0.0)),
            bm.verts.new((3.0, 0.0, 0.0)),
            bm.verts.new((3.0, 2.0, 0.0)),
            bm.verts.new((0.0, 2.0, 0.0)),
        ]
        face = bm.faces.new(verts)
        original = [(-2.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-2.0, 1.0)]
        for loop, uv in zip(face.loops, original):
            loop[uv_layer].uv = Vector(uv)
        bm.to_mesh(mesh)
        bm.free()

        try:
            poly = mesh.polygons[0]
            scale, location = normalize_face_uv_for_atlas_tiling(poly, mesh.uv_layers.active)
            self.assertEqual(scale, (3.0, 2.0, 1.0))
            self.assertEqual(location, (-1.0, -0.5, 0.0))

            # The Atlas tiling Mapping node evaluates this affine transform
            # around 0.5. It must reconstruct the source coordinate exactly
            # before FRACT keeps the sample inside the assigned Atlas cell.
            for loop_index, expected in zip(poly.loop_indices, original):
                uv = mesh.uv_layers.active.data[loop_index].uv
                restored = restore_atlas_tiling_uv(uv.x, uv.y, scale, location)
                self.assertAlmostEqual(restored[0], expected[0])
                self.assertAlmostEqual(restored[1], expected[1])
                self.assertGreaterEqual(uv.x, 0.0)
                self.assertLessEqual(uv.x, 1.0)
                self.assertGreaterEqual(uv.y, 0.0)
                self.assertLessEqual(uv.y, 1.0)
        finally:
            bpy.data.meshes.remove(mesh)

    def test_standalone_restore_bakes_atlas_tiling_rotation(self):
        """The standalone fallback must reproduce the Atlas node transform."""
        # This is jmc2obj's south-west liquid corner: the Atlas mesh stores
        # (0, 0), while the shader rotates it by 45° around UV center.
        u, v = restore_atlas_tiling_uv(0.0, 0.0, rotation=math.pi / 4.0)
        self.assertAlmostEqual(u, 0.5, places=6)
        self.assertAlmostEqual(v, 0.5 - math.sqrt(0.5), places=6)

        # A merged 3 x 2 face additionally restores its source offset.
        u, v = restore_atlas_tiling_uv(1.0, 1.0, (3.0, 2.0, 1.0), (-1.0, -0.5, 0.0))
        self.assertAlmostEqual(u, 1.0, places=6)
        self.assertAlmostEqual(v, 1.0, places=6)

    def test_partial_uv_island_does_not_enable_tiling(self):
        """Pixel-split and partial-model faces are already Atlas-safe."""
        mesh = bpy.data.meshes.new("PartialUVFace")
        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.new("UVMap")
        verts = [bm.verts.new((x, y, 0.0)) for x, y in ((0, 0), (1, 0), (1, 1), (0, 1))]
        face = bm.faces.new(verts)
        partial = ((0.25, 0.125), (0.3125, 0.125), (0.3125, 0.1875), (0.25, 0.1875))
        for loop, coord in zip(face.loops, partial):
            loop[uv_layer].uv = Vector(coord)
        bm.to_mesh(mesh)
        bm.free()
        try:
            poly = mesh.polygons[0]
            active_uv = mesh.uv_layers.active
            self.assertFalse(face_uv_requires_atlas_tiling(poly, active_uv))
            self.assertEqual(
                [(round(active_uv.data[i].uv.x, 6), round(active_uv.data[i].uv.y, 6)) for i in poly.loop_indices],
                list(partial),
            )
        finally:
            bpy.data.meshes.remove(mesh)

    def test_atlas_uv_tiling_group_creation(self):
        group = ensure_atlas_uv_tiling()
        self.assertIsNotNone(group)
        self.assertEqual(group.name, "MC_Atlas_UV_Tiling")
        self.assertEqual(group.get("mozi_template_version"), ATLAS_UV_TILING_VERSION)
        self.assertTrue(group.get("mozi_template_complete"))

        # Verify interface sockets
        input_names = [
            s.name for s in group.interface.items_tree
            if s.item_type == "SOCKET" and s.in_out == "INPUT"
        ]
        output_names = [
            s.name for s in group.interface.items_tree
            if s.item_type == "SOCKET" and s.in_out == "OUTPUT"
        ]

        expected_inputs = [
            "Vector",
            "Scale",
            "Location",
            "Rotation",
            "Mapped Vector",
            "Use External Vector",
            "Atlas Width",
            "Atlas Height",
            "Tile Width",
            "Tile Height",
        ]
        expected_outputs = ["Atlas UV", "Local UV"]

        for exp in expected_inputs:
            self.assertIn(exp, input_names)
        for exp in expected_outputs:
            self.assertIn(exp, output_names)

    def test_atlas_material_builder_static_and_animated_tiling_nodes(self):
        import json
        import tempfile
        from pathlib import Path
        from utils.materials.atlas.builder import build_atlas_chunk_materials

        with tempfile.TemporaryDirectory() as tmp_dir:
            atlas_dir = Path(tmp_dir)

            # Create dummy images
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
            self.assertEqual(len(materials), 2)

            # 1. Verify Static Material (Chunk 0)
            mat_static = materials[0]
            nodes_static = {n.name: n for n in mat_static.node_tree.nodes}
            self.assertIn("MC Atlas UV Tiling", nodes_static)
            self.assertIn("Attr UV Tiling Transform", nodes_static)
            tiling_static = nodes_static["MC Atlas UV Tiling"]
            tex_static = nodes_static["Atlas Chunk 000 Static (Albedo)"]
            self.assertEqual(tiling_static.inputs["Vector"].links[0].from_node.bl_idname, "ShaderNodeTexCoord")
            self.assertEqual(tiling_static.inputs["Scale"].links[0].from_node, nodes_static["Combine UV Tiling Scale"])
            self.assertEqual(tiling_static.inputs["Location"].links[0].from_node, nodes_static["Combine UV Tiling Location"])
            self.assertEqual(tex_static.inputs["Vector"].links[0].from_node, tiling_static)

            # 2. Verify Animated Material (Chunk 1)
            mat_anim = materials[1]
            nodes_anim = {n.name: n for n in mat_anim.node_tree.nodes}
            self.assertIn("MC Atlas UV Tiling (Albedo)", nodes_anim)
            self.assertIn("MC UV Mapping (Albedo)", nodes_anim)

            tiling_anim = nodes_anim["MC Atlas UV Tiling (Albedo)"]
            uv_mapper = nodes_anim["MC UV Mapping (Albedo)"]
            tex_curr = nodes_anim["Tex Current (Albedo)"]
            tex_next = nodes_anim["Tex Next (Albedo)"]

            self.assertEqual(tiling_anim.inputs["Vector"].links[0].from_node.bl_idname, "ShaderNodeTexCoord")
            self.assertEqual(uv_mapper.inputs["Vector"].links[0].from_node, tiling_anim)
            self.assertEqual(uv_mapper.inputs["Vector"].links[0].from_socket.name, "Atlas UV")
            self.assertEqual(tex_curr.inputs["Vector"].links[0].from_node, uv_mapper)
            self.assertEqual(tex_curr.inputs["Vector"].links[0].from_socket.name, "Current UV")
            self.assertEqual(tex_next.inputs["Vector"].links[0].from_node, uv_mapper)
            self.assertEqual(tex_next.inputs["Vector"].links[0].from_socket.name, "Next UV")






if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
