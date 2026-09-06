"""
Unit tests for Generic Mod OBJ Loader and decoupled OBJ subsystem.
Tests:
1. Base OBJ Parser robustness (quads, triangles, usemtl with tint indices).
2. ModOBJLoader automatic coordinate scaling and centering.
3. ModelParser integration with direct .obj and Forge OBJ Loader.
4. StateBaker end-to-end mod OBJ baking with blockstate rotation.
5. Backward compatibility for builtin entity presets (chests, bells).
"""

import unittest
from pathlib import Path

from tests._bootstrap import bootstrap_environment
bootstrap_environment()

from utils.mc_baker.obj.base_parser import WavefrontOBJParser
from utils.mc_baker.obj.mod_obj_loader import ModOBJLoader
from utils.mc_baker.obj.builtin_presets import resolve_obj_model_for_state, build_bell_model
from utils.mc_baker.model_parser import ModelParser
from utils.mc_baker.state_baker import StateBaker


class TestModOBJLoader(unittest.TestCase):
    """Test suite for generic mod OBJ loading and baking."""

    def test_base_parser_quads_and_triangles(self):
        """Verify parser handles mixed quads, triangles, and usemtl [tint] syntax."""
        sample_obj = """
        v 0.0 0.0 0.0
        v 1.0 0.0 0.0
        v 1.0 1.0 0.0
        v 0.0 1.0 0.0
        vt 0.0 0.0
        vt 1.0 0.0
        vt 1.0 1.0
        vt 0.0 1.0
        usemtl [0]create:block/brass_casing
        f 1/1 2/2 3/3 4/4
        usemtl [1]create:block/cogwheel
        f 1/1 2/2 3/3
        """
        faces = WavefrontOBJParser.parse_text(sample_obj)
        self.assertEqual(len(faces), 2)

        # Quad face
        self.assertEqual(len(faces[0].verts), 4)
        self.assertEqual(faces[0].material, "create:block/brass_casing")
        self.assertEqual(faces[0].tint_index, 0)

        # Triangle face
        self.assertEqual(len(faces[1].verts), 3)
        self.assertEqual(faces[1].material, "create:block/cogwheel")
        self.assertEqual(faces[1].tint_index, 1)

    def test_mod_obj_loader_auto_scaling_16_to_1(self):
        """Verify OBJ with Blockbench 0..16 coordinates is auto-normalized to 0..1."""
        obj_16 = """
        v 0.0 0.0 0.0
        v 16.0 0.0 0.0
        v 16.0 16.0 0.0
        v 0.0 16.0 0.0
        vt 0.0 0.0
        vt 1.0 0.0
        vt 1.0 1.0
        vt 0.0 1.0
        usemtl create:block/gearbox
        f 1/1 2/2 3/3 4/4
        """
        baked = ModOBJLoader.bake_from_text(
            obj_16,
            block_state="create:gearbox",
            fallback_texture="create:block/gearbox",
        )
        self.assertIsNotNone(baked)
        self.assertEqual(len(baked.elements), 1)
        elem = baked.elements[0]
        # Element bounding box in [0..16] space
        self.assertAlmostEqual(elem.from_pos[0], 0.0)
        self.assertAlmostEqual(elem.to_pos[0], 16.0)

        face = list(elem.faces.values())[0]
        # Vertex coordinates must be in [0..1] block space
        xs = [v[0] for v in face.vertices]
        self.assertAlmostEqual(min(xs), 0.0)
        self.assertAlmostEqual(max(xs), 1.0)

    def test_mod_obj_loader_material_mapping(self):
        """Verify MTL material variables are replaced from textures_map."""
        sample_obj = """
        v 0.0 0.0 0.0
        v 1.0 0.0 0.0
        v 1.0 1.0 0.0
        v 0.0 1.0 0.0
        vt 0.0 0.0
        vt 1.0 0.0
        vt 1.0 1.0
        vt 0.0 1.0
        usemtl casing_mtl
        f 1/1 2/2 3/3 4/4
        """
        textures_map = {
            "casing_mtl": "create:block/andesite_casing"
        }
        baked = ModOBJLoader.bake_from_text(
            sample_obj,
            block_state="create:andesite_casing",
            textures_map=textures_map,
        )
        self.assertIsNotNone(baked)
        face = list(baked.elements[0].faces.values())[0]
        self.assertEqual(face.texture, "create:block/andesite_casing")

    def test_model_parser_with_direct_obj(self):
        """Verify ModelParser handles _is_obj flagged models from JarResourceLoader."""
        parser = ModelParser()
        raw_obj_content = """
        v 0.0 0.0 0.0
        v 1.0 0.0 0.0
        v 1.0 1.0 0.0
        v 0.0 1.0 0.0
        vt 0.0 0.0
        vt 1.0 0.0
        vt 1.0 1.0
        vt 0.0 1.0
        usemtl #all
        f 1/1 2/2 3/3 4/4
        """
        parser.register_model("create:block/cogwheel", {
            "_is_obj": True,
            "_raw_obj": raw_obj_content,
            "textures": {
                "all": "create:block/cogwheel"
            }
        })

        resolved = parser.resolve_model("create:block/cogwheel")
        self.assertEqual(resolved["model_id"], "create:block/cogwheel")
        self.assertTrue(len(resolved["elements"]) > 0)
        first_face = list(resolved["elements"][0]["faces"].values())[0]
        self.assertEqual(first_face["texture"], "create:block/cogwheel")
        self.assertIn("_baked_face", first_face)

    def test_model_parser_with_forge_obj_loader(self):
        """Verify ModelParser handles loader: forge:obj definitions."""
        parser = ModelParser()
        raw_obj_content = """
        v 0.0 0.0 0.0
        v 1.0 0.0 0.0
        v 1.0 1.0 0.0
        v 0.0 1.0 0.0
        vt 0.0 0.0
        vt 1.0 0.0
        vt 1.0 1.0
        vt 0.0 1.0
        usemtl brass
        f 1/1 2/2 3/3 4/4
        """
        parser.register_model("create:block/shaft.obj", {
            "_is_obj": True,
            "_raw_obj": raw_obj_content,
        })
        parser.register_model("create:block/shaft", {
            "loader": "forge:obj",
            "model": "create:block/shaft.obj",
            "textures": {
                "brass": "create:block/brass_block"
            }
        })

        resolved = parser.resolve_model("create:block/shaft")
        self.assertEqual(resolved["model_id"], "create:block/shaft")
        self.assertTrue(len(resolved["elements"]) > 0)
        face_data = list(resolved["elements"][0]["faces"].values())[0]
        self.assertEqual(face_data["texture"], "create:block/brass_block")

    def test_state_baker_mod_obj_with_variant_rotation(self):
        """Verify StateBaker bakes mod OBJ model and rotates vertices according to blockstate."""
        baker = StateBaker()
        raw_obj = """
        v 0.0 0.0 0.0
        v 1.0 0.0 0.0
        v 1.0 1.0 0.0
        v 0.0 1.0 0.0
        vt 0.0 0.0
        vt 1.0 0.0
        vt 1.0 1.0
        vt 0.0 1.0
        usemtl create:block/cogwheel
        f 1/1 2/2 3/3 4/4
        """
        baker.model_parser.register_model("create:block/cogwheel", {
            "_is_obj": True,
            "_raw_obj": raw_obj,
        })
        baker.state_resolver.register_blockstate("create:cogwheel", {
            "variants": {
                "axis=x": {"model": "create:block/cogwheel", "x": 90, "y": 90},
                "axis=y": {"model": "create:block/cogwheel"},
            }
        })

        baked = baker.bake_block_state("create:cogwheel[axis=x]")
        self.assertIsNotNone(baked)
        self.assertEqual(baked.block_state, "create:cogwheel[axis=x]")
        self.assertTrue(len(baked.elements) > 0)
        face = list(baked.elements[0].faces.values())[0]
        self.assertEqual(face.texture, "create:block/cogwheel")

    def test_builtin_presets_backward_compatibility(self):
        """Verify builtin entity block presets (chest, bell, etc.) work identically."""
        # 1. Chest
        chest = resolve_obj_model_for_state("minecraft:chest", {"facing": "north", "type": "single"})
        self.assertIsNotNone(chest)
        self.assertEqual(chest.block_state, "minecraft:chest[facing=north,type=single]")
        self.assertEqual(len(chest.elements), 18)

        # 2. Bell
        bell = build_bell_model("minecraft:bell[attachment=floor,facing=north]", {"attachment": "floor", "facing": "north"})
        self.assertIsNotNone(bell)
        self.assertTrue(len(bell.elements) > 0)


if __name__ == "__main__":
    unittest.main()
