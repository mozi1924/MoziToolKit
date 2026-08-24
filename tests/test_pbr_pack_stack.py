"""
Tests for multi-channel PBR Resource Pack Stacking, Decoupled Baking, and Instant Material Replacement.
"""

import os
import json
import tempfile
import unittest
import sys
import zipfile
from pathlib import Path
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.materials import (
    ResourcePackStack,
    ZipResourcePack,
    AtlasGenerator,
    ATLAS_FORMAT_VERSION,
    get_configured_pack_stack,
)
from utils.system import has_pillow

try:
    from PIL import Image
except ImportError:
    Image = None


class TestPBRPackStack(unittest.TestCase):
    """Test suite for Minecraft-style resource pack stacking and PBR channel composition."""

    def test_multi_pack_pbr_channel_composition_mock(self):
        """
        Verify that:
        - Pack A (top) has only specular 'diamond_ore_s.png' (e.g. glowing addon)
        - Pack B (middle) has normal 'diamond_ore_n.png' and fallback specular 'diamond_ore_s.png'
        - Pack C (bottom) has base albedo 'diamond_ore.png'
        The composite texture receives:
        - albedo from Pack C
        - normal from Pack B
        - specular from Pack A (overriding Pack B)
        """
        if not Image:
            self.skipTest("Pillow not available")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            pack_a_dir = tmp / "pack_a_glowing"
            pack_b_dir = tmp / "pack_b_pbr"
            pack_c_dir = tmp / "pack_c_base"

            # Create Pack A (specular only, green specular)
            tex_a = pack_a_dir / "assets" / "minecraft" / "textures" / "block"
            tex_a.mkdir(parents=True)
            Image.new("RGBA", (16, 16), (0, 255, 0, 255)).save(tex_a / "diamond_ore_s.png")

            # Create Pack B (normal + blue specular)
            tex_b = pack_b_dir / "assets" / "minecraft" / "textures" / "block"
            tex_b.mkdir(parents=True)
            Image.new("RGBA", (16, 16), (128, 128, 255, 255)).save(tex_b / "diamond_ore_n.png")
            Image.new("RGBA", (16, 16), (0, 0, 255, 255)).save(tex_b / "diamond_ore_s.png")

            # Create Pack C (base albedo + model)
            tex_c = pack_c_dir / "assets" / "minecraft" / "textures" / "block"
            tex_c.mkdir(parents=True)
            Image.new("RGBA", (16, 16), (0, 200, 255, 255)).save(tex_c / "diamond_ore.png")
            models_c = pack_c_dir / "assets" / "minecraft" / "models" / "block"
            models_c.mkdir(parents=True)
            (models_c / "diamond_ore.json").write_text(
                '{"parent": "block/cube_all", "textures": {"all": "minecraft:block/diamond_ore"}}',
                encoding="utf-8"
            )

            # Build stack in priority order: A (top), B (middle), C (bottom)
            stack = ResourcePackStack([pack_a_dir, pack_b_dir, pack_c_dir])
            self.assertEqual(len(stack.packs), 3)

            # Query texture info
            info = stack.get_texture_info("diamond_ore", "minecraft")
            self.assertIsNotNone(info)
            self.assertIsNotNone(info["albedo"])
            self.assertIsNotNone(info["normal"])
            self.assertIsNotNone(info["specular"])

            # Verify paths
            self.assertTrue(str(info["albedo"]).endswith("diamond_ore.png"))
            self.assertTrue(str(info["normal"]).endswith("diamond_ore_n.png"))
            self.assertTrue(str(info["specular"]).endswith("diamond_ore_s.png"))

            # Check actual image pixel colors
            albedo_img = Image.open(info["albedo"])
            normal_img = Image.open(info["normal"])
            specular_img = Image.open(info["specular"])

            self.assertEqual(albedo_img.getpixel((0, 0)), (0, 200, 255, 255))
            self.assertEqual(normal_img.getpixel((0, 0)), (128, 128, 255, 255))
            # Specular MUST be Green from Pack A, NOT Blue from Pack B
            self.assertEqual(specular_img.getpixel((0, 0)), (0, 255, 0, 255))

            # Now test Atlas Generator with this stack (build to stack's persistent baked dir)
            atlas_out = stack.get_baked_atlas_dir()
            generator = AtlasGenerator(fallback_stack=stack)
            outputs = generator.build(atlas_out)

            self.assertTrue(outputs["mapping"].exists())
            with open(outputs["mapping"], "r", encoding="utf-8") as fp:
                mapping = json.load(fp)

            self.assertEqual(mapping["format_version"], ATLAS_FORMAT_VERSION)
            self.assertIn("diamond_ore", mapping["textures"])
            chunk0 = mapping["chunks"][0]
            self.assertIn("albedo", chunk0["files"])
            self.assertIn("normal", chunk0["files"])
            self.assertIn("specular", chunk0["files"])

            # Check that specular chunk image has the green specular pixel from Pack A
            spec_chunk_img = Image.open(atlas_out / chunk0["files"]["specular"])
            loc = mapping["textures"]["diamond_ore"]
            px_x, px_y = loc.get("pixel_x", 0), loc.get("pixel_y", 0)
            self.assertEqual(spec_chunk_img.getpixel((px_x, px_y)), (0, 255, 0, 255))

            # Test stack baking status
            self.assertTrue(stack.is_stack_baked())

    def test_normal_only_overlay_keeps_lower_albedo_in_atlas(self):
        """An _N-only top layer must overlay, never replace, the base texture."""
        if not Image:
            self.skipTest("Pillow not available")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            overlay_dir = tmp / "glow_overlay"
            pbr_dir = tmp / "pbr_base"
            vanilla_dir = tmp / "vanilla"

            def texture_dir(pack):
                result = pack / "assets" / "minecraft" / "textures" / "block"
                result.mkdir(parents=True)
                return result

            # Use an upper-case suffix to cover real-world PBR packs that name
            # their channel companions _N/_S instead of lower-case.
            Image.new("RGBA", (16, 16), (12, 34, 56, 255)).save(texture_dir(overlay_dir) / "diamond_ore_N.png")
            Image.new("RGBA", (16, 16), (80, 90, 100, 255)).save(texture_dir(pbr_dir) / "diamond_ore.png")
            Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(texture_dir(vanilla_dir) / "diamond_ore.png")

            stack = ResourcePackStack([overlay_dir, pbr_dir, vanilla_dir])
            info = stack.get_texture_info("diamond_ore")
            self.assertIsNotNone(info)
            self.assertTrue(str(info["albedo"]).endswith("pbr_base/assets/minecraft/textures/block/diamond_ore.png"))
            self.assertTrue(str(info["normal"]).endswith("diamond_ore_N.png"))

            atlas_dir = tmp / "atlas"
            AtlasGenerator(fallback_stack=stack).build(atlas_dir)
            mapping = json.loads((atlas_dir / "atlas_mapping.json").read_text(encoding="utf-8"))
            location = mapping["textures"]["diamond_ore"]
            chunk = next(item for item in mapping["chunks"] if item["chunk_id"] == location["chunk_id"])
            x = location.get("pixel_x", location["tile_column"] * location["tile_size"])
            y = location.get("pixel_y", location["tile_row"] * location["tile_size"])

            self.assertEqual(Image.open(atlas_dir / chunk["files"]["albedo"]).getpixel((x, y)), (80, 90, 100, 255))
            self.assertEqual(Image.open(atlas_dir / chunk["files"]["normal"]).getpixel((x, y)), (12, 34, 56, 255))

    def test_non_pbr_chunk_does_not_emit_placeholder_pbr_sheets(self):
        """PBR in one chunk must not allocate default PBR images for another."""
        if not Image:
            self.skipTest("Pillow not available")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            textures = root / "assets" / "minecraft" / "textures" / "block"
            textures.mkdir(parents=True)
            Image.new("RGBA", (16, 16), (100, 100, 100, 255)).save(textures / "pbr_block.png")
            Image.new("RGBA", (16, 16), (128, 128, 255, 255)).save(textures / "pbr_block_n.png")
            Image.new("RGBA", (16, 16), (200, 100, 50, 255)).save(textures / "plain_block.png")

            # One 16px tile per chunk makes the allocation contract explicit.
            atlas_dir = root / "atlas"
            AtlasGenerator(root, max_chunk_size=16).build(atlas_dir)
            mapping = json.loads((atlas_dir / "atlas_mapping.json").read_text(encoding="utf-8"))
            pbr_chunk_id = mapping["textures"]["pbr_block"]["chunk_id"]
            plain_chunk_id = mapping["textures"]["plain_block"]["chunk_id"]
            pbr_chunk = next(chunk for chunk in mapping["chunks"] if chunk["chunk_id"] == pbr_chunk_id)
            plain_chunk = next(chunk for chunk in mapping["chunks"] if chunk["chunk_id"] == plain_chunk_id)

            self.assertIn("normal", pbr_chunk["files"])
            self.assertNotIn("specular", pbr_chunk["files"])
            self.assertEqual(set(plain_chunk["files"]), {"albedo"})

    def test_real_user_packs_if_present(self):
        """Test with actual user packs on system if they exist."""
        real_packs = [
            Path("/Users/jaxlocke/Downloads/SPBR-GlowingOre.zip"),
            Path("/Users/jaxlocke/Downloads/SPBR-21.zip"),
            Path("/Users/jaxlocke/26.2-Fabric.jar"),
        ]
        available_packs = [p for p in real_packs if p.exists()]
        if len(available_packs) < 2:
            self.skipTest("Real user packs not all found on system")

        stack = ResourcePackStack(available_packs)
        self.assertGreaterEqual(len(stack.packs), 2)

        # Check coal_ore or deepslate_diamond_ore
        info = stack.get_texture_info("coal_ore", "minecraft")
        if info:
            self.assertIsNotNone(info["albedo"])
            if Path("/Users/jaxlocke/Downloads/SPBR-GlowingOre.zip").exists():
                self.assertIsNotNone(info["specular"])
                spec_path = str(info["specular"])
                self.assertTrue(Path(spec_path).exists())
                self.assertTrue(spec_path.endswith("coal_ore_s.png"))
                self.assertEqual(
                    Path(spec_path).resolve(),
                    (stack.packs[0].extract_dir / "assets" / "minecraft" / "textures" / "block" / "coal_ore_s.png").resolve()
                )


