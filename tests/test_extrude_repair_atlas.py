"""
Unit tests for MoziToolKit Auto Extrude Repair under Atlas and Non-Square Textures.
Tests Unified Atlas, Baked Atlas Chunks, animated texture strips, and boundary safety clamping.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import bpy
    import bmesh
    from mathutils import Vector
    from utils.extrude_repair import repair_extruded_side_faces
    from utils.mesh.uv import get_face_uv_bounds
    from utils.node_groups.atlas_uv_decoder import build_atlas_uv_decoder_node_group
    from utils.node_groups.animated import ensure_animated_uv_mapping
    HAS_BPY = True
except ImportError:
    HAS_BPY = False


@unittest.skipUnless(HAS_BPY, "bpy module is required for Extrude Repair Atlas unit tests")
class TestExtrudeRepairAtlas(unittest.TestCase):

    def setUp(self):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)

    def _create_test_image(self, name: str, width: int, height: int) -> bpy.types.Image:
        if name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[name])
        img = bpy.data.images.new(name=name, width=width, height=height)
        return img

    def test_extrude_repair_unified_atlas_1728x52352(self):
        """Unified Atlas material with 1728x52352 decoder repairs extruded UVs within [0, 1] local tile space."""
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
        cube = bpy.context.active_object

        # Unwrap to [0, 1] local UV
        bm = bmesh.new()
        bm.from_mesh(cube.data)
        uv_layer = bm.loops.layers.uv.verify()
        for face in bm.faces:
            face.loops[0][uv_layer].uv = Vector((0.0, 0.0))
            face.loops[1][uv_layer].uv = Vector((1.0, 0.0))
            face.loops[2][uv_layer].uv = Vector((1.0, 1.0))
            face.loops[3][uv_layer].uv = Vector((0.0, 1.0))
        bm.to_mesh(cube.data)
        bm.free()

        # Create Atlas Unified Material with decoder node
        mat = bpy.data.materials.new(name="mtk:unified_atlas")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        decoder_group = build_atlas_uv_decoder_node_group()
        decoder_node = nodes.new("ShaderNodeGroup")
        decoder_node.node_tree = decoder_group
        decoder_node.name = "MC Atlas UV Decoder"
        decoder_node.inputs["Tile Size"].default_value = 16.0
        decoder_node.inputs["Atlas Width"].default_value = 1728.0
        decoder_node.inputs["Atlas Height"].default_value = 52352.0
        cube.data.materials.append(mat)

        # Extrude top face in edit mode
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(cube.data)
        uv_layer = bm.loops.layers.uv.verify()
        faces_to_extrude = [f for f in bm.faces if f.normal.z > 0.5]
        for f in bm.faces:
            f.select = False

        ret = bmesh.ops.extrude_discrete_faces(bm, faces=faces_to_extrude)
        extruded_top = ret["faces"][0]
        extruded_top.select = True
        for v in extruded_top.verts:
            v.co.z += 0.2

        count = repair_extruded_side_faces(
            bm,
            obj=cube,
            context=bpy.context,
            repair_uv=True,
            add_crease=True,
            uv_mode="SMART",
        )
        self.assertEqual(count, 4)

        # Verify side face UVs stay safely inside [0.0, 1.0] tile bounds
        for f in bm.faces:
            if not f.select and len(f.verts) == 4 and abs(f.normal.z) < 0.1:
                bounds = get_face_uv_bounds(f, uv_layer)
                self.assertGreaterEqual(bounds.min_u, -1e-4)
                self.assertLessEqual(bounds.max_u, 1.0 + 1e-4)
                self.assertGreaterEqual(bounds.min_v, -1e-4)
                self.assertLessEqual(bounds.max_v, 1.0 + 1e-4)

        bmesh.update_edit_mesh(cube.data)
        bpy.ops.object.mode_set(mode="OBJECT")

    def test_extrude_repair_baked_atlas_chunk_boundary_clamping(self):
        """Atlas Chunk material with baked UVs clamps extruded UVs inside tile bounds to prevent bleeding."""
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
        cube = bpy.context.active_object

        # Target block tile in 2048x2048 atlas: [0.25, 0.25 + 16/2048] x [0.5, 0.5 + 16/2048]
        tile_u0 = 0.25
        tile_u1 = 0.25 + 16.0 / 2048.0
        tile_v0 = 0.5
        tile_v1 = 0.5 + 16.0 / 2048.0

        bm = bmesh.new()
        bm.from_mesh(cube.data)
        uv_layer = bm.loops.layers.uv.verify()
        for face in bm.faces:
            face.loops[0][uv_layer].uv = Vector((tile_u0, tile_v0))
            face.loops[1][uv_layer].uv = Vector((tile_u1, tile_v0))
            face.loops[2][uv_layer].uv = Vector((tile_u1, tile_v1))
            face.loops[3][uv_layer].uv = Vector((tile_u0, tile_v1))
        bm.to_mesh(cube.data)
        bm.free()

        # Create Atlas Chunk Material
        img = self._create_test_image("test_atlas_chunk_2048", 2048, 2048)
        mat = bpy.data.materials.new(name="mtk:chunk_atlas")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.name = "Tex Atlas (Albedo)"
        tex_node.image = img
        cube.data.materials.append(mat)

        # Extrude top face
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(cube.data)
        uv_layer = bm.loops.layers.uv.verify()
        faces_to_extrude = [f for f in bm.faces if f.normal.z > 0.5]
        for f in bm.faces:
            f.select = False

        ret = bmesh.ops.extrude_discrete_faces(bm, faces=faces_to_extrude)
        extruded_top = ret["faces"][0]
        extruded_top.select = True
        for v in extruded_top.verts:
            v.co.z += 0.2

        count = repair_extruded_side_faces(
            bm,
            obj=cube,
            context=bpy.context,
            repair_uv=True,
            add_crease=True,
            uv_mode="SMART",
        )
        self.assertEqual(count, 4)

        # Check that all 4 side faces have UVs strictly within the block's tile bounds
        for f in bm.faces:
            if not f.select and len(f.verts) == 4 and abs(f.normal.z) < 0.1:
                bounds = get_face_uv_bounds(f, uv_layer)
                self.assertGreaterEqual(bounds.min_u, tile_u0 - 1e-6)
                self.assertLessEqual(bounds.max_u, tile_u1 + 1e-6)
                self.assertGreaterEqual(bounds.min_v, tile_v0 - 1e-6)
                self.assertLessEqual(bounds.max_v, tile_v1 + 1e-6)

        bmesh.update_edit_mesh(cube.data)
        bpy.ops.object.mode_set(mode="OBJECT")

    def test_extrude_repair_anisotropic_animated_strip(self):
        """Animated vertical strip (16x512) uses correct anisotropic step without bleeding across frames."""
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
        cube = bpy.context.active_object

        # Frame 0 UV in 16x512 texture: [0, 1] x [31/32, 1.0]
        frame_v0 = 31.0 / 32.0
        frame_v1 = 1.0

        bm = bmesh.new()
        bm.from_mesh(cube.data)
        uv_layer = bm.loops.layers.uv.verify()
        for face in bm.faces:
            face.loops[0][uv_layer].uv = Vector((0.0, frame_v0))
            face.loops[1][uv_layer].uv = Vector((1.0, frame_v0))
            face.loops[2][uv_layer].uv = Vector((1.0, frame_v1))
            face.loops[3][uv_layer].uv = Vector((0.0, frame_v1))
        bm.to_mesh(cube.data)
        bm.free()

        # Material with animated node group
        img = self._create_test_image("test_fire_16x512", 16, 512)
        mat = bpy.data.materials.new(name="mtk:minecraft:fire_0")
        mat.use_nodes = True
        mat["mtk:source_texture"] = "fire_0"
        nodes = mat.node_tree.nodes

        uv_group = ensure_animated_uv_mapping()
        uv_node = nodes.new("ShaderNodeGroup")
        uv_node.node_tree = uv_group
        uv_node.inputs["Frame Width"].default_value = 16.0
        uv_node.inputs["Frame Height"].default_value = 16.0
        uv_node.inputs["Atlas Mode"].default_value = 1.0

        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.image = img
        cube.data.materials.append(mat)

        # Extrude top face
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(cube.data)
        uv_layer = bm.loops.layers.uv.verify()
        faces_to_extrude = [f for f in bm.faces if f.normal.z > 0.5]
        for f in bm.faces:
            f.select = False

        ret = bmesh.ops.extrude_discrete_faces(bm, faces=faces_to_extrude)
        extruded_top = ret["faces"][0]
        extruded_top.select = True
        for v in extruded_top.verts:
            v.co.z += 0.2

        count = repair_extruded_side_faces(
            bm,
            obj=cube,
            context=bpy.context,
            repair_uv=True,
            add_crease=True,
            uv_mode="SMART",
        )
        self.assertEqual(count, 4)

        # Check that side face UVs stay strictly within Frame 0's vertical range [31/32, 1.0]
        for f in bm.faces:
            if not f.select and len(f.verts) == 4 and abs(f.normal.z) < 0.1:
                bounds = get_face_uv_bounds(f, uv_layer)
                self.assertGreaterEqual(bounds.min_u, -1e-4)
                self.assertLessEqual(bounds.max_u, 1.0 + 1e-4)
                self.assertGreaterEqual(bounds.min_v, frame_v0 - 1e-6)
                self.assertLessEqual(bounds.max_v, frame_v1 + 1e-6)

        bmesh.update_edit_mesh(cube.data)
        bpy.ops.object.mode_set(mode="OBJECT")

    def test_extrude_repair_adjacent_different_material_isolation(self):
        """Outward extrusion next to a face with different material safely fallbacks and avoids bleeding."""
        # Create a 2-cube strip mesh sharing an edge
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
        cube = bpy.context.active_object

        mat_a = bpy.data.materials.new(name="Mat_Stone")
        mat_b = bpy.data.materials.new(name="Mat_Dirt")
        cube.data.materials.append(mat_a)
        cube.data.materials.append(mat_b)

        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(cube.data)
        uv_layer = bm.loops.layers.uv.verify()

        # Set face 0 to mat_a, face 1 to mat_b
        bm.faces.ensure_lookup_table()
        bm.faces[0].material_index = 0
        bm.faces[1].material_index = 1

        top_face = bm.faces[0]
        for f in bm.faces:
            f.select = False

        ret = bmesh.ops.extrude_discrete_faces(bm, faces=[top_face])
        extruded_top = ret["faces"][0]
        extruded_top.select = True
        for v in extruded_top.verts:
            v.co.z += 0.2

        # Repair with OUTWARD mode
        count = repair_extruded_side_faces(
            bm,
            obj=cube,
            context=bpy.context,
            repair_uv=True,
            add_crease=False,
            uv_mode="OUTWARD",
        )
        self.assertEqual(count, 4)

        # Check extruded side faces inherit mat_a (index 0) and UVs are contained
        side_faces = [
            f for f in bm.faces
            if f != extruded_top and any(e in extruded_top.edges for e in f.edges)
        ]
        self.assertEqual(len(side_faces), 4)
        for f in side_faces:
            self.assertEqual(f.material_index, 0)

        bmesh.update_edit_mesh(cube.data)
        bpy.ops.object.mode_set(mode="OBJECT")
