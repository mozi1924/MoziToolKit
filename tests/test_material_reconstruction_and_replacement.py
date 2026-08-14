"""
Comprehensive Unit and Integration Tests for Material Identification, Node Reconstruction,
LabPBR & Animated UV Node Repair, and Cross-Mode Replacement with UV Inversion.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import bpy
    HAS_BPY = True
except ImportError:
    HAS_BPY = False

from utils.atlas_layout import (
    atlas_uv_from_local,
    local_uv_from_atlas,
    atlas_uv_from_rect,
    local_uv_from_rect,
    find_texture_id_from_atlas_uv,
)
from utils.material_matching import (
    detect_material_mode,
    is_mozi_material,
    extract_face_texture_info,
)
from utils.material_builder import (
    inspect_material_nodes,
    repair_material_nodes,
)
from pipeline.presets import run_preset_pipeline


class TestUVTransformMath(unittest.TestCase):
    """Test precision and invertibility of Atlas <-> Local UV coordinate math."""

    def test_static_atlas_uv_roundtrip(self):
        cases = [
            (0.0, 0.0, 0, 0, 16, 256, 256),
            (1.0, 1.0, 3, 5, 16, 512, 1024),
            (0.25, 0.75, 7, 2, 32, 1024, 2048),
            (0.5, 0.5, 15, 63, 16, 256, 1024),
            # Testing sub-quad and scaled UV values (> 1.0 or < 0.0)
            (1.2, -0.2, 2, 4, 16, 512, 512),
        ]
        for u_orig, v_orig, col, row, tile_size, atlas_w, atlas_h in cases:
            u_atlas, v_atlas = atlas_uv_from_local(
                u_orig, v_orig,
                tile_column=col,
                tile_row=row,
                tile_size=tile_size,
                atlas_width=atlas_w,
                atlas_height=atlas_h,
            )
            u_recovered, v_recovered = local_uv_from_atlas(
                u_atlas, v_atlas,
                tile_column=col,
                tile_row=row,
                tile_size=tile_size,
                atlas_width=atlas_w,
                atlas_height=atlas_h,
            )
            self.assertAlmostEqual(u_orig, u_recovered, places=6)
            self.assertAlmostEqual(v_orig, v_recovered, places=6)

    def test_rect_atlas_uv_roundtrip(self):
        cases = [
            (0.0, 0.0, 0, 0, 16, 16, 256, 512),
            (1.0, 1.0, 64, 0, 32, 32, 512, 1024),
            (0.33, 0.67, 128, 0, 16, 16, 1024, 1024),
        ]
        for u_orig, v_orig, px, py, rw, rh, atlas_w, atlas_h in cases:
            u_atlas, v_atlas = atlas_uv_from_rect(
                u_orig, v_orig,
                pixel_x=px,
                pixel_y=py,
                rect_width=rw,
                rect_height=rh,
                atlas_width=atlas_w,
                atlas_height=atlas_h,
            )
            u_recovered, v_recovered = local_uv_from_rect(
                u_atlas, v_atlas,
                pixel_x=px,
                pixel_y=py,
                rect_width=rw,
                rect_height=rh,
                atlas_width=atlas_w,
                atlas_height=atlas_h,
            )
            self.assertAlmostEqual(u_orig, u_recovered, places=6)
            self.assertAlmostEqual(v_orig, v_recovered, places=6)


class TestMaterialReconstructionAndRepair(unittest.TestCase):
    """Test material classification, node tree health inspection, and repair."""

    def setUp(self):
        if not HAS_BPY:
            self.skipTest("bpy not available")
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def test_material_mode_detection(self):
        # Generic
        mat_gen = bpy.data.materials.new("Vanilla_Stone")
        self.assertEqual(detect_material_mode(mat_gen), "GENERIC")
        self.assertFalse(is_mozi_material(mat_gen))

        # Standalone Mozi
        mat_mozi = bpy.data.materials.new("mtk:minecraft:stone:a1b2c3d4e5f6")
        mat_mozi["mtk:source_namespace"] = "minecraft"
        mat_mozi["mtk:source_texture"] = "stone"
        self.assertEqual(detect_material_mode(mat_mozi), "STANDALONE")
        self.assertTrue(is_mozi_material(mat_mozi))

        # Atlas Chunk
        mat_chunk = bpy.data.materials.new("mtk:minecraft:atlas_chunk_000:a1b2c3d4e5f6")
        mat_chunk["mtk:atlas_chunk_id"] = 0
        self.assertEqual(detect_material_mode(mat_chunk), "ATLAS_CHUNK")
        self.assertTrue(is_mozi_material(mat_chunk))

    def test_repair_missing_decoder_and_links(self):
        mat = bpy.data.materials.new("Test_Broken_LabPBR")
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()

        # Only output node exists, no decoder
        out_node = nt.nodes.new("ShaderNodeOutputMaterial")

        report = inspect_material_nodes(mat)
        self.assertFalse(report["is_healthy"])
        self.assertFalse(report["has_decoder_node"])

        # Run repair
        success = repair_material_nodes(mat)
        self.assertTrue(success)

        report_after = inspect_material_nodes(mat)
        self.assertTrue(report_after["is_healthy"])
        self.assertTrue(report_after["has_decoder_node"])
        self.assertTrue(report_after["bsdf_linked"])


class TestCrossModeMaterialReplacement(unittest.TestCase):
    """Integration test for Standalone <-> Atlas cross-mode replacements with UV restoration."""

    def setUp(self):
        import tempfile
        if not HAS_BPY:
            self.skipTest("bpy not available")

        self.temp_dir = tempfile.TemporaryDirectory()
        self.pack_dir = Path(self.temp_dir.name)
        tex_dir = self.pack_dir / "assets/minecraft/textures/block"
        tex_dir.mkdir(parents=True, exist_ok=True)

        # Create test texture: stone.png
        stone_file = tex_dir / "stone.png"
        img_stone = bpy.data.images.new("temp_stone", width=16, height=16)
        img_stone.filepath_raw = str(stone_file)
        img_stone.file_format = "PNG"
        img_stone.save()
        bpy.data.images.remove(img_stone)

        # Create test texture: dirt.png
        dirt_file = tex_dir / "dirt.png"
        img_dirt = bpy.data.images.new("temp_dirt", width=16, height=16)
        img_dirt.filepath_raw = str(dirt_file)
        img_dirt.file_format = "PNG"
        img_dirt.save()
        bpy.data.images.remove(img_dirt)

        bpy.ops.wm.read_factory_settings(use_empty=True)

        # Create a cube object
        bpy.ops.mesh.primitive_cube_add(size=2.0)
        self.cube = bpy.context.active_object
        self.cube.name = "TestCube"

        # Assign initial vanilla material
        mat = bpy.data.materials.new(name="stone")
        self.cube.data.materials.append(mat)
        uv_layer = self.cube.data.uv_layers.active
        self.original_uv_coords = [(item.uv.x, item.uv.y) for item in uv_layer.data]

    def tearDown(self):
        if hasattr(self, "temp_dir"):
            self.temp_dir.cleanup()

    def test_standalone_to_atlas_to_standalone_cycle(self):
        # Step 1: Initial Standalone Replace
        params_standalone = {
            "zip_path": str(self.pack_dir),
            "material_mode": "STANDALONE",
            "pack_textures": True,
            "use_cache": False,
        }
        res1, ctx1 = run_preset_pipeline("replace_material", bpy.context, params=params_standalone, target_objects=[self.cube])
        self.assertTrue(res1.is_success, f"res1 failed: {res1.message} - reports: {ctx1.reports}")
        self.assertEqual(len(self.cube.material_slots), 1)
        self.assertTrue(self.cube.material_slots[0].material.name.startswith("mtk:minecraft:stone"))

        # Step 2: Convert Standalone -> Atlas
        from utils.dependencies import has_pillow
        if not has_pillow():
            self.skipTest("Pillow is not installed in current environment; skipping Atlas step")

        params_atlas = {
            "zip_path": str(self.pack_dir),
            "material_mode": "ATLAS",
            "pack_textures": True,
            "use_cache": False,
        }
        res2, ctx2 = run_preset_pipeline("replace_material", bpy.context, params=params_atlas, target_objects=[self.cube])
        self.assertTrue(res2.is_success, f"res2 failed: {res2.message} - reports: {ctx2.reports}")
        self.assertTrue(self.cube.material_slots[0].material.name.startswith("mtk:minecraft:atlas_chunk_"))
        self.assertIn("atlas_chunk_id", self.cube.data.attributes)
        self.assertIn("atlas_texture_id", self.cube.data.attributes)

        # Verify UVs moved into Atlas cells
        uv_layer = self.cube.data.uv_layers.active
        atlas_uv_coords = [(item.uv.x, item.uv.y) for item in uv_layer.data]
        self.assertTrue(any(abs(a[0] - o[0]) > 1e-4 or abs(a[1] - o[1]) > 1e-4
                            for a, o in zip(atlas_uv_coords, self.original_uv_coords)))

        # Step 3: Convert Atlas -> Standalone (Invert UVs and restore standalone material)
        res3, ctx3 = run_preset_pipeline("replace_material", bpy.context, params=params_standalone, target_objects=[self.cube])
        self.assertTrue(res3.is_success, f"res3 failed: {res3.message} - reports: {ctx3.reports}")
        self.assertTrue(self.cube.material_slots[0].material.name.startswith("mtk:minecraft:stone"))

        # Verify attributes cleaned up
        self.assertNotIn("atlas_chunk_id", self.cube.data.attributes)
        self.assertNotIn("atlas_texture_id", self.cube.data.attributes)

        # Verify UVs restored back to original [0, 1] UV space!
        restored_uv_coords = [(item.uv.x, item.uv.y) for item in uv_layer.data]
        for (u_res, v_res), (u_orig, v_orig) in zip(restored_uv_coords, self.original_uv_coords):
            self.assertAlmostEqual(u_res, u_orig, places=4)
            self.assertAlmostEqual(v_res, v_orig, places=4)


def run_all_tests():
    import os
    print("=" * 60)
    print("Running Material Reconstruction & Replacement Unit Tests...")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestUVTransformMath))
    suite.addTests(loader.loadTestsFromTestCase(TestMaterialReconstructionAndRepair))
    suite.addTests(loader.loadTestsFromTestCase(TestCrossModeMaterialReplacement))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("\n✅ ALL TESTS PASSED SUCCESSFULLY!")
        os._exit(0)
    else:
        print("\n❌ SOME TESTS FAILED!")
        os._exit(1)


if __name__ == "__main__":
    run_all_tests()
