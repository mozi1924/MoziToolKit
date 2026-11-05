"""
Tests for MoziToolKit Bridge and Material Presets.
"""

import _mesh_arrays as ma
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import array
import ctypes
import numpy as np

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
libmtk_release_path = PROJECT_DIR.parent / "libmozitoolkit" / "target" / "release"

for p in [str(libmtk_release_path), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import bpy
import bmesh
import mathutils

from MoziToolKit.bridge.engine import get_libmtk
from MoziToolKit.bridge.mesh import (
    BLENDER_TO_MTK_DOMAIN,
    BLENDER_TO_MTK_TYPE,
    MTK_TO_BLENDER_DOMAIN,
    MTK_TO_BLENDER_TYPE,
    extract_mesh_data,
    inject_mesh_data,
    resolve_source_texture_keys,
    inject_face_source_texture_keys,
)
from MoziToolKit.utils.materials.matching.presets.registry import (
    build_matching_context,
    build_material_alias_map,
    clean_mtk_material_name,
    detect_material_origin,
    generate_candidates_for_name,
)
from MoziToolKit.utils.materials.matching.presets.mineways import build_mineways_grid_spec
from MoziToolKit.utils.materials.matching.presets.mineways_table import MINEWAYS_TILES_TABLE


class TestMaterialPresets(unittest.TestCase):
    def test_mineways_table_integrity(self):
        self.assertGreater(len(MINEWAYS_TILES_TABLE), 1200)
        self.assertEqual(MINEWAYS_TILES_TABLE[0][2], "grass_block_top")
        self.assertEqual(MINEWAYS_TILES_TABLE[1][2], "stone")

    def test_mineways_spec_generation(self):
        spec = build_mineways_grid_spec()
        if isinstance(spec, dict):
            self.assertIn("swatch_size", spec)
            self.assertIn("tile_size", spec)
            self.assertIn("swatch_to_candidates", spec)
            self.assertEqual(spec["swatch_size"], 18.0)
            self.assertEqual(spec["tile_size"], 16.0)
            self.assertGreater(len(spec["swatch_to_candidates"]), 1200)
        else:
            self.assertEqual(spec.swatch_size, 18.0)
            self.assertEqual(spec.tile_size, 16.0)

    def test_preset_registry(self):
        self.assertEqual(detect_material_origin("mineways_stone"), "mineways")
        self.assertEqual(detect_material_origin("minecraft_block_stone"), "jmc2obj")
        self.assertEqual(detect_material_origin("ice_cube_dirt"), "ice_cube")
        self.assertEqual(detect_material_origin("mtk:minecraft:grass_block_top:8d09ec43b668"), "mtk")

        # Test clean_mtk_material_name
        self.assertEqual(clean_mtk_material_name("mtk:minecraft:bell_side:8d09ec43b668"), "minecraft:bell_side")
        self.assertEqual(clean_mtk_material_name("MTK:minecraft:grass_block_top:8d09ec43b668"), "minecraft:grass_block_top")

        # Test generate_candidates_for_name for MTK materials
        candidates = generate_candidates_for_name("mtk:minecraft:bell_side:8d09ec43b668")
        self.assertIn("minecraft:bell_side", candidates)
        self.assertIn("bell_side", candidates)
        self.assertIn("block/bell_side", candidates)
        self.assertIn("minecraft:block/bell_side", candidates)

        alias_map, grid_spec = build_matching_context(["mineways_stone"], origin="mineways")
        self.assertIn("mineways_stone", alias_map)
        self.assertIsNotNone(grid_spec)
        if isinstance(grid_spec, dict):
            self.assertEqual(grid_spec["swatch_size"], 18.0)
        else:
            self.assertEqual(grid_spec.swatch_size, 18.0)



    def test_real_mesh_update(self):
        mesh = bpy.data.meshes.new("TestMeshUpdate")
        mesh.from_pydata(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 0.0, 1.0)],
            [],
            [(0, 1, 2, 3)],
        )
        mesh.update()
        self.assertEqual(len(mesh.vertices), 4)
        self.assertEqual(len(mesh.polygons), 1)
        bpy.data.meshes.remove(mesh)

    def test_extract_mesh_data_quads(self):
        mesh = bpy.data.meshes.new("TestQuadMesh")
        mesh.from_pydata(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 0.0, 1.0)],
            [],
            [(0, 1, 2, 3)],
        )
        mesh.polygons[0].material_index = 1
        uv_layer = mesh.uv_layers.new(name="UVMap")
        uvs = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
        for i, uv in enumerate(uvs):
            uv_layer.data[i].uv = uv

        mesh_data = extract_mesh_data(mesh)
        self.assertEqual(mesh_data.vertex_count, 4)
        self.assertEqual(mesh_data.triangle_count, 2)
        indices = ma.indices(mesh_data)
        self.assertEqual(len(indices), 6)
        self.assertEqual(mesh_data.uv_layout, "per_loop")
        self.assertEqual(len(ma.loop_uvs(mesh_data)), 8)
        face_mats = ma.face_materials(mesh_data)
        self.assertEqual(len(face_mats), 1)
        self.assertEqual(face_mats[0], 1)
        bpy.data.meshes.remove(mesh)
        self.assertEqual(len(face_mats), 1)
        self.assertEqual(face_mats[0], 1)


