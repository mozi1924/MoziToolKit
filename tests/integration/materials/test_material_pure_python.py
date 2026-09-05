"""
Unit tests verifying pure Python execution (100% free of bpy).
Tests that AtlasGenerator, StandaloneGenerator, ChannelDescriptor,
StandaloneMaterialDescriptor, and Biome color operations run without Blender.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from PIL import Image

from utils.materials.models import (
    ChannelDescriptor,
    StandaloneMaterialDescriptor,
    AtlasChunkDescriptor,
)
from utils.materials.biome import (
    hex_to_rgb,
    srgb_to_linear,
    hex_to_linear_rgb,
    get_colormap_uv,
    sample_colormap_pixel,
    blend_biome_colors,
    BiomeResolver,
)
from utils.materials.standalone.aligner import (
    align_standalone_textures,
    is_channel_animated,
    _get_channel_image_size,
)
from utils.materials.standalone.generator import (
    StandaloneGenerator,
    STANDALONE_FORMAT_VERSION,
)
from utils.materials.atlas.generator import (
    AtlasGenerator,
    ATLAS_FORMAT_VERSION,
)
from utils.materials.pack.pack_stack import ResourcePackStack
from utils.materials.pack.resource_pack import ZipResourcePack


class TestMaterialPurePython(unittest.TestCase):
    """Test suite running in pure Python with zero Blender / bpy requirement."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="mtk_pure_python_test_")
        self.test_dir = Path(self.tmp_dir)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_descriptors_and_models(self):
        """Verify ChannelDescriptor and StandaloneMaterialDescriptor serialization/deserialization."""
        ch_albedo = ChannelDescriptor(
            path=self.test_dir / "stone.png",
            colorspace="sRGB",
            frame_count=1,
            frame_width=16,
            frame_height=16,
            frame_scale_v=1.0,
        )
        ch_normal = ChannelDescriptor(
            path=self.test_dir / "stone_n.png",
            colorspace="Non-Color",
            frame_count=1,
            frame_width=16,
            frame_height=16,
            frame_scale_v=1.0,
        )

        desc = StandaloneMaterialDescriptor(
            material_id="stone_mat",
            canonical_key="minecraft:block/stone",
            channels={"albedo": ch_albedo, "normal": ch_normal},
            tint_info={"tint_type": 0},
            pack_hash="abc123456789",
        )

        # Verify serialization
        data = desc.to_dict()
        self.assertEqual(data["material_id"], "stone_mat")
        self.assertEqual(data["canonical_key"], "minecraft:block/stone")
        self.assertEqual(data["channels"]["albedo"]["colorspace"], "sRGB")
        self.assertEqual(data["channels"]["normal"]["colorspace"], "Non-Color")

        # Verify deserialization
        restored = StandaloneMaterialDescriptor.from_dict(data)
        self.assertEqual(restored.material_id, "stone_mat")
        self.assertEqual(restored.canonical_key, "minecraft:block/stone")
        self.assertIsNotNone(restored.albedo)
        self.assertIsNotNone(restored.normal)
        self.assertIsNone(restored.specular)

        # Verify conversion to texture_info dict
        t_info = restored.to_texture_info()
        self.assertEqual(t_info["canonical_key"], "minecraft:block/stone")
        self.assertTrue(t_info["is_precompiled"])
        self.assertIn("albedo", t_info)

    def test_biome_pure_python(self):
        """Verify biome math and tint resolvers run in pure python."""
        r, g, b = hex_to_rgb("#55FF55")
        self.assertAlmostEqual(r, 0.3333333, places=2)
        self.assertAlmostEqual(g, 1.0, places=2)

        # Colormap coordinate calculation
        u, v = get_colormap_uv(0.8, 0.4)
        self.assertTrue(0.0 <= u <= 1.0)
        self.assertTrue(0.0 <= v <= 1.0)

        # Test colormap image sampling
        img = Image.new("RGB", (256, 256), (100, 200, 50))
        color = sample_colormap_pixel(img, 0.8, 0.4)
        self.assertEqual(len(color), 3)
        self.assertAlmostEqual(color[0], 100 / 255.0, places=2)

    def test_align_standalone_textures_pure_python(self):
        """Verify PIL-based companion channel vertical tiling and alignment."""
        # Create an animated albedo (16x32, 2 frames)
        albedo_path = self.test_dir / "lava.png"
        albedo_img = Image.new("RGBA", (16, 32), (255, 100, 0, 255))
        albedo_img.save(albedo_path)

        # Create a static normal map (16x16, 1 frame)
        normal_path = self.test_dir / "lava_n.png"
        normal_img = Image.new("RGBA", (16, 16), (128, 128, 255, 255))
        normal_img.save(normal_path)

        tex_info = {
            "texture_name": "lava",
            "albedo": str(albedo_path),
            "normal": str(normal_path),
            "albedo_mcmeta": {"animation": {"frametime": 2}},
        }

        out_dir = self.test_dir / "aligned"
        aligned = align_standalone_textures(tex_info, pack_hash="testhash", output_dir=out_dir)

        # Normal map should have been vertically tiled to match 32px height (2 frames)
        aligned_norm_path = Path(aligned["normal"])
        self.assertTrue(aligned_norm_path.exists())
        w, h = _get_channel_image_size(aligned_norm_path)
        self.assertEqual(w, 16)
        self.assertEqual(h, 32)


if __name__ == "__main__":
    unittest.main()
