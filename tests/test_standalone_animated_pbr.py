"""
Unit and integration tests for Standalone animated material + PBR texture alignment and node graphs.
"""

from __future__ import annotations

import unittest
import sys
from pathlib import Path
import tempfile
import shutil
import json

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Bootstrap MoziToolKit package so top-level pipeline/operators/ui imports resolve
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

import bpy
from PIL import Image

from utils.system import has_pillow
from utils.materials import (
    align_standalone_textures,
    rebuild_material,
    inspect_material_nodes,
    ZipResourcePack,
)
from pipeline.presets import run_preset_pipeline


class TestStandaloneAnimatedPBR(unittest.TestCase):
    """Test suite for Standalone animated materials with PBR texture alignment."""

    def setUp(self):
        if not has_pillow():
            self.skipTest("Pillow not installed in test environment")

        self.tmp_dir = tempfile.mkdtemp()
        self.pack_dir = Path(self.tmp_dir) / "test_pack"
        self.tex_dir = self.pack_dir / "assets" / "minecraft" / "textures" / "block"
        self.tex_dir.mkdir(parents=True, exist_ok=True)

        # Create dummy pack.mcmeta
        mcmeta_path = self.pack_dir / "pack.mcmeta"
        mcmeta_path.write_text('{"pack": {"pack_format": 15, "description": "Test Pack"}}', encoding="utf-8")

        # Create a test mesh object in Blender
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.mesh.primitive_cube_add()
        self.cube = bpy.context.active_object
        self.cube.name = "TestAnimatedPBRCube"

    def tearDown(self):
        if hasattr(self, "cube") and self.cube and self.cube.name in bpy.data.objects:
            bpy.data.objects.remove(self.cube, do_unlink=True)

        for mat in list(bpy.data.materials):
            if mat.name.startswith("mtk:") or mat.name.startswith("sea_lantern") or mat.name.startswith("water_still"):
                bpy.data.materials.remove(mat, do_unlink=True)

        if Path(self.tmp_dir).exists():
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_align_standalone_textures_tiles_static_pbr_channels(self):
        """align_standalone_textures must tile static 1-frame _n and _s channels to match Albedo's 32 frames."""
        albedo_path = self.tex_dir / "sea_lantern.png"
        normal_path = self.tex_dir / "sea_lantern_n.png"
        specular_path = self.tex_dir / "sea_lantern_s.png"

        # Albedo: 16x512 (32 frames of 16x16)
        img_albedo = Image.new("RGBA", (16, 512), (0, 200, 200, 255))
        img_albedo.save(albedo_path)

        # Normal: 16x16 (1 frame static)
        img_normal = Image.new("RGBA", (16, 16), (128, 128, 255, 255))
        img_normal.save(normal_path)

        # Specular: 64x64 (1 frame static, high-res)
        img_specular = Image.new("RGBA", (64, 64), (255, 0, 100, 200))
        img_specular.save(specular_path)

        # mcmeta for albedo: 32 frames, frametime 2, interpolate True
        albedo_mcmeta = {
            "frametime": 2,
            "interpolate": True,
            "width": 16,
            "height": 16,
            "frames": list(range(32)),
        }

        tex_info = {
            "namespace": "minecraft",
            "texture_name": "sea_lantern",
            "texture_key": "block/sea_lantern",
            "albedo": albedo_path,
            "albedo_mcmeta": albedo_mcmeta,
            "normal": normal_path,
            "normal_mcmeta": None,
            "specular": specular_path,
            "specular_mcmeta": None,
            "pack_hash": "testpackhash123",
        }

        aligned_info = align_standalone_textures(tex_info, pack_hash="testpackhash123")

        # Albedo should remain unchanged
        self.assertEqual(aligned_info["albedo"], albedo_path)
        self.assertEqual(aligned_info["albedo_mcmeta"]["frametime"], 2)

        # Normal should be aligned to 16x512
        aligned_normal_path = aligned_info["normal"]
        self.assertTrue(aligned_normal_path.exists())
        with Image.open(aligned_normal_path) as n_img:
            self.assertEqual(n_img.size, (16, 512))
        self.assertIsNotNone(aligned_info["normal_mcmeta"])
        self.assertEqual(aligned_info["normal_mcmeta"]["frametime"], 2)
        self.assertEqual(aligned_info["normal_mcmeta"]["height"], 16)

        # Specular should be aligned to 64x2048 (32 frames of 64x64)
        aligned_specular_path = aligned_info["specular"]
        self.assertTrue(aligned_specular_path.exists())
        with Image.open(aligned_specular_path) as s_img:
            self.assertEqual(s_img.size, (64, 2048))
        self.assertIsNotNone(aligned_info["specular_mcmeta"])
        self.assertEqual(aligned_info["specular_mcmeta"]["frametime"], 2)
        self.assertEqual(aligned_info["specular_mcmeta"]["height"], 64)

    def test_rebuild_material_constructs_synchronized_pbr_animation_nodes(self):
        """rebuild_material must construct a single shared scheduler and UV mapping node for all animated PBR channels."""
        albedo_path = self.tex_dir / "magma.png"
        normal_path = self.tex_dir / "magma_n.png"
        specular_path = self.tex_dir / "magma_s.png"

        Image.new("RGBA", (16, 256), (255, 100, 0, 255)).save(albedo_path)
        Image.new("RGBA", (16, 16), (128, 128, 255, 255)).save(normal_path)
        Image.new("RGBA", (16, 16), (0, 255, 0, 255)).save(specular_path)

        mcmeta_path = self.tex_dir / "magma.png.mcmeta"
        mcmeta_path.write_text('{"animation": {"frametime": 3, "interpolate": true}}', encoding="utf-8")

        pack = ZipResourcePack(self.pack_dir, use_cache=False)
        tex_info = pack.get_texture_info("magma")
        self.assertIsNotNone(tex_info)

        mat = bpy.data.materials.new(name="mtk:minecraft:magma")
        success = rebuild_material(mat, tex_info, pack_textures=True, pack_hash=pack.pack_hash)
        self.assertTrue(success)

        # Inspect material node tree
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        # 1. Exactly 1 shared Scheduler and 1 shared UV Mapping group
        sched_nodes = [n for n in nodes if n.type == "GROUP" and n.node_tree and "Scheduler" in n.node_tree.name]
        uv_nodes = [n for n in nodes if n.type == "GROUP" and n.node_tree and "UV_Mapping" in n.node_tree.name]
        self.assertEqual(len(sched_nodes), 1, "Expected exactly 1 shared Scheduler node group")
        self.assertEqual(len(uv_nodes), 1, "Expected exactly 1 shared UV Mapping node group")

        shared_uv = uv_nodes[0]
        self.assertEqual(float(shared_uv.inputs["Atlas Mode"].default_value), 1.0)

        # 2. Image textures for Albedo, Normal, and Specular (each with Current and Next)
        tex_curr_nodes = [n for n in nodes if n.type == "TEX_IMAGE" and "Current" in n.name]
        tex_next_nodes = [n for n in nodes if n.type == "TEX_IMAGE" and "Next" in n.name]
        self.assertEqual(len(tex_curr_nodes), 3, "Expected Tex Current for Albedo, Normal, and Specular")
        self.assertEqual(len(tex_next_nodes), 3, "Expected Tex Next for Albedo, Normal, and Specular")

        # 3. Verify Tex Current & Next are connected to shared UV node outputs
        for tex_curr in tex_curr_nodes:
            in_link = next((l for l in links if l.to_node == tex_curr and l.to_socket.name == "Vector"), None)
            self.assertIsNotNone(in_link)
            self.assertEqual(in_link.from_node, shared_uv)
            self.assertEqual(in_link.from_socket.name, "Current UV")

        for tex_next in tex_next_nodes:
            in_link = next((l for l in links if l.to_node == tex_next and l.to_socket.name == "Vector"), None)
            self.assertIsNotNone(in_link)
            self.assertEqual(in_link.from_node, shared_uv)
            self.assertEqual(in_link.from_socket.name, "Next UV")

        # 4. Verify Frame Blend nodes for each channel
        blend_nodes = [n for n in nodes if n.type == "GROUP" and n.node_tree and "Frame_Blend" in n.node_tree.name]
        self.assertEqual(len(blend_nodes), 3, "Expected 3 Frame Blend nodes (Albedo, Normal, Specular)")

        # 5. Decoder node connections
        decoder = next((n for n in nodes if n.type == "GROUP" and n.node_tree and "LabPBR" in n.node_tree.name), None)
        self.assertIsNotNone(decoder)
        self.assertTrue(decoder.inputs["Normal (_n) Color"].is_linked)
        self.assertTrue(decoder.inputs["Specular (_s) Color"].is_linked)

        # 6. Overall material health
        health = inspect_material_nodes(mat)
        self.assertTrue(health["is_healthy"], f"Material issues: {health['issues']}")

    def test_pipeline_standalone_animated_pbr_bakes_frame_0_uv(self):
        """End-to-end pipeline replacement in Standalone mode must bake Frame 0 UVs and assign aligned PBR material."""
        albedo_path = self.tex_dir / "sea_lantern.png"
        normal_path = self.tex_dir / "sea_lantern_n.png"
        specular_path = self.tex_dir / "sea_lantern_s.png"

        Image.new("RGBA", (16, 512), (0, 200, 200, 255)).save(albedo_path)
        Image.new("RGBA", (16, 16), (128, 128, 255, 255)).save(normal_path)
        Image.new("RGBA", (16, 16), (255, 0, 100, 200)).save(specular_path)

        mcmeta_path = self.tex_dir / "sea_lantern.png.mcmeta"
        mcmeta_path.write_text('{"animation": {"frametime": 2}}', encoding="utf-8")

        self.cube.data.materials.clear()
        initial_mat = bpy.data.materials.new(name="sea_lantern")
        self.cube.data.materials.append(initial_mat)

        params = {
            "zip_path": str(self.pack_dir),
            "material_mode": "STANDALONE",
            "pack_textures": True,
            "use_cache": False,
        }
        res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[self.cube])
        self.assertTrue(res.is_success, ctx.reports)

        assigned_mat = self.cube.material_slots[0].material
        self.assertTrue(assigned_mat.name.startswith("mtk:minecraft:sea_lantern"))

        # Verify UV coordinates on the mesh are baked to Frame 0: V in [31/32, 1.0]
        uv_layer = self.cube.data.uv_layers.active
        v_coords = [item.uv.y for item in uv_layer.data]
        min_v = min(v_coords)
        max_v = max(v_coords)
        self.assertAlmostEqual(max_v, 1.0, places=4)
        self.assertAlmostEqual(min_v, 1.0 - 16.0 / 512.0, places=4)

    def test_static_materials_remain_unaltered(self):
        """Materials with purely static textures (no animation) must not create animation nodes."""
        stone_albedo = self.tex_dir / "stone.png"
        stone_normal = self.tex_dir / "stone_n.png"
        stone_specular = self.tex_dir / "stone_s.png"

        Image.new("RGBA", (16, 16), (128, 128, 128, 255)).save(stone_albedo)
        Image.new("RGBA", (16, 16), (128, 128, 255, 255)).save(stone_normal)
        Image.new("RGBA", (16, 16), (0, 0, 0, 255)).save(stone_specular)

        pack = ZipResourcePack(self.pack_dir, use_cache=False)
        tex_info = pack.get_texture_info("stone")

        mat = bpy.data.materials.new(name="mtk:minecraft:stone")
        rebuild_material(mat, tex_info, pack_textures=True, pack_hash=pack.pack_hash)

        nodes = mat.node_tree.nodes
        sched_nodes = [n for n in nodes if n.type == "GROUP" and n.node_tree and "Scheduler" in n.node_tree.name]
        uv_nodes = [n for n in nodes if n.type == "GROUP" and n.node_tree and "UV_Mapping" in n.node_tree.name]
        static_tex_nodes = [n for n in nodes if n.type == "TEX_IMAGE" and "Static" in n.name]

        self.assertEqual(len(sched_nodes), 0, "Static material must have 0 scheduler nodes")
        self.assertEqual(len(uv_nodes), 0, "Static material must have 0 UV mapping group nodes")
        self.assertEqual(len(static_tex_nodes), 3, "Static material must have 3 static texture nodes")

        health = inspect_material_nodes(mat)
        self.assertTrue(health["is_healthy"], f"Material issues: {health['issues']}")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