class TestDualMeshApi(unittest.TestCase):
    """Verifies strict separation and functionality of Universal Python vs Blender Direct Pointer APIs."""

    def setUp(self):
        mtk = get_libmtk()
        if mtk is None or not hasattr(mtk, "MeshData"):
            self.skipTest("libmtk MeshData not available")
        self.mesh = ma.unit_quad()

    def test_universal_python_zero_copy_api(self):
        """Suite B: Universal Python memoryview & buffer protocol API."""
        pos_mv = self.mesh.positions_memoryview()
        self.assertIsInstance(pos_mv, memoryview)
        pos_arr = np.frombuffer(pos_mv, dtype=np.float32).reshape(-1, 3)
        self.assertEqual(len(pos_arr), 4)

        idx_mv = self.mesh.indices_memoryview()
        self.assertIsInstance(idx_mv, memoryview)
        idx_arr = np.frombuffer(idx_mv, dtype=np.uint32)
        self.assertEqual(len(idx_arr), 6)

        quad_mv = self.mesh.quad_indices_memoryview()
        self.assertIsNotNone(quad_mv)
        quad_arr = np.frombuffer(quad_mv, dtype=np.uint32)
        self.assertEqual(len(quad_arr), 4)

        uv_mv = self.mesh.uvs_memoryview()
        self.assertIsInstance(uv_mv, memoryview)

    def test_blender_direct_pointer_api(self):
        """Suite A: standalone Blender DNA adapter writes typed core views."""
        from MoziToolKit.bridge.engine import get_libmtk_dna

        dna = get_libmtk_dna()
        if dna is None or not hasattr(dna, "copy_f32"):
            self.skipTest("libmtk_blender_dna is not available")
        self.assertFalse(hasattr(self.mesh, "blender_direct"))

        buf = (ctypes.c_float * 12)()
        ptr = ctypes.addressof(buf)
        src = memoryview(self.mesh.positions_memoryview()).cast("B")
        written = dna.copy_f32(src, ptr, 12, max_bytes=48)
        self.assertEqual(written, 48)


    def test_source_texture_palette_indices(self):
        """Rust reads the canonical palette + u32 indices without per-face strings."""
        if not hasattr(self.mesh, "source_texture_palette_indices"):
            self.skipTest("source_texture_palette_indices not available in this libmtk build")
        mesh = ma.unit_quads(3)
        # Canonical provenance: Mesh-domain string palette + Face-domain Int32 indices.
        mesh.add_string_attribute(
            "mtk_source_textures", "mesh", ["minecraft:block/grass_block_top", "minecraft:block/dirt"]
        )
        mesh.add_attribute_from_buffer(
            "mtk_source_texture_idx", "face", "int32", np.array([0, 1, 0], dtype=np.int32)
        )

        palette, indices = mesh.source_texture_palette_indices()
        self.assertEqual(palette, ["minecraft:block/grass_block_top", "minecraft:block/dirt"])
        self.assertEqual(np.frombuffer(indices, dtype=np.uint32).tolist(), [0, 1, 0])

    def test_retired_source_texture_key_is_not_converted(self):
        """The retired per-face string layer must never be resurrected into provenance."""
        if not hasattr(self.mesh, "source_texture_palette_indices"):
            self.skipTest("source_texture_palette_indices not available in this libmtk build")
        mesh = ma.unit_quads(3)
        mesh.add_string_attribute(
            "mtk_source_texture_key",
            "face",
            ["minecraft:block/stone", "minecraft:block/dirt", "minecraft:block/stone"],
        )

        palette, indices = mesh.source_texture_palette_indices()
        self.assertEqual(palette, [])
        self.assertEqual(len(np.frombuffer(indices, dtype=np.uint32)), 0)


