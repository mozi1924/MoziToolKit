"""Unit and integration tests for Mineways atlas unpacking, tile decoding, and UV remapping."""

import unittest
import bpy
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Bootstrap MoziToolKit package (also activates the isolated test sandbox)
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

from utils.materials import (
    is_mineways_material,
    is_mineways_atlas_material,
    is_mineways_atlas_image,
    find_mineways_atlas_image,
    decode_mineways_face_uv,
    remap_mineways_atlas_uv_to_local,
    extract_face_texture_info,
    detect_material_mode,
)


class TestMinewaysAtlasUnpack(unittest.TestCase):
    def tearDown(self):
        for mat in list(bpy.data.materials):
            bpy.data.materials.remove(mat)
        for mesh in list(bpy.data.meshes):
            bpy.data.meshes.remove(mesh)
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)

    def test_mineways_atlas_image_detection(self):
        img_terrain = bpy.data.images.new("terrainRGB.png", width=1024, height=1024)
        self.assertTrue(is_mineways_atlas_image(img_terrain))

        img_custom = bpy.data.images.new("dd-RGB.png", width=1024, height=1024)
        self.assertTrue(is_mineways_atlas_image(img_custom))

        img_rgba = bpy.data.images.new("castle_build-RGBA.png", width=1024, height=1024)
        self.assertTrue(is_mineways_atlas_image(img_rgba))

        img_alpha = bpy.data.images.new("test_world_Alpha.png", width=1024, height=1024)
        self.assertTrue(is_mineways_atlas_image(img_alpha))

        img_normal = bpy.data.images.new("stone.png", width=16, height=16)
        self.assertFalse(is_mineways_atlas_image(img_normal))

    def test_mineways_atlas_material_detection(self):
        mat = bpy.data.materials.new(name="Grass_Block")
        mat.use_nodes = True
        tex_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        img = bpy.data.images.new("dd-RGB.png", width=1024, height=1024)
        tex_node.image = img

        self.assertTrue(is_mineways_atlas_image(img))
        self.assertTrue(is_mineways_atlas_material(mat))
        self.assertTrue(is_mineways_material(mat))
        self.assertEqual(detect_material_mode(mat), "MINEWAYS_ATLAS")

    def test_decode_mineways_face_uv_grass_side(self):
        # Grass block side is at (3, 0) in master table -> swatch_id = 3
        # In 1024x1024 (56 swatches per row), swatch 3 is at col 3, row 0
        # Pixel X: [3*18+1, 3*18+17] = [55, 71] -> U: [55/1024, 71/1024]
        # Pixel Y from top: [0*18+1, 0*18+17] = [1, 17] -> V: [1 - 17/1024, 1 - 1/1024]
        mesh = bpy.data.meshes.new("TestMesh")
        mesh.from_pydata(
            [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
            [],
            [(0, 1, 2, 3)],
        )
        uv_layer = mesh.uv_layers.new(name="UVMap")
        uv_layer.data[0].uv = (71.0 / 1024.0, (1024.0 - 17.0) / 1024.0)
        uv_layer.data[1].uv = (71.0 / 1024.0, (1024.0 - 1.0) / 1024.0)
        uv_layer.data[2].uv = (55.0 / 1024.0, (1024.0 - 1.0) / 1024.0)
        uv_layer.data[3].uv = (55.0 / 1024.0, (1024.0 - 17.0) / 1024.0)

        img = bpy.data.images.new("dd-RGB.png", width=1024, height=1024)
        poly = mesh.polygons[0]
        tex_name, alt_name, local_uvs = decode_mineways_face_uv(poly, uv_layer, image=img)

        self.assertEqual(tex_name, "grass_block_side")
        self.assertAlmostEqual(local_uvs[0][0], 1.0, places=4)
        self.assertAlmostEqual(local_uvs[0][1], 0.0, places=4)
        self.assertAlmostEqual(local_uvs[1][0], 1.0, places=4)
        self.assertAlmostEqual(local_uvs[1][1], 1.0, places=4)
        self.assertAlmostEqual(local_uvs[2][0], 0.0, places=4)
        self.assertAlmostEqual(local_uvs[2][1], 1.0, places=4)
        self.assertAlmostEqual(local_uvs[3][0], 0.0, places=4)
        self.assertAlmostEqual(local_uvs[3][1], 0.0, places=4)

    def test_decode_mineways_face_uv_chiseled_stone_bricks(self):
        # Chiseled stone bricks is at (5, 13) -> swatch_id = 5 + 13*16 = 213
        # In 1024x1024 (56 swatches per row): col = 213 % 56 = 45, row = 213 // 56 = 3
        # Pixel X: [45*18+1, 45*18+17] = [811, 827] -> U: [811/1024, 827/1024]
        # Pixel Y from top: [3*18+1, 3*18+17] = [55, 71] -> V: [1 - 71/1024, 1 - 55/1024]
        mesh = bpy.data.meshes.new("TestMesh")
        mesh.from_pydata(
            [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
            [],
            [(0, 1, 2, 3)],
        )
        uv_layer = mesh.uv_layers.new(name="UVMap")
        uv_layer.data[0].uv = (811.0 / 1024.0, (1024.0 - 71.0) / 1024.0)
        uv_layer.data[1].uv = (827.0 / 1024.0, (1024.0 - 71.0) / 1024.0)
        uv_layer.data[2].uv = (827.0 / 1024.0, (1024.0 - 55.0) / 1024.0)
        uv_layer.data[3].uv = (811.0 / 1024.0, (1024.0 - 55.0) / 1024.0)

        img = bpy.data.images.new("dd-RGB.png", width=1024, height=1024)
        poly = mesh.polygons[0]
        tex_name, alt_name, local_uvs = decode_mineways_face_uv(poly, uv_layer, image=img)

        self.assertEqual(tex_name, "chiseled_stone_bricks")
        self.assertAlmostEqual(local_uvs[0][0], 0.0, places=4)
        self.assertAlmostEqual(local_uvs[0][1], 0.0, places=4)
        self.assertAlmostEqual(local_uvs[1][0], 1.0, places=4)
        self.assertAlmostEqual(local_uvs[1][1], 0.0, places=4)
        self.assertAlmostEqual(local_uvs[2][0], 1.0, places=4)
        self.assertAlmostEqual(local_uvs[2][1], 1.0, places=4)
        self.assertAlmostEqual(local_uvs[3][0], 0.0, places=4)
        self.assertAlmostEqual(local_uvs[3][1], 1.0, places=4)

    def test_extract_face_texture_info_mineways_atlas(self):
        mat = bpy.data.materials.new(name="Grass_Block")
        mat.use_nodes = True
        tex_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        img = bpy.data.images.new("dd-RGB.png", width=1024, height=1024)
        tex_node.image = img

        mesh = bpy.data.meshes.new("TestMesh")
        mesh.from_pydata(
            [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
            [],
            [(0, 1, 2, 3)],
        )
        mesh.materials.append(mat)
        uv_layer = mesh.uv_layers.new(name="UVMap")
        uv_layer.data[0].uv = (71.0 / 1024.0, (1024.0 - 17.0) / 1024.0)
        uv_layer.data[1].uv = (71.0 / 1024.0, (1024.0 - 1.0) / 1024.0)
        uv_layer.data[2].uv = (55.0 / 1024.0, (1024.0 - 1.0) / 1024.0)
        uv_layer.data[3].uv = (55.0 / 1024.0, (1024.0 - 17.0) / 1024.0)

        ns, candidates, old_loc = extract_face_texture_info(mesh, 0, mat)
        self.assertEqual(ns, "minecraft")
        self.assertIn("block/grass_block_side", candidates)
        self.assertIsNotNone(old_loc)
        self.assertEqual(old_loc["kind"], "mineways_atlas")


if __name__ == "__main__":
    unittest.main(argv=["first-arg-is-ignored"])
