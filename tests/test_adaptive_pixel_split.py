"""
Unit tests for MoziToolKit Adaptive Pixel Split.
Tests static textures, animation strips (preventing over-splitting),
Atlas Chunk materials with attribute preservation, Unified Atlas decoder detection,
and partial UV bounds.
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
    from utils.pixel_split import (
        SplitConfig,
        process_adaptive_pixel_split,
        get_face_effective_texture_info,
        calculate_face_target_grid,
    )
    from utils.node_groups.animated import ensure_animated_uv_mapping
    from utils.node_groups.atlas_uv_decoder import build_atlas_uv_decoder_node_group
    HAS_BPY = True
except ImportError:
    HAS_BPY = False


@unittest.skipUnless(HAS_BPY, "bpy module is required for Adaptive Pixel Split unit tests")
class TestAdaptivePixelSplit(unittest.TestCase):

    def setUp(self):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)

    def _create_test_image(self, name: str, width: int, height: int) -> bpy.types.Image:
        """Create a blank memory image datablock for testing."""
        if name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[name])
        img = bpy.data.images.new(name=name, width=width, height=height)
        return img

    def _unwrap_minecraft_cube_uvs(self, obj: bpy.types.Object):
        """Map each face of a cube to full [0, 1] x [0, 1] UV coordinates (Minecraft block model format)."""
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()
        for face in bm.faces:
            if len(face.loops) == 4:
                face.loops[0][uv_layer].uv = Vector((0.0, 0.0))
                face.loops[1][uv_layer].uv = Vector((1.0, 0.0))
                face.loops[2][uv_layer].uv = Vector((1.0, 1.0))
                face.loops[3][uv_layer].uv = Vector((0.0, 1.0))
        bm.to_mesh(obj.data)
        bm.free()

    def test_static_texture_split_16x16(self):
        """Standard 16x16 static texture subdivides cube faces into 16x16 (256 faces per cube face)."""
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
        cube = bpy.context.active_object
        self._unwrap_minecraft_cube_uvs(cube)

        img = self._create_test_image("test_stone_16", 16, 16)
        mat = bpy.data.materials.new(name="Mat_Stone")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.name = "Tex Static (Albedo)"
        tex_node.image = img
        bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
        mat.node_tree.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])

        cube.data.materials.append(mat)

        config = SplitConfig(auto_resolution=True, selection_scope="ALL", pixels_per_face=1)
        stats = process_adaptive_pixel_split(bpy.context, config, target_obj=cube)

        self.assertEqual(stats["initial_faces"], 6)
        # 6 faces * (16 * 16) = 1536 faces
        self.assertEqual(stats["final_faces"], 1536)

    def test_animated_standalone_texture_prevents_vertical_oversplit(self):
        """An animated texture strip (16x512, 32 frames of 16x16) must split into 16x16, NOT 16x512."""
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
        cube = bpy.context.active_object
        self._unwrap_minecraft_cube_uvs(cube)

        img = self._create_test_image("test_lava_animated_16x512", 16, 512)
        mat = bpy.data.materials.new(name="mtk:minecraft:lava_still")
        mat.use_nodes = True
        mat["mtk:source_texture"] = "lava_still"
        nodes = mat.node_tree.nodes

        uv_group = ensure_animated_uv_mapping()
        uv_node = nodes.new("ShaderNodeGroup")
        uv_node.node_tree = uv_group
        uv_node.name = "MC UV Mapping (Albedo)"
        uv_node.inputs["Frame Width"].default_value = 16.0
        uv_node.inputs["Frame Height"].default_value = 16.0
        uv_node.inputs["Image Width"].default_value = 16.0
        uv_node.inputs["Image Height"].default_value = 512.0
        uv_node.inputs["Atlas Mode"].default_value = 0.0

        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.name = "Tex Current (Albedo)"
        tex_node.image = img

        cube.data.materials.append(mat)

        # Inspect detected info
        bm = bmesh.new()
        bm.from_mesh(cube.data)
        bm.faces.ensure_lookup_table()
        face = bm.faces[0]
        info = get_face_effective_texture_info(face, cube, bpy.context)
        bm.free()

        self.assertEqual(info.effective_resolution, (16, 16))
        self.assertEqual(info.raw_image_resolution, (16, 512))
        self.assertTrue(info.is_animated)
        self.assertEqual(info.total_frames, 32)

        # Run split
        config = SplitConfig(auto_resolution=True, selection_scope="ALL", pixels_per_face=1)
        stats = process_adaptive_pixel_split(bpy.context, config, target_obj=cube)

        self.assertEqual(stats["initial_faces"], 6)
        # 6 faces * (16 * 16) = 1536 faces (CRUCIAL: NOT 6 * 16 * 512 = 49152 faces)
        self.assertEqual(stats["final_faces"], 1536)

    def test_animated_vertical_strip_ratio_heuristic(self):
        """Even without node groups, an image with 32x256 (height % width == 0) is recognized as 32x32 frames."""
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
        cube = bpy.context.active_object

        img = self._create_test_image("raw_strip_32x256", 32, 256)
        mat = bpy.data.materials.new(name="Mat_RawStrip")
        mat.use_nodes = True
        tex_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex_node.image = img
        cube.data.materials.append(mat)

        bm = bmesh.new()
        bm.from_mesh(cube.data)
        bm.faces.ensure_lookup_table()
        face = bm.faces[0]
        info = get_face_effective_texture_info(face, cube, bpy.context)
        bm.free()

        self.assertEqual(info.effective_resolution, (32, 32))
        self.assertEqual(info.total_frames, 8)

    def test_atlas_chunk_baked_uv_and_attribute_preservation(self):
        """Atlas Chunk material with baked UVs divides tile properly and migrates face attributes to all sub-faces."""
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
        cube = bpy.context.active_object

        # 1024x1024 Atlas image with 16x16 tiles
        img = self._create_test_image("atlas_chunk_000_albedo", 1024, 1024)
        mat = bpy.data.materials.new(name="mtk:minecraft:atlas_chunk_000")
        mat.use_nodes = True
        mat["mtk:atlas_chunk_id"] = 0
        mat["mtk:atlas_chunk_kind"] = "static"
        tex_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex_node.name = "Atlas Chunk 000 Static (Albedo)"
        tex_node.image = img
        cube.data.materials.append(mat)

        # Set custom face attributes and baked atlas UVs
        bm = bmesh.new()
        bm.from_mesh(cube.data)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.verify()
        chunk_layer = bm.faces.layers.int.new("atlas_chunk_id")
        tex_layer = bm.faces.layers.int.new("atlas_texture_id")
        mat_layer = bm.faces.layers.int.new("material_id")

        # Tile (col=1, row=2) on 1024x1024 atlas (each tile is 16px -> 16/1024 = 0.015625)
        u_min = 1 * 16.0 / 1024.0
        u_max = 2 * 16.0 / 1024.0
        v_min = 1.0 - 3 * 16.0 / 1024.0
        v_max = 1.0 - 2 * 16.0 / 1024.0

        for face in bm.faces:
            face[chunk_layer] = 0
            face[tex_layer] = 77
            face[mat_layer] = 5
            face.loops[0][uv_layer].uv = Vector((u_min, v_min))
            face.loops[1][uv_layer].uv = Vector((u_max, v_min))
            face.loops[2][uv_layer].uv = Vector((u_max, v_max))
            face.loops[3][uv_layer].uv = Vector((u_min, v_max))

        bm.to_mesh(cube.data)
        bm.free()

        # Run split
        config = SplitConfig(auto_resolution=True, selection_scope="ALL", pixels_per_face=1)
        stats = process_adaptive_pixel_split(bpy.context, config, target_obj=cube)

        # 6 faces * (16 * 16) = 1536
        self.assertEqual(stats["final_faces"], 1536)

        # Verify attribute preservation across all sub-faces
        bm_check = bmesh.new()
        bm_check.from_mesh(cube.data)
        chunk_layer = bm_check.faces.layers.int.get("atlas_chunk_id")
        tex_layer = bm_check.faces.layers.int.get("atlas_texture_id")
        mat_layer = bm_check.faces.layers.int.get("material_id")

        self.assertIsNotNone(chunk_layer)
        self.assertIsNotNone(tex_layer)
        self.assertIsNotNone(mat_layer)

        for face in bm_check.faces:
            self.assertEqual(face[chunk_layer], 0)
            self.assertEqual(face[tex_layer], 77)
            self.assertEqual(face[mat_layer], 5)

        bm_check.free()

    def test_atlas_unified_material_decoder_split_safe(self):
        """Unified Atlas material with 1728x52352 decoder does NOT crash and splits at tile_size (16x16)."""
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
        cube = bpy.context.active_object
        self._unwrap_minecraft_cube_uvs(cube)

        mat = bpy.data.materials.new(name="MC_Atlas_Material")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes

        decoder_tree = build_atlas_uv_decoder_node_group()
        decoder_node = nodes.new("ShaderNodeGroup")
        decoder_node.node_tree = decoder_tree
        decoder_node.name = "MC Atlas UV Decoder"
        decoder_node.inputs["Atlas Width"].default_value = 1728.0
        decoder_node.inputs["Atlas Height"].default_value = 52352.0
        decoder_node.inputs["Tile Size"].default_value = 16.0

        cube.data.materials.append(mat)

        bm = bmesh.new()
        bm.from_mesh(cube.data)
        bm.faces.ensure_lookup_table()
        face = bm.faces[0]
        info = get_face_effective_texture_info(face, cube, bpy.context)
        bm.free()

        self.assertEqual(info.material_mode, "ATLAS_UNIFIED")
        self.assertEqual(info.effective_resolution, (16, 16))

        config = SplitConfig(auto_resolution=True, selection_scope="ALL", pixels_per_face=1)
        stats = process_adaptive_pixel_split(bpy.context, config, target_obj=cube)

        self.assertEqual(stats["final_faces"], 1536)

    def test_partial_uv_region_split(self):
        """A quad with partial UVs (e.g. 2x10 pixels of a 16x16 torch texture) subdivides into 2x10=20 faces."""
        bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0, 0, 0))
        plane = bpy.context.active_object

        img = self._create_test_image("test_torch_16", 16, 16)
        mat = bpy.data.materials.new(name="Mat_Torch")
        mat.use_nodes = True
        tex_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex_node.image = img
        plane.data.materials.append(mat)

        bm = bmesh.new()
        bm.from_mesh(plane.data)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.verify()
        face = bm.faces[0]

        # 2x10 pixel UV span: U in [0, 2/16], V in [0, 10/16]
        u0, u1 = 0.0, 2.0 / 16.0
        v0, v1 = 0.0, 10.0 / 16.0
        face.loops[0][uv_layer].uv = Vector((u0, v0))
        face.loops[1][uv_layer].uv = Vector((u1, v0))
        face.loops[2][uv_layer].uv = Vector((u1, v1))
        face.loops[3][uv_layer].uv = Vector((u0, v1))

        bm.to_mesh(plane.data)
        bm.free()

        config = SplitConfig(auto_resolution=True, selection_scope="ALL", pixels_per_face=1)
        stats = process_adaptive_pixel_split(bpy.context, config, target_obj=plane)

        self.assertEqual(stats["initial_faces"], 1)
        # 1 face * (2 * 10) = 20 sub-faces
        self.assertEqual(stats["final_faces"], 20)


if __name__ == "__main__":
    import sys
    unittest.main(argv=[sys.argv[0]])