class TestPaletteSourceTextureKeys(unittest.TestCase):
    def test_resolve_from_palette_int(self):
        mesh = bpy.data.meshes.new("TestPaletteMesh")
        mesh.from_pydata(
            [(0,0,0),(1,0,0),(1,1,0),(0,1,0), (2,0,0),(3,0,0),(3,1,0),(2,1,0),
             (4,0,0),(5,0,0),(5,1,0),(4,1,0), (6,0,0),(7,0,0),(7,1,0),(6,1,0)],
            [],
            [(0,1,2,3), (4,5,6,7), (8,9,10,11), (12,13,14,15)],
        )
        try:
            attr = mesh.attributes.new(name="mtk_source_texture_idx", type="INT", domain="FACE")
            attr.data.foreach_set("value", [0, 1, 0, 2])
            mesh["mtk_source_textures"] = ["stone", "grass_block_top", "dirt"]

            resolved = resolve_source_texture_keys(mesh)
            self.assertEqual(resolved, ["stone", "grass_block_top", "stone", "dirt"])
        finally:
            bpy.data.meshes.remove(mesh)



class TestPaletteProvenanceParity(unittest.TestCase):
    """Save imports and Live Sync must expose identical palette provenance."""

    def test_skip_string_flag_does_not_change_provenance(self):
        keys = ["minecraft:block/grass_block_top", "minecraft:block/dirt"]
        palette = ["minecraft:block/grass_block_top", "minecraft:block/dirt"]
        idx = np.array([0, 1], dtype=np.int32)
        resolved_by_mode = {}
        for skip in (False, True):
            mesh_data = ma.unit_quads(2)
            # Canonical provenance only: the per-face string layer is retired.
            mesh_data.add_string_attribute("mtk_source_textures", "mesh", palette)
            mesh_data.add_attribute_from_buffer("mtk_source_texture_idx", "face", "int32", idx)

            name = f"mtk_palette_parity_{int(skip)}"
            b_mesh = bpy.data.meshes.new(name)
            obj = bpy.data.objects.new(name, b_mesh)
            bpy.context.scene.collection.objects.link(obj)
            try:
                inject_mesh_data(
                    mesh_data,
                    b_mesh,
                    update_topology=True,
                    update_normals=True,
                    skip_string_attributes=skip,
                )
                self.assertIn("mtk_source_textures", b_mesh)
                self.assertIn("mtk_source_texture_idx", b_mesh.attributes)
                self.assertNotIn("mtk_source_texture_key", b_mesh.attributes)
                resolved_by_mode[skip] = resolve_source_texture_keys(b_mesh)
            finally:
                bpy.data.objects.remove(obj, do_unlink=True)
                bpy.data.meshes.remove(b_mesh)

        self.assertEqual(resolved_by_mode[False], keys)
        self.assertEqual(resolved_by_mode[True], keys)