class TestDecoupledMaterialReplacement(unittest.TestCase):
    """Test suite for decoupled pre-baking and instant material replacement."""

    def setUp(self):
        # Create a test mesh in Blender
        bpy.ops.mesh.primitive_cube_add()
        self.cube = bpy.context.active_object
        self.cube.name = "TestPBRCube"

    def tearDown(self):
        if self.cube and self.cube.name in bpy.data.objects:
            bpy.data.objects.remove(self.cube, do_unlink=True)

    def test_fast_path_material_replacement_uses_cached_atlas(self):
        """Verify that Replace Material uses pre-baked atlas and assigns chunk materials."""
        if not Image:
            self.skipTest("Pillow not available")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            pack_dir = tmp / "pack"
            tex_dir = pack_dir / "assets" / "minecraft" / "textures" / "block"
            tex_dir.mkdir(parents=True)
            Image.new("RGBA", (16, 16), (100, 150, 200, 255)).save(tex_dir / "stone.png")

            stack = ResourcePackStack([pack_dir])

            # 1. Pre-bake
            atlas_dir = stack.get_baked_atlas_dir(yefira_only=False)
            gen = AtlasGenerator(fallback_stack=stack)
            gen.build(atlas_dir)

            self.assertTrue(stack.is_stack_baked())

            # 2. Assign initial stone material on cube
            mat = bpy.data.materials.new(name="minecraft:stone")
            self.cube.data.materials.clear()
            self.cube.data.materials.append(mat)

            # 3. Run StepReplaceMaterial with params
            try:
                from MoziToolKit.pipeline.context import PipelineContext
                from MoziToolKit.pipeline.steps.step_replace_material import StepReplaceMaterial
            except ImportError:
                from pipeline.context import PipelineContext
                from pipeline.steps.step_replace_material import StepReplaceMaterial

            ctx = PipelineContext(
                context=bpy.context,
                target_objects=[self.cube],
                params={
                    "pack_stack": stack,
                    "material_mode": "ATLAS",
                    "pack_textures": False,
                    "biome_preset": "PLAINS",
                }
            )

            step = StepReplaceMaterial()
            results = list(step.execute_iter(ctx))

            # Verify success
            last_res = results[-1]
            self.assertTrue(hasattr(last_res, "is_success") and last_res.is_success)

            # Check that cube material slot is now an Atlas Chunk Material
            self.assertGreater(len(self.cube.data.materials), 0)
            assigned_mat = self.cube.data.materials[0]
            self.assertIn("chunk", assigned_mat.name.lower())
            self.assertIn("LabPBR 1.3 Decoder", [n.name for n in assigned_mat.node_tree.nodes])


if __name__ == "__main__":
    unittest.main()
