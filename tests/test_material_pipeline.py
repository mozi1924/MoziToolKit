"""
Tests for Material Pipeline and Shader Builders.
Can be executed under standard Python (with mocks) or headless Blender.
"""

import array
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
    HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "meshes") and not isinstance(bpy.data, MagicMock)
except ImportError:
    bpy = MagicMock()
    sys.modules["bpy"] = bpy
    sys.modules["bpy.props"] = MagicMock()
    sys.modules["bpy.types"] = MagicMock()
    sys.modules["bpy.app"] = MagicMock()
    HAS_BPY = False

from MoziToolKit.utils.materials.builder.atlas_builder import build_atlas_chunk_material
from MoziToolKit.utils.materials.pipeline import (
    replace_materials,
    restore_materials_from_provenance,
)
from MoziToolKit.utils.materials.biome.updater import update_object_biome
from MoziToolKit.utils.materials.constants import (
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


def _read_loop_uvs(layer):
    """Read a UV layer as rounded per-loop tuples."""
    return [tuple(round(float(v), 6) for v in loop.uv) for loop in layer.data]


class TestMaterialPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if HAS_BPY:
            import MoziToolKit.ui as ui
            import MoziToolKit.ui.panel_biome
            ui.panel_biome.register()

    @classmethod
    def tearDownClass(cls):
        if HAS_BPY:
            import MoziToolKit.ui as ui
            import MoziToolKit.ui.panel_biome
            try:
                ui.panel_biome.unregister()
            except Exception:
                pass

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_atlas_chunk_material_construction_in_blender(self):
        try:
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
                self.assertIn("Principled BSDF", node_names)
                self.assertNotIn("LabPBR Decoder", node_names)
                self.assertNotIn("Attr Material Props", node_names)
        finally:
            if "MTK:Atlas:blocks:001" in bpy.data.materials:
                bpy.data.materials.remove(bpy.data.materials["MTK:Atlas:blocks:001"])
            if "blocks_chunk_001.png" in bpy.data.images:
                bpy.data.images.remove(bpy.data.images["blocks_chunk_001.png"])

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_atlas_chunk_material_with_overlay_in_blender(self):
        try:
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
                )

                self.assertIsNotNone(mat)
                self.assertEqual(mat.name, "MTK:Atlas:blocks:001")
                self.assertTrue(mat["mtk_has_overlay"])

                node_names = [n.name for n in mat.node_tree.nodes]
                self.assertIn("Atlas Albedo Texture", node_names)
                self.assertIn("Atlas Overlay Texture", node_names)
                self.assertIn("MC Biome Tint", node_names)
                self.assertIn("MC Biome Colormap Decoder", node_names)
                self.assertIn("Colormap Grass", node_names)
                self.assertIn("Principled BSDF", node_names)
                self.assertNotIn("LabPBR Decoder", node_names)

                cm_grass_node = mat.node_tree.nodes["Colormap Grass"]
                self.assertEqual(cm_grass_node.interpolation, "Linear")
                self.assertEqual(cm_grass_node.extension, "EXTEND")
        finally:
            if "MTK:Atlas:blocks:001" in bpy.data.materials:
                bpy.data.materials.remove(bpy.data.materials["MTK:Atlas:blocks:001"])
            for img_n in ("blocks_chunk_001.png", "blocks_chunk_001_overlay.png", "grass.png"):
                if img_n in bpy.data.images:
                    bpy.data.images.remove(bpy.data.images[img_n])

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
        self.addCleanup(lambda: bpy.data.objects.remove(obj, do_unlink=True) if obj.name in bpy.data.objects else None)
        self.addCleanup(lambda: bpy.data.materials.remove(src_mat) if src_mat.name in bpy.data.materials else None)
        self.addCleanup(
            lambda: bpy.data.materials.remove(bpy.data.materials["MTK:Atlas:Ext:blocks:001"])
            if "MTK:Atlas:Ext:blocks:001" in bpy.data.materials
            else None
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            atlas_dir = cache_dir / "atlas"
            colormaps_dir = cache_dir / "colormaps"
            atlas_dir.mkdir(parents=True, exist_ok=True)
            colormaps_dir.mkdir(parents=True, exist_ok=True)

            _write_dummy_png(atlas_dir / "blocks_chunk_001.png")
            _write_dummy_png(colormaps_dir / "grass.png")
            _write_dummy_png(colormaps_dir / "foliage.png")

            # Create .mtkcache package
            from MoziToolKit.bridge.engine import get_libmtk
            mtk = get_libmtk()
            testing = getattr(getattr(mtk, "unstable", None), "testing", None) if mtk else None
            if testing is not None and hasattr(testing, "create_test_cache_package"):
                testing.create_test_cache_package(str(cache_dir / "abc123stackfp.mtkcache"), "abc123stackfp", 0)

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

            # Mock get_cache_dir and MOZI_CACHE_DIR to return our temporary test cache
            with patch.dict(os.environ, {"MOZI_CACHE_DIR": str(cache_dir)}), patch("MoziToolKit.utils.materials.pipeline.get_cache_dir", return_value=cache_dir):
                # 1. Replace Materials (Atlas Mode)
                res = replace_materials(obj, mode="ATLAS", origin="AUTO", biome="BADLANDS")
                self.assertTrue(res["success"])
                self.assertEqual(res["face_count"], len(mesh.polygons))
                self.assertIn("mtk_source_texture_idx", mesh.attributes)
                self.assertIn("mtk_source_textures", mesh)
                self.assertIn("mtk_atlas_chunk_id", mesh.attributes)
                self.assertIn("mtk_uv_transform", mesh.attributes)
                self.assertIn(ATTR_BIOME_TINT_DATA, mesh.attributes)
                self.assertIn(ATTR_BIOME_TINT_COLOR, mesh.attributes)
                self.assertIn(ATTR_COLORMAP_UV, mesh.attributes)
                self.assertNotIn("mtk_material_props", mesh.attributes)
                self.assertEqual(mesh.materials[0].name, "MTK:Atlas:Ext:blocks:001")
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
                self.assertEqual(mesh.materials[0].name, "MTK:Atlas:Ext:blocks:001")
                self.assertEqual(mesh.materials[0]["mtk_stack_fingerprint"], "abc123stackfp")
                self.assertIn(ATTR_BIOME_TINT_DATA, mesh.attributes)



    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_multi_uv_atlas_layer_roundtrip(self):
        """Local UVs stay untouched; atlas UVs live in MTK_Atlas and are reused when the layout is unchanged."""
        bpy.ops.mesh.primitive_cube_add(size=2.0)
        obj = bpy.context.active_object
        mesh = obj.data
        uv_layer = mesh.uv_layers.get("UVMap") or mesh.uv_layers.active or mesh.uv_layers.new(name="UVMap")
        uv_layer.name = "UVMap"
        for loop in uv_layer.data:
            loop.uv = (0.25, 0.75)
        local_before = _read_loop_uvs(uv_layer)

        src_mat = bpy.data.materials.new(name="mtk:minecraft:block/stone:0badf00d")
        mesh.materials.append(src_mat)
        self.addCleanup(lambda: bpy.data.objects.remove(obj, do_unlink=True) if obj.name in bpy.data.objects else None)
        self.addCleanup(lambda: bpy.data.materials.remove(src_mat) if src_mat.name in bpy.data.materials else None)
        for atlmat_name in ("MTK:Atlas:Ext:blocks:001", "MTK:Atlas:Ext:anim:blocks:001"):
            self.addCleanup(
                lambda n=atlmat_name: bpy.data.materials.remove(bpy.data.materials[n])
                if n in bpy.data.materials
                else None
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            atlas_dir = cache_dir / "atlas"
            colormaps_dir = cache_dir / "colormaps"
            atlas_dir.mkdir(parents=True, exist_ok=True)
            colormaps_dir.mkdir(parents=True, exist_ok=True)
            _write_dummy_png(atlas_dir / "blocks_chunk_001.png")
            _write_dummy_png(colormaps_dir / "grass.png")

            from MoziToolKit.bridge.engine import get_libmtk
            mtk = get_libmtk()
            testing = getattr(getattr(mtk, "unstable", None), "testing", None) if mtk else None
            if testing is not None and hasattr(testing, "create_test_cache_package"):
                testing.create_test_cache_package(str(cache_dir / "multiuvfp.mtkcache"), "multiuvfp", 0)

            atlas_mapping = {
                "chunks": [{
                    "chunk_id": 0, "category": "blocks", "is_animated": False,
                    "category_chunk_index": 1, "width": 64, "height": 64,
                    "has_normal": False, "has_specular": False,
                }],
                "sprites": {
                    "minecraft:block/stone": {
                        "chunk_id": 0, "category": "blocks", "is_animated": False,
                        "texture_id": 1,
                        "uv_bounds": [0.0, 0.0, 0.25, 0.25],
                        "frame_0_uv_bounds": [0.0, 0.0, 0.25, 0.25],
                        "local_uv_bounds": [0.0, 0.0, 1.0, 1.0],
                        "pixel_rect": [0, 0, 16, 16],
                        "frame_size": [16, 16],
                        "frame_count": 1,
                        "has_normal": False, "has_specular": False,
                    }
                },
            }
            (atlas_dir / "atlas_mapping.json").write_text(json.dumps(atlas_mapping), encoding="utf-8")

            with patch.dict(os.environ, {"MOZI_CACHE_DIR": str(cache_dir)}), \
                 patch("MoziToolKit.utils.materials.pipeline.get_cache_dir", return_value=cache_dir):
                res = replace_materials(obj, mode="ATLAS", origin="AUTO", biome="PLAINS")
                self.assertTrue(res["success"])
                self.assertFalse(res["reused_atlas_uvs"])

                mesh = obj.data
                self.assertEqual([layer.name for layer in mesh.uv_layers], ["UVMap", "MTK_Atlas"])
                self.assertEqual(mesh.uv_layers.active.name, "MTK_Atlas")
                self.assertEqual(mesh["mtk:local_uv_layer"], "UVMap")
                self.assertEqual(mesh["mtk:atlas_uv_layer"], "MTK_Atlas")
                self.assertTrue(mesh.get("mtk:atlas_layout_hash"))
                self.assertEqual(_read_loop_uvs(mesh.uv_layers["UVMap"]), local_before)

                atlas_uvs = [tuple(loop.uv) for loop in mesh.uv_layers["MTK_Atlas"].data]
                self.assertTrue(all(0.0 <= u <= 0.25 and 0.0 <= v <= 0.25 for u, v in atlas_uvs))
                self.assertNotEqual(atlas_uvs[0], (0.25, 0.75))

                atlas_mat = mesh.materials[0]
                uv_nodes = [node for node in atlas_mat.node_tree.nodes if node.type == "UVMAP"]
                self.assertEqual(len(uv_nodes), 1)
                self.assertEqual(uv_nodes[0].uv_map, "MTK_Atlas")
                self.assertEqual(atlas_mat["mtk_uv_map_name"], "MTK_Atlas")

                # Same atlas layout: reuse the atlas map and only rebind materials.
                res_reuse = replace_materials(obj, mode="ATLAS", origin="AUTO", biome="PLAINS")
                self.assertTrue(res_reuse.get("reused_atlas_uvs"))
                self.assertEqual(_read_loop_uvs(obj.data.uv_layers["UVMap"]), local_before)

                # Forced remap: re-project from local UVs, local layer still untouched.
                res_force = replace_materials(
                    obj, mode="ATLAS", origin="AUTO", biome="PLAINS", force_remap=True
                )
                self.assertFalse(res_force.get("reused_atlas_uvs"))
                self.assertEqual(_read_loop_uvs(obj.data.uv_layers["UVMap"]), local_before)

                # Layout change: never reuse the old atlas UVs.
                with patch(
                    "MoziToolKit.utils.materials.pipeline.compute_atlas_layout_hash",
                    return_value="v1:layout-changed",
                ):
                    res_changed = replace_materials(obj, mode="ATLAS", origin="AUTO", biome="PLAINS")
                self.assertFalse(res_changed.get("reused_atlas_uvs"))
                self.assertEqual(_read_loop_uvs(obj.data.uv_layers["UVMap"]), local_before)
                self.assertEqual(obj.data["mtk:atlas_layout_hash"], "v1:layout-changed")

    def test_material_props_memoryview_is_flat_f32_buffer(self):
        """Rust-owned material props memoryview must expose exactly len(keys) * 4 floats."""
        from MoziToolKit.bridge.material import compute_flat_material_props_buffer
        from MoziToolKit.utils.materials.properties_config import load_material_properties_config
        import numpy as np

        # Do not depend on test order or on whichever registry state a previous
        # case left behind: production registers this file on add-on startup.
        self.assertTrue(load_material_properties_config())

        keys = ["minecraft:block/glowstone", "minecraft:block/stone"]
        buf = compute_flat_material_props_buffer(keys)
        arr = np.frombuffer(buf, dtype=np.float32)
        self.assertEqual(arr.size, len(keys) * 4)
        # Glowstone emission is expected to be non-zero; stone is zero.
        self.assertGreater(float(arr[0]), 0.0)
        self.assertEqual(float(arr[4]), 0.0)

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_secondary_replacement_with_hashed_mtk_materials(self):
        # Create a test cube in Blender with hashed MTK material (mimicking previously processed map)
        bpy.ops.mesh.primitive_cube_add(size=2.0)
        obj = bpy.context.active_object
        self.assertIsNotNone(obj)
        mesh = obj.data

        hashed_mat = bpy.data.materials.new(name="mtk:minecraft:grass_block_top:8d09ec43b668")
        mesh.materials.append(hashed_mat)
        self.addCleanup(lambda: bpy.data.objects.remove(obj, do_unlink=True) if obj.name in bpy.data.objects else None)
        self.addCleanup(lambda: bpy.data.materials.remove(hashed_mat) if hashed_mat.name in bpy.data.materials else None)
        self.addCleanup(
            lambda: bpy.data.materials.remove(bpy.data.materials["MTK:Atlas:Ext:blocks:001"])
            if "MTK:Atlas:Ext:blocks:001" in bpy.data.materials
            else None
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            atlas_dir = cache_dir / "atlas"
            colormaps_dir = cache_dir / "colormaps"
            atlas_dir.mkdir(parents=True, exist_ok=True)
            colormaps_dir.mkdir(parents=True, exist_ok=True)

            _write_dummy_png(atlas_dir / "blocks_chunk_001.png")
            _write_dummy_png(colormaps_dir / "grass.png")

            from MoziToolKit.bridge.engine import get_libmtk
            mtk = get_libmtk()
            testing = getattr(getattr(mtk, "unstable", None), "testing", None) if mtk else None
            if testing is not None and hasattr(testing, "create_test_cache_package"):
                testing.create_test_cache_package(str(cache_dir / "xyz987stackfp.mtkcache"), "xyz987stackfp", 0)

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

            with patch.dict(os.environ, {"MOZI_CACHE_DIR": str(cache_dir)}), patch("MoziToolKit.utils.materials.pipeline.get_cache_dir", return_value=cache_dir):
                # 1. Replace Materials in ATLAS mode from hashed MTK material name
                res_atlas = replace_materials(obj, mode="ATLAS", origin="AUTO", biome="PLAINS")
                self.assertTrue(res_atlas["success"])
                self.assertEqual(res_atlas["unmapped_faces"], 0)
                self.assertIn(ATTR_BIOME_TINT_DATA, mesh.attributes)

                # 2. Update to Custom Biome with custom green tint
                obj.mtk_biome_use_custom_grass = True
                obj.mtk_biome_grass_color = (0.0, 1.0, 0.0, 1.0)
                up_res = update_object_biome(obj, "CUSTOM")
                self.assertTrue(up_res)

                # Check attribute on face
                tint_cols = [list(d.color) for d in mesh.attributes[ATTR_BIOME_TINT_COLOR].data]
                self.assertEqual(tint_cols[0], [0.0, 1.0, 0.0, 1.0])

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_memory_image_pixel_orientation_matches_blender_convention(self):
        """
        Verify that in-memory image streaming via get_or_create_image_from_rgba
        vertically flips incoming top-to-bottom RGBA buffers to align with
        Blender's bottom-to-top img.pixels layout, matching bpy.data.images.load identically.
        """
        import struct
        import zlib
        from MoziToolKit.utils.materials.builder.image_utils import get_or_create_image_from_rgba, get_or_create_image

        def make_png(width, height, raw_rgba):
            line_bytes = width * 4
            raw_data = bytearray()
            for y in range(height):
                raw_data.append(0)
                raw_data.extend(raw_rgba[y * line_bytes : (y + 1) * line_bytes])
            compressed = zlib.compress(bytes(raw_data))

            def chunk(tag, data):
                return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

            header = b"\x89PNG\r\n\x1a\n"
            ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            idat = chunk(b"IDAT", compressed)
            iend = chunk(b"IEND", b"")
            return header + ihdr + idat + iend

        # 2x2 image:
        # Row 0 (Top): Red [255, 0, 0, 255]
        # Row 1 (Bottom): Blue [0, 0, 255, 255]
        top_row = bytes([255, 0, 0, 255, 255, 0, 0, 255])
        bot_row = bytes([0, 0, 255, 255, 0, 0, 255, 255])
        raw_rgba = top_row + bot_row

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_png = Path(tmpdir) / "test_orientation.png"
            tmp_png.write_bytes(make_png(2, 2, raw_rgba))

            file_img = bpy.data.images.load(str(tmp_png))
            file_pixels = list(file_img.pixels)

            mem_img = get_or_create_image_from_rgba("MTK_Test_Orientation_Mem", 2, 2, raw_rgba, force_reload=True)
            self.assertIsNotNone(mem_img)
            mem_pixels = list(mem_img.pixels)

            # 1. Blender row 0 (bottom row, V=0.0) must be Blue (bottom of image)
            self.assertAlmostEqual(mem_pixels[0], 0.0, places=2)
            self.assertAlmostEqual(mem_pixels[1], 0.0, places=2)
            self.assertAlmostEqual(mem_pixels[2], 1.0, places=2)

            # 2. Blender row 1 (top row, V=1.0) must be Red (top of image)
            self.assertAlmostEqual(mem_pixels[8], 1.0, places=2)
            self.assertAlmostEqual(mem_pixels[9], 0.0, places=2)
            self.assertAlmostEqual(mem_pixels[10], 0.0, places=2)

            # 3. Must match Blender's native image load 100%
            for fp, mp in zip(file_pixels, mem_pixels):
                self.assertAlmostEqual(fp, mp, places=4)

            # Cleanup
            bpy.data.images.remove(file_img)
            bpy.data.images.remove(mem_img)

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_f32_memory_image_pixel_orientation_matches_blender_convention(self):
        """
        Verify that direct float32 streaming via get_or_create_image_from_f32
        streams bottom-to-top pixels directly into Blender matching bpy.data.images.load.
        """
        import struct
        import zlib
        from MoziToolKit.utils.materials.builder.image_utils import get_or_create_image_from_f32

        def make_png(width, height, raw_rgba):
            line_bytes = width * 4
            raw_data = bytearray()
            for y in range(height):
                raw_data.append(0)
                raw_data.extend(raw_rgba[y * line_bytes : (y + 1) * line_bytes])
            compressed = zlib.compress(bytes(raw_data))

            def chunk(tag, data):
                return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

            header = b"\x89PNG\r\n\x1a\n"
            ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            idat = chunk(b"IDAT", compressed)
            iend = chunk(b"IEND", b"")
            return header + ihdr + idat + iend

        top_row = bytes([255, 0, 0, 255, 255, 0, 0, 255])
        bot_row = bytes([0, 0, 255, 255, 0, 0, 255, 255])
        raw_rgba = top_row + bot_row

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_png = Path(tmpdir) / "test_orientation_f32.png"
            tmp_png.write_bytes(make_png(2, 2, raw_rgba))

            file_img = bpy.data.images.load(str(tmp_png))
            file_pixels = list(file_img.pixels)

            # In Rust, to_f32_buffer(flip_v=True) puts bottom row (Blue) first, then top row (Red)
            f32_data = struct.pack(
                "<16f",
                0.0, 0.0, 1.0, 1.0,  0.0, 0.0, 1.0, 1.0, # Bottom row
                1.0, 0.0, 0.0, 1.0,  1.0, 0.0, 0.0, 1.0, # Top row
            )
            f32_img = get_or_create_image_from_f32("MTK_Test_Orientation_F32", 2, 2, f32_data, force_reload=True)
            self.assertIsNotNone(f32_img)
            f32_pixels = list(f32_img.pixels)

            for fp, mp in zip(file_pixels, f32_pixels):
                self.assertAlmostEqual(fp, mp, places=4)

            bpy.data.images.remove(file_img)
            bpy.data.images.remove(f32_img)

    def test_pipeline_exports_and_constants(self):
        """The pipeline no longer exposes the removed mtk_material_props contract."""
        import MoziToolKit.utils.materials.pipeline as pipe
        self.assertFalse(hasattr(pipe, "ATTR_MATERIAL_PROPS"))
        self.assertTrue(hasattr(pipe, "get_or_load_biome_resolver"))
        self.assertTrue(hasattr(pipe, "compute_biome_tint_attributes"))
        self.assertTrue(hasattr(pipe, "apply_biome_tint_attributes"))

    def test_extract_face_material_palette_context(self):
        """Verify extract_face_material_palette_context builds palette via bridge."""
        from MoziToolKit.utils.materials.pipeline import extract_face_material_palette_context
        import numpy as np

        mesh = MagicMock()
        class Polys:
            def __len__(self): return 2
            def foreach_get(self, attr, buf):
                if attr == "material_index":
                    buf[:] = [0, 1]
                elif attr == "loop_start":
                    buf[:] = [0, 4]
                elif attr == "loop_total":
                    buf[:] = [4, 4]
        mesh.polygons = Polys()
        class Loops:
            def __len__(self): return 8
        mesh.loops = Loops()

        slot0 = MagicMock()
        slot0.name = "minecraft:stone"
        slot0.get.return_value = ""
        slot1 = MagicMock()
        slot1.name = "minecraft:dirt"
        slot1.get.return_value = ""
        mesh.materials = [slot0, slot1]
        mesh.uv_layers = MagicMock()
        mesh.attributes = {}

        palette, indices, face_loop_ranges, loop_uvs, uv_layer, existing_key_palette, existing_key_indices = (
            extract_face_material_palette_context(mesh)
        )
        self.assertEqual(palette, ["minecraft:stone", "minecraft:dirt"])
        self.assertEqual(list(indices), [0, 1])
        self.assertEqual(face_loop_ranges, [(0, 4), (4, 4)])


if __name__ == "__main__":
    if "--" in sys.argv:
        argv = [sys.argv[0]] + sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = [sys.argv[0]]
    unittest.main(argv=argv)