class TestColorAttributeInjection(unittest.TestCase):
    def test_inject_color_attributes_standard_sets_active_color(self):
        from MoziToolKit.bridge.mesh.standard import inject_color_attributes_standard

        mesh = bpy.data.meshes.new("test_color_attr_mesh")
        try:
            mesh.vertices.add(4)
            mesh.loops.add(4)
            mesh.polygons.add(1)
            colors_f32 = np.array([
                0.5, 0.2, 0.1, 1.0,
                0.5, 0.2, 0.1, 1.0,
                0.5, 0.2, 0.1, 1.0,
                0.5, 0.2, 0.1, 1.0,
            ], dtype=np.float32)

            mesh_data = SimpleNamespace(colors_memoryview=lambda: memoryview(colors_f32))
            inject_color_attributes_standard(mesh, mesh_data)

            self.assertIn("color", mesh.color_attributes)
            col_attr = mesh.color_attributes.get("color")
            self.assertIsNotNone(col_attr)
            self.assertEqual(mesh.color_attributes.active_color, col_attr)
            col_vals = [c for item in col_attr.data for c in item.color]
            self.assertEqual(len(col_vals), 16)
            self.assertAlmostEqual(col_vals[0], 0.5, places=5)
            self.assertAlmostEqual(col_vals[1], 0.2, places=5)
        finally:
            bpy.data.meshes.remove(mesh)

    def test_inject_color_attributes_dna_sets_active_color(self):
        from unittest.mock import MagicMock, patch
        from MoziToolKit.bridge.mesh.dna import inject_color_attributes_dna

        mesh = bpy.data.meshes.new("test_color_dna_mesh")
        try:
            mesh.vertices.add(4)
            mesh.loops.add(4)
            mesh.polygons.add(1)
            colors_f32 = np.array([
                0.5, 0.2, 0.1, 1.0,
                0.5, 0.2, 0.1, 1.0,
                0.5, 0.2, 0.1, 1.0,
                0.5, 0.2, 0.1, 1.0,
            ], dtype=np.float32)

            mesh_data = SimpleNamespace(colors_memoryview=lambda: memoryview(colors_f32))

            mock_dna = MagicMock()
            mock_dna.copy_f32.return_value = None

            with patch("MoziToolKit.bridge.mesh.dna.get_libmtk_dna", return_value=mock_dna), \
                 patch("MoziToolKit.bridge.mesh.dna.is_dna_enabled", return_value=True), \
                 patch("MoziToolKit.bridge.mesh.dna.resolve_colors_ptr", return_value=0x12345678):
                result = inject_color_attributes_dna(mesh, mesh_data)

            self.assertTrue(result)
            self.assertIn("color", mesh.color_attributes)
            col_attr = mesh.color_attributes.get("color")
            self.assertIsNotNone(col_attr)
            self.assertEqual(mesh.color_attributes.active_color, col_attr)
            mock_dna.copy_f32.assert_called_once()
        finally:
            bpy.data.meshes.remove(mesh)

    def test_inject_face_materials_standard_triangulated_quad_expansion(self):
        """Regression test: triangulated quad meshes should repeat face material slots across both triangles."""
        from MoziToolKit.bridge.mesh.standard import inject_face_materials_standard

        mesh = bpy.data.meshes.new("test_tri_mats")
        try:
            mesh.vertices.add(4)
            mesh.loops.add(6)
            mesh.polygons.add(2)
            mats_u16 = np.array([3], dtype=np.uint16)
            mesh_data = SimpleNamespace(face_materials_memoryview=lambda: memoryview(mats_u16))

            inject_face_materials_standard(mesh, mesh_data)
            slots = [p.material_index for p in mesh.polygons]
            self.assertEqual(slots, [3, 3])
        finally:
            bpy.data.meshes.remove(mesh)

    def test_inject_color_attributes_standard_triangulated_quad_expansion(self):
        """Regression test: triangulated quad meshes expand 4 quad corners to 6 triangle loop corners."""
        from MoziToolKit.bridge.mesh.standard import inject_color_attributes_standard

        mesh = bpy.data.meshes.new("test_tri_colors")
        try:
            mesh.vertices.add(4)
            mesh.loops.add(6)
            mesh.polygons.add(2)
            colors_f32 = np.array([
                1.0, 0.0, 0.0, 1.0,  # Corner 0
                0.0, 1.0, 0.0, 1.0,  # Corner 1
                0.0, 0.0, 1.0, 1.0,  # Corner 2
                1.0, 1.0, 0.0, 1.0,  # Corner 3
            ], dtype=np.float32)

            mesh_data = SimpleNamespace(colors_memoryview=lambda: memoryview(colors_f32))

            inject_color_attributes_standard(mesh, mesh_data)

            col_attr = mesh.color_attributes.get("color")
            self.assertIsNotNone(col_attr)
            col_vals = [c for item in col_attr.data for c in item.color]
            self.assertEqual(len(col_vals), 24)  # 6 corners * 4 floats
            # Tri 1: corners 0, 1, 2
            self.assertEqual(col_vals[0:4], [1.0, 0.0, 0.0, 1.0])
            self.assertEqual(col_vals[4:8], [0.0, 1.0, 0.0, 1.0])
            self.assertEqual(col_vals[8:12], [0.0, 0.0, 1.0, 1.0])
            # Tri 2: corners 0, 2, 3
            self.assertEqual(col_vals[12:16], [1.0, 0.0, 0.0, 1.0])
            self.assertEqual(col_vals[16:20], [0.0, 0.0, 1.0, 1.0])
            self.assertEqual(col_vals[20:24], [1.0, 1.0, 0.0, 1.0])
        finally:
            bpy.data.meshes.remove(mesh)


if __name__ == "__main__":
    if "--" in sys.argv:
        argv = [sys.argv[0]] + sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = [sys.argv[0]]
    unittest.main(argv=argv)

