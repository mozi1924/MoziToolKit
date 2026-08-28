"""
Comprehensive test suite verifying the Acceptance Matrix and Invariants from
docs/materials/material_pipeline.md (Minecraft Material Resolution, Matching & Replacement Pipeline).
"""

from __future__ import annotations

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

# Bootstrap MoziToolKit package so top-level pipeline/operators/ui imports resolve
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

from PIL import Image

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from utils.system import has_pillow
from utils.materials import (
    ResourcePackStack,
    ZipResourcePack,
    AtlasGenerator,
    StandaloneGenerator,
    STANDALONE_FORMAT_VERSION,
    ATLAS_FORMAT_VERSION,
    canonical_texture_key,
    detect_material_mode,
)
from pipeline.presets import run_preset_pipeline


class TestMaterialSystemSpecification(unittest.TestCase):
    """Verifies all required acceptance matrix scenarios and invariants from the design spec."""

    def setUp(self):
        if not has_pillow():
            self.skipTest("Pillow required for material system tests.")

        self.tmp_dir = tempfile.mkdtemp(prefix="mtk_spec_test_")
        self.pack_root = Path(self.tmp_dir)

    def tearDown(self):
        if hasattr(self, "tmp_dir") and Path(self.tmp_dir).exists():
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

        if HAS_BPY and bpy.data:
            for mat in list(bpy.data.materials):
                if mat.name.startswith("mtk:") or "spec_test" in mat.name:
                    bpy.data.materials.remove(mat, do_unlink=True)
            for obj in list(bpy.data.objects):
                if "SpecTest" in obj.name:
                    bpy.data.objects.remove(obj, do_unlink=True)

    def _create_mock_pack(self, pack_name: str, files: dict[str, Any]) -> Path:
        """Create a mock unpacked resource pack directory with pack.mcmeta and given files."""
        pack_dir = self.pack_root / pack_name
        pack_dir.mkdir(parents=True, exist_ok=True)

        mcmeta_path = pack_dir / "pack.mcmeta"
        mcmeta_path.write_text('{"pack": {"pack_format": 15, "description": "Mock Pack"}}', encoding="utf-8")

        for rel_path, content in files.items():
            file_path = pack_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, Image.Image):
                content.save(file_path)
            elif isinstance(content, (dict, list)):
                file_path.write_text(json.dumps(content), encoding="utf-8")
            elif isinstance(content, str):
                file_path.write_text(content, encoding="utf-8")
            elif isinstance(content, bytes):
                file_path.write_bytes(content)

        return pack_dir

    def test_acceptance_uppercase_pbr_override(self):
        """
        Acceptance Matrix #1:
        Top layer: ore_N.png
        Middle layer: ore.png
        Bottom layer: ore.png
        Must use middle layer Albedo and top layer Normal; top _N must not become an Albedo entry.
        """
        top_pack = self._create_mock_pack("top_pbr", {
            "assets/minecraft/textures/block/diamond_ore_N.png": Image.new("RGBA", (16, 16), (128, 128, 255, 255)),
        })
        mid_pack = self._create_mock_pack("mid_hd", {
            "assets/minecraft/textures/block/diamond_ore.png": Image.new("RGBA", (32, 32), (0, 200, 200, 255)),
        })
        base_pack = self._create_mock_pack("base_vanilla", {
            "assets/minecraft/textures/block/diamond_ore.png": Image.new("RGBA", (16, 16), (0, 100, 100, 255)),
        })

        stack = ResourcePackStack([top_pack, mid_pack, base_pack])
        comp = stack.get_texture_info("diamond_ore", "minecraft")

        self.assertIsNotNone(comp)
        self.assertEqual(comp["albedo"], mid_pack / "assets/minecraft/textures/block/diamond_ore.png")
        self.assertEqual(comp["normal"], top_pack / "assets/minecraft/textures/block/diamond_ore_N.png")
        self.assertIsNone(comp["specular"])

        # Ensure diamond_ore_n / diamond_ore_N is not an independent albedo entry
        all_comp = stack.get_all_composite_textures()
        self.assertIn(("minecraft", "block/diamond_ore"), all_comp)
        self.assertNotIn(("minecraft", "block/diamond_ore_n"), all_comp)
        self.assertNotIn(("minecraft", "block/diamond_ore_N"), all_comp)

    def test_acceptance_three_channel_cross_layer_composition(self):
        """
        Acceptance Matrix #2:
        Top layer: ore_s.png
        Middle layer: ore.png + ore_n.png
        Bottom layer: ore.png
        Must resolve: Albedo and Normal from mid layer, Specular from top layer.
        """
        top_pack = self._create_mock_pack("top_glow", {
            "assets/minecraft/textures/block/gold_ore_s.png": Image.new("RGBA", (16, 16), (255, 255, 0, 255)),
        })
        mid_pack = self._create_mock_pack("mid_pbr", {
            "assets/minecraft/textures/block/gold_ore.png": Image.new("RGBA", (16, 16), (200, 180, 0, 255)),
            "assets/minecraft/textures/block/gold_ore_n.png": Image.new("RGBA", (16, 16), (128, 128, 255, 255)),
        })
        base_pack = self._create_mock_pack("base_vanilla", {
            "assets/minecraft/textures/block/gold_ore.png": Image.new("RGBA", (16, 16), (100, 90, 0, 255)),
        })

        stack = ResourcePackStack([top_pack, mid_pack, base_pack])
        comp = stack.get_texture_info("gold_ore", "minecraft")

        self.assertIsNotNone(comp)
        self.assertEqual(comp["albedo"], mid_pack / "assets/minecraft/textures/block/gold_ore.png")
        self.assertEqual(comp["normal"], mid_pack / "assets/minecraft/textures/block/gold_ore_n.png")
        self.assertEqual(comp["specular"], top_pack / "assets/minecraft/textures/block/gold_ore_s.png")

    def test_acceptance_missing_albedo_isolation(self):
        """
        Acceptance Matrix #3:
        Any layer has only companion maps (e.g. unknown_ore_n.png / unknown_ore_s.png), but NO layer has albedo.
        Must NOT generate tile in Atlas, standalone material, transparent image or black placeholder.
        """
        top_pack = self._create_mock_pack("orphan_pbr", {
            "assets/minecraft/textures/block/nonexistent_ore_n.png": Image.new("RGBA", (16, 16), (128, 128, 255, 255)),
            "assets/minecraft/textures/block/nonexistent_ore_s.png": Image.new("RGBA", (16, 16), (0, 255, 0, 255)),
            "assets/minecraft/textures/block/stone.png": Image.new("RGBA", (16, 16), (128, 128, 128, 255)),
        })

        stack = ResourcePackStack([top_pack])
        atlas_out = self.pack_root / "atlas_orphan_test"
        gen_atlas = AtlasGenerator(fallback_stack=stack)
        res_atlas = gen_atlas.build(atlas_out)

        mapping_file = atlas_out / "atlas_mapping.json"
        self.assertTrue(mapping_file.exists())
        with open(mapping_file, "r", encoding="utf-8") as fp:
            atlas_data = json.load(fp)

        self.assertIn("minecraft:block/stone", atlas_data["textures"])
        self.assertNotIn("minecraft:block/nonexistent_ore", atlas_data["textures"])
        self.assertNotIn("minecraft:block/nonexistent_ore_n", atlas_data["textures"])

        # Test Standalone Generator also isolates missing albedo
        st_out = self.pack_root / "st_orphan_test"
        gen_st = StandaloneGenerator(fallback_stack=stack)
        res_st = gen_st.build(st_out)

        st_mapping_file = st_out / "standalone_mapping.json"
        self.assertTrue(st_mapping_file.exists())
        with open(st_mapping_file, "r", encoding="utf-8") as fp:
            st_data = json.load(fp)

        self.assertIn("minecraft:block/stone", st_data["textures"])
        self.assertNotIn("minecraft:block/nonexistent_ore", st_data["textures"])

    def test_acceptance_per_chunk_pbr_allocation(self):
        """
        Acceptance Matrix #4:
        One category/chunk contains PBR textures, another chunk has only standard Albedo textures.
        Only the PBR chunk writes normal/specular files; pure Albedo chunk files only contain albedo.
        """
        pack = self._create_mock_pack("chunk_pbr_test", {
            # Blocks have PBR
            "assets/minecraft/textures/block/iron_ore.png": Image.new("RGBA", (16, 16), (200, 200, 200, 255)),
            "assets/minecraft/textures/block/iron_ore_n.png": Image.new("RGBA", (16, 16), (128, 128, 255, 255)),
            # Items have NO PBR
            "assets/minecraft/textures/item/apple.png": Image.new("RGBA", (16, 16), (255, 0, 0, 255)),
        })

        stack = ResourcePackStack([pack])
        atlas_out = self.pack_root / "atlas_chunk_test"
        gen = AtlasGenerator(fallback_stack=stack)
        gen.build(atlas_out)

        mapping_file = atlas_out / "atlas_mapping.json"
        with open(mapping_file, "r", encoding="utf-8") as fp:
            mapping = json.load(fp)

        block_chunk = next(c for c in mapping["chunks"] if c["category"] == "blocks")
        item_chunk = next(c for c in mapping["chunks"] if c["category"] == "items")

        # Block chunk has normal
        self.assertIn("normal", block_chunk["files"])
        self.assertTrue((atlas_out / block_chunk["files"]["normal"]).exists())

        # Item chunk has ONLY albedo, NO normal or specular file
        self.assertNotIn("normal", item_chunk["files"])
        self.assertNotIn("specular", item_chunk["files"])

    def test_acceptance_ordered_stack_cache_invalidation(self):
        """
        Acceptance Matrix #5:
        Changing the order of packs, or changing file contents, must change stack_hash and invalidate cache.
        """
        pack_a = self._create_mock_pack("pack_a", {
            "assets/minecraft/textures/block/dirt.png": Image.new("RGBA", (16, 16), (100, 50, 0, 255)),
        })
        pack_b = self._create_mock_pack("pack_b", {
            "assets/minecraft/textures/block/dirt.png": Image.new("RGBA", (16, 16), (200, 100, 0, 255)),
        })

        stack_1 = ResourcePackStack([pack_a, pack_b])
        stack_2 = ResourcePackStack([pack_b, pack_a])

        self.assertNotEqual(stack_1.stack_hash, stack_2.stack_hash)

        # Precompile stack 1
        st_dir_1 = stack_1.get_baked_standalone_dir()
        stack_1.precompile_standalone(st_dir_1)
        self.assertTrue(stack_1.is_standalone_baked())

        # Stack 2 has not been baked
        self.assertFalse(stack_2.is_standalone_baked())

    def test_precompile_mode_dispatch_atlas_vs_standalone(self):
        """
        Verify that:
        - In ATLAS mode, stack.precompile() precompiles Atlas cache only (no Standalone cache).
        - In STANDALONE mode, stack.precompile() precompiles BOTH Atlas and Standalone caches.
        """
        pack = self._create_mock_pack("precompile_mode_pack", {
            "assets/minecraft/textures/block/cobblestone.png": Image.new("RGBA", (16, 16), (100, 100, 100, 255)),
        })
        stack_atlas = ResourcePackStack([pack])

        # 1. Precompile in ATLAS mode
        res_atlas_mode = stack_atlas.precompile(material_mode="ATLAS")
        self.assertIsNotNone(res_atlas_mode.get("atlas"))
        self.assertIsNone(res_atlas_mode.get("standalone"))
        self.assertTrue(stack_atlas.is_stack_baked(yefira_only=False))
        self.assertFalse(stack_atlas.is_standalone_baked())

        # 2. Precompile in STANDALONE mode
        pack_st = self._create_mock_pack("precompile_mode_pack_2", {
            "assets/minecraft/textures/block/sand.png": Image.new("RGBA", (16, 16), (200, 180, 120, 255)),
        })
        stack_st = ResourcePackStack([pack_st])
        res_st_mode = stack_st.precompile(material_mode="STANDALONE")
        self.assertIsNotNone(res_st_mode.get("atlas"))
        self.assertIsNotNone(res_st_mode.get("standalone"))
        self.assertTrue(stack_st.is_stack_baked(yefira_only=False))
        self.assertTrue(stack_st.is_standalone_baked())

    def test_acceptance_atomic_build_protection(self):
        """
        Acceptance Matrix #6:
        Interrupted or failed build must not corrupt previous valid cache or leave incomplete cache marked valid.
        """
        pack = self._create_mock_pack("atomic_test_pack", {
            "assets/minecraft/textures/block/stone.png": Image.new("RGBA", (16, 16), (128, 128, 128, 255)),
        })
        stack = ResourcePackStack([pack])

        # 1. Build initial complete atlas cache
        atlas_dir = stack.get_baked_atlas_dir(yefira_only=False)
        gen = AtlasGenerator(fallback_stack=stack)
        gen.build(atlas_dir)
        self.assertTrue(stack.is_stack_baked(yefira_only=False))

        # 2. Simulate incomplete directory by deleting one referenced file
        mapping_path = atlas_dir / "atlas_mapping.json"
        with open(mapping_path, "r", encoding="utf-8") as fp:
            mapping = json.load(fp)
        albedo_f = mapping["chunks"][0]["files"]["albedo"]
        (atlas_dir / albedo_f).unlink()

        # Incomplete cache must fail validation
        self.assertFalse(stack.is_stack_baked(yefira_only=False))

    def test_acceptance_standalone_precompilation_and_instant_replacement(self):
        """
        Acceptance Matrix #7:
        Stack with animated Albedo (16x256, 16 frames) and static companion _s (16x16).
        Precompilation phase must synthesize aligned strips and mapping.
        Replacement phase must consume precompiled assets with zero live resizing.
        """
        pack = self._create_mock_pack("animated_pbr_pack", {
            "assets/minecraft/textures/block/sea_lantern.png": Image.new("RGBA", (16, 256), (0, 200, 200, 255)),
            "assets/minecraft/textures/block/sea_lantern_s.png": Image.new("RGBA", (16, 16), (255, 0, 100, 255)),
            "assets/minecraft/textures/block/sea_lantern.png.mcmeta": {
                "animation": {"frametime": 2, "interpolate": True}
            },
        })

        stack = ResourcePackStack([pack])
        st_dir = stack.get_baked_standalone_dir()

        # 1. Precompile Standalone and Atlas library
        res = stack.precompile(material_mode="STANDALONE")
        self.assertTrue(stack.is_standalone_baked())

        mapping_file = st_dir / "standalone_mapping.json"
        with open(mapping_file, "r", encoding="utf-8") as fp:
            st_mapping = json.load(fp)

        self.assertEqual(st_mapping["format_version"], STANDALONE_FORMAT_VERSION)
        key = "minecraft:block/sea_lantern"
        self.assertIn(key, st_mapping["textures"])
        entry = st_mapping["textures"][key]

        self.assertTrue(entry["is_animated"])
        self.assertEqual(entry["animation"]["total_frames"], 16)
        self.assertAlmostEqual(entry["animation"]["v_scale"], 1.0 / 16.0, places=4)
        self.assertAlmostEqual(entry["animation"]["v_offset"], 15.0 / 16.0, places=4)

        # Companion specular channel must have been pre-tiled to 16x256
        spec_file = st_dir / entry["files"]["specular"]
        self.assertTrue(spec_file.exists())
        with Image.open(spec_file) as s_img:
            self.assertEqual(s_img.size, (16, 256))

        # 2. Test Viewport Material Replacement in Blender
        if HAS_BPY:
            bpy.ops.mesh.primitive_cube_add()
            cube = bpy.context.active_object
            cube.name = "SpecTestCube"
            cube.data.materials.clear()
            cube.data.materials.append(bpy.data.materials.new(name="sea_lantern"))

            params = {
                "pack_stack": stack,
                "material_mode": "STANDALONE",
                "pack_textures": True,
                "use_cache": True,
            }
            res_pipe, ctx_pipe = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[cube])
            self.assertTrue(res_pipe.is_success, ctx_pipe.reports)

            mat = cube.material_slots[0].material
            self.assertEqual(detect_material_mode(mat), "STANDALONE")

            # Check that Atlas cache was also precompiled alongside standalone for Live Sync
            self.assertTrue(stack.is_stack_baked(yefira_only=False))

            # Check loop UVs are baked to Frame 0
            uv_layer = cube.data.uv_layers.active
            v_coords = [item.uv.y for item in uv_layer.data]
            self.assertAlmostEqual(max(v_coords), 1.0, places=4)
            self.assertAlmostEqual(min(v_coords), 15.0 / 16.0, places=4)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
