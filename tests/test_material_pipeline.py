"""
Tests for Material Pipeline and Shader Builders.
Can be executed under standard Python (with mocks) or headless Blender.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
libmtk_release_path = PROJECT_DIR.parent / "libmozitoolkit" / "target" / "release"

for p in [str(libmtk_release_path), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)


try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from utils.materials.builder.standalone_builder import build_standalone_material
from utils.materials.builder.atlas_builder import build_atlas_chunk_material
from utils.materials.pipeline import replace_materials, restore_materials_from_provenance
from utils.materials.biome.updater import update_object_biome
from utils.materials.constants import (
    ATTR_BIOME_TINT_DATA,
    ATTR_BIOME_TINT_COLOR,
    ATTR_COLORMAP_UV,
)


def _write_dummy_png(path: Path):
    """Helper to write a valid PNG file."""
    if HAS_BPY:
        img = bpy.data.images.new(path.name, width=16, height=16)
        img.filepath_raw = str(path)
        img.file_format = 'PNG'
        img.save()
        bpy.data.images.remove(img)
    else:
        path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


class TestMaterialPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if HAS_BPY:
            import ui.panel_biome
            ui.panel_biome.register()

    @classmethod
    def tearDownClass(cls):
        if HAS_BPY:
            import ui.panel_biome
            try:
                ui.panel_biome.unregister()
            except Exception:
                pass

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_standalone_material_construction_in_blender(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            albedo_file = tmp_path / "stone.png"
            normal_file = tmp_path / "stone_n.png"
            spec_file = tmp_path / "stone_s.png"

            _write_dummy_png(albedo_file)
            _write_dummy_png(normal_file)
            _write_dummy_png(spec_file)

            mat = build_standalone_material(
                texture_key="minecraft:block/stone",
                albedo_path=albedo_file,
                normal_path=normal_file,
                specular_path=spec_file,
                stack_fingerprint="test_fp_123",
                use_labpbr=True,
            )

            self.assertIsNotNone(mat)
            self.assertEqual(mat.name, "MTK:minecraft:block/stone")
            self.assertEqual(mat["mtk_material_mode"], "STANDALONE")
            self.assertEqual(mat["mtk_source_texture_key"], "minecraft:block/stone")
            self.assertEqual(mat["mtk_stack_fingerprint"], "test_fp_123")
            self.assertFalse(mat["mtk_is_animated"])
            self.assertTrue(mat.use_nodes)

            # Check nodes
            node_names = [n.name for n in mat.node_tree.nodes]
            self.assertIn("Albedo Texture", node_names)
            self.assertIn("Normal Texture", node_names)
            self.assertIn("Specular Texture", node_names)
            self.assertIn("MC Biome Tint", node_names)
            self.assertIn("LabPBR Decoder", node_names)
            self.assertIn("Material Output", node_names)

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_standalone_material_with_colormaps_and_overlay(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            albedo_file = tmp_path / "grass_block_side.png"
            overlay_file = tmp_path / "grass_block_side_overlay.png"
            grass_cm = tmp_path / "grass.png"
            foliage_cm = tmp_path / "foliage.png"

            _write_dummy_png(albedo_file)
            _write_dummy_png(overlay_file)
            _write_dummy_png(grass_cm)
            _write_dummy_png(foliage_cm)

            colormaps = {"grass": grass_cm, "foliage": foliage_cm}

            mat = build_standalone_material(
                texture_key="minecraft:block/grass_block_side",
                albedo_path=albedo_file,
                overlay_path=overlay_file,
                colormaps=colormaps,
                stack_fingerprint="test_fp_grass",
                use_labpbr=True,
            )

            self.assertIsNotNone(mat)
            self.assertTrue(mat["mtk_has_overlay"])

            node_names = [n.name for n in mat.node_tree.nodes]
            self.assertIn("Albedo Texture", node_names)
            self.assertIn("Overlay Texture", node_names)
            self.assertIn("MC Biome Tint", node_names)
            self.assertIn("MC Biome Colormap Decoder", node_names)
            self.assertIn("Colormap Grass", node_names)
            self.assertIn("Colormap Foliage", node_names)

            # Verify Colormap nodes use Linear interpolation and EXTEND extension
            cm_grass_node = mat.node_tree.nodes["Colormap Grass"]
            self.assertEqual(cm_grass_node.interpolation, "Linear")
            self.assertEqual(cm_grass_node.extension, "EXTEND")

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_atlas_chunk_material_construction_in_blender(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            albedo_file = tmp_path / "blocks_chunk_001.png"
            _write_dummy_png(albedo_file)

            mat = build_atlas_chunk_material(
                chunk_id=0,
                albedo_path=albedo_file,
                category="blocks",
                category_chunk_index=1,
                stack_fingerprint="test_fp_456",
                use_attribute_node=True,
                use_labpbr=True,
            )

            self.assertIsNotNone(mat)
            self.assertEqual(mat.name, "MTK:Atlas:blocks:001")
            self.assertEqual(mat["mtk_material_mode"], "ATLAS")
            self.assertEqual(mat["mtk_atlas_category"], "blocks")
            self.assertEqual(mat["mtk_atlas_chunk_id"], 0)
            self.assertEqual(mat["mtk_atlas_chunk_index"], 1)
            self.assertEqual(mat["mtk_stack_fingerprint"], "test_fp_456")
            self.assertFalse(mat["mtk_is_animated"])

            node_names = [n.name for n in mat.node_tree.nodes]
            self.assertIn("Atlas Albedo Texture", node_names)
            self.assertIn("MTK UV Transform", node_names)
            self.assertIn("MTK UV Rotation", node_names)
            self.assertIn("Atlas UV Tiling", node_names)
            self.assertIn("LabPBR Decoder", node_names)

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_atlas_chunk_material_with_overlay_in_blender(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            albedo_file = tmp_path / "blocks_chunk_001.png"
            overlay_file = tmp_path / "blocks_chunk_001_overlay.png"
            grass_cm = tmp_path / "grass.png"
            _write_dummy_png(albedo_file)
            _write_dummy_png(overlay_file)
            _write_dummy_png(grass_cm)

            mat = build_atlas_chunk_material(
                chunk_id=0,
                albedo_path=albedo_file,
                overlay_path=overlay_file,
                colormaps={"grass": grass_cm},
                category="blocks",
                category_chunk_index=1,
                stack_fingerprint="test_fp_overlay",
                use_attribute_node=True,
                use_labpbr=True,
            )

            self.assertIsNotNone(mat)
            self.assertEqual(mat.name, "MTK:Atlas:blocks:001")
            self.assertTrue(mat["mtk_has_overlay"])

            node_names = [n.name for n in mat.node_tree.nodes]
            self.assertIn("Atlas Albedo Texture", node_names)
            self.assertIn("Atlas Overlay Texture", node_names)
            self.assertIn("Biome Tint", node_names)
            self.assertIn("MC Biome Colormap Decoder", node_names)
            self.assertIn("Colormap Grass", node_names)
            self.assertIn("LabPBR Decoder", node_names)

            cm_grass_node = mat.node_tree.nodes["Colormap Grass"]
            self.assertEqual(cm_grass_node.interpolation, "Linear")
            self.assertEqual(cm_grass_node.extension, "EXTEND")

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_end_to_end_material_replacement_and_provenance(self):
        # Create a test cube in Blender
        bpy.ops.mesh.primitive_cube_add(size=2.0)
        obj = bpy.context.active_object
        self.assertIsNotNone(obj)
        mesh = obj.data

        # Give it a material slot named "grass_block_top"
        src_mat = bpy.data.materials.new(name="minecraft:block/grass_block_top")
        mesh.materials.append(src_mat)

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            atlas_dir = cache_dir / "atlas"
            standalone_dir = cache_dir / "standalone"
            colormaps_dir = cache_dir / "colormaps"
            atlas_dir.mkdir(parents=True, exist_ok=True)
            standalone_dir.mkdir(parents=True, exist_ok=True)
            colormaps_dir.mkdir(parents=True, exist_ok=True)

            _write_dummy_png(atlas_dir / "blocks_chunk_001.png")
            _write_dummy_png(colormaps_dir / "grass.png")
            _write_dummy_png(colormaps_dir / "foliage.png")
            (standalone_dir / "assets" / "minecraft" / "textures" / "block").mkdir(parents=True, exist_ok=True)
            _write_dummy_png(standalone_dir / "assets" / "minecraft" / "textures" / "block" / "grass_block_top.png")

            # Write cache_manifest.json
            manifest = {
                "fingerprint": "abc123stackfp",
                "packs": []
            }
            (cache_dir / "cache_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            # Write atlas_mapping.json
            atlas_mapping = {
                "chunks": [
                    {
                        "chunk_id": 0,
                        "category": "blocks",
                        "is_animated": False,
                        "category_chunk_index": 1,
                        "width": 1024,
                        "height": 1024,
                        "has_normal": False,
                        "has_specular": False,
                    }
                ],
                "sprites": {
                    "minecraft:block/grass_block_top": {
                        "chunk_id": 0,
                        "category": "blocks",
                        "is_animated": False,
                        "texture_id": 1,
                        "uv_bounds": [0.0, 0.0, 1.0, 1.0],
                        "frame_0_uv_bounds": [0.0, 0.0, 1.0, 1.0],
                        "local_uv_bounds": [0.0, 0.0, 1.0, 1.0],
                        "pixel_rect": [0, 0, 16, 16],
                        "frame_size": [16, 16],
                        "frame_count": 1,
                        "has_normal": False,
                        "has_specular": False,
                    }
                }
            }
            (atlas_dir / "atlas_mapping.json").write_text(json.dumps(atlas_mapping), encoding="utf-8")

            # Write standalone_mapping.json
            sa_mapping = {
                "format_version": 3,
                "textures": {
                    "minecraft:block/grass_block_top": {
                        "files": {"albedo": "assets/minecraft/textures/block/grass_block_top.png"},
                        "is_animated": False
                    }
                }
            }
            (standalone_dir / "standalone_mapping.json").write_text(json.dumps(sa_mapping), encoding="utf-8")

            # Mock get_cache_dir to return our temporary test cache
            with patch("utils.materials.pipeline.get_cache_dir", return_value=cache_dir):
                # 1. Replace Materials (Atlas Mode)
                res = replace_materials(obj, mode="ATLAS", origin="AUTO", biome="BADLANDS")
                self.assertTrue(res["success"])
                self.assertEqual(res["face_count"], len(mesh.polygons))
                self.assertIn("mtk_source_texture_key", mesh.attributes)
                self.assertIn("mtk_atlas_chunk_id", mesh.attributes)
                self.assertIn("mtk_uv_transform", mesh.attributes)
                self.assertIn(ATTR_BIOME_TINT_DATA, mesh.attributes)
                self.assertIn(ATTR_BIOME_TINT_COLOR, mesh.attributes)
                self.assertIn(ATTR_COLORMAP_UV, mesh.attributes)
                self.assertEqual(mesh.materials[0].name, "MTK:Atlas:blocks:001")
                self.assertEqual(mesh.materials[0]["mtk_stack_fingerprint"], "abc123stackfp")

                # Verify Badlands Biome attributes
                tint_data_attr = mesh.attributes[ATTR_BIOME_TINT_DATA]
                self.assertEqual(len(tint_data_attr.data), len(mesh.polygons))

                # 2. Test Instant Biome Switching (<1ms)
                updated = update_object_biome(obj, "DESERT")
                self.assertTrue(updated)
                self.assertEqual(obj["mtk:biome_preset"], "DESERT")

                # 3. Clear materials and restore from provenance
                mesh.materials.clear()
                self.assertEqual(len(mesh.materials), 0)

                restore_res = restore_materials_from_provenance(obj, mode="ATLAS")
                self.assertTrue(restore_res["success"])
                self.assertEqual(len(mesh.materials), 1)
                self.assertEqual(mesh.materials[0].name, "MTK:Atlas:blocks:001")
                self.assertEqual(mesh.materials[0]["mtk_stack_fingerprint"], "abc123stackfp")
                self.assertIn(ATTR_BIOME_TINT_DATA, mesh.attributes)

                # 4. Replace Materials (Standalone Mode)
                res_sa = replace_materials(obj, mode="STANDALONE", origin="AUTO", biome="PLAINS")
                self.assertTrue(res_sa["success"])
                self.assertEqual(mesh.materials[0].name, "MTK:minecraft:block/grass_block_top")
                self.assertEqual(mesh.materials[0]["mtk_stack_fingerprint"], "abc123stackfp")
                self.assertIn(ATTR_BIOME_TINT_DATA, mesh.attributes)

                # 5. Test Custom Biome with Temperature/Humidity & Direct Color Overrides
                obj.mtk_biome_temp = 0.5
                obj.mtk_biome_humidity = 0.9
                obj.mtk_biome_use_custom_grass = True
                obj.mtk_biome_grass_color = (1.0, 0.0, 0.0, 1.0)
                custom_updated = update_object_biome(obj, "CUSTOM")
                self.assertTrue(custom_updated)
                self.assertEqual(obj["mtk:biome_preset"], "CUSTOM")

                # Verify Standalone mode custom color applied directly to MC Biome Tint node
                mat = mesh.materials[0]
                biome_node = mat.node_tree.nodes.get("MC Biome Tint")
                self.assertIsNotNone(biome_node)
                self.assertEqual(tuple(biome_node.inputs["Tint Color"].default_value), (1.0, 0.0, 0.0, 1.0))


if __name__ == "__main__":
    if "--" in sys.argv:
        argv = [sys.argv[0]] + sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = [sys.argv[0]]
    unittest.main(argv=argv)


