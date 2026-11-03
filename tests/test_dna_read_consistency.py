"""
Tests for DNA Direct Read/Write Consistency between Fast-Path and Safe-Path.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
dev_lib_path = PROJECT_DIR / "dev" / "lib"
libmtk_release_path = PROJECT_DIR.parent / "libmozitoolkit" / "target" / "release"

for p in [str(dev_lib_path), str(libmtk_release_path), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

if "bpy" not in sys.modules:
    sys.modules["bpy"] = MagicMock()
if "mathutils" not in sys.modules:
    sys.modules["mathutils"] = MagicMock()

import bpy

HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "meshes")

from MoziToolKit.bridge.dna import is_dna_available, is_dna_enabled
from MoziToolKit.bridge.mesh import extract_mesh_data, extract_mesh_data_dna, inject_mesh_data
from MoziToolKit.bridge.mesh.dna import (
    inject_face_materials_dna,
    inject_topology_dna,
)
from MoziToolKit.bridge.point_cloud import (
    extract_voxel_point_cloud,
    inject_voxel_point_cloud,
)


class TestDnaReadWriteConsistency(unittest.TestCase):
    def setUp(self):
        if not HAS_BPY:
            self.skipTest("Requires real Blender host environment (bpy)")

    def _create_grid_mesh(self, num_x: int = 10, num_y: int = 10):
        """Creates a grid mesh of quads in Blender."""
        mesh = bpy.data.meshes.new(f"test_grid_{num_x}x{num_y}")
        v_count = (num_x + 1) * (num_y + 1)
        poly_count = num_x * num_y
        loop_count = poly_count * 4

        mesh.vertices.add(v_count)
        mesh.loops.add(loop_count)
        mesh.polygons.add(poly_count)

        # Generate vertex positions
        coords = []
        for y in range(num_y + 1):
            for x in range(num_x + 1):
                coords.extend([float(x), float(y), 0.0])
        mesh.vertices.foreach_set("co", np.array(coords, dtype=np.float32))

        # Generate loop vertices and UVs
        loop_verts = []
        loop_uvs = []
        for y in range(num_y):
            for x in range(num_x):
                v0 = y * (num_x + 1) + x
                v1 = v0 + 1
                v2 = (y + 1) * (num_x + 1) + x + 1
                v3 = (y + 1) * (num_x + 1) + x
                loop_verts.extend([v0, v1, v2, v3])
                loop_uvs.extend([0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0])

        mesh.loops.foreach_set("vertex_index", np.array(loop_verts, dtype=np.uint32))

        # Setup polygon offsets first so face topology is valid for UV/attribute layers
        offsets = np.arange(0, loop_count + 4, 4, dtype=np.int32)
        mesh.polygons.foreach_set("loop_start", offsets[:-1])
        mesh.polygons.foreach_set("loop_total", np.full(poly_count, 4, dtype=np.int32))

        # Setup UV layer
        uv_layer = mesh.uv_layers.new(name="UVMap")
        uv_layer.data.foreach_set("uv", np.array(loop_uvs, dtype=np.float32))

        # Setup material indices
        mat_attr = mesh.attributes.new(name="material_index", type="INT", domain="FACE")
        mat_indices = np.arange(poly_count, dtype=np.int32) % 5
        mat_attr.data.foreach_set("value", mat_indices)

        # Setup custom float attribute
        custom_attr = mesh.attributes.new(name="test_custom", type="FLOAT", domain="POINT")
        custom_attr.data.foreach_set("value", np.linspace(0.0, 1.0, v_count, dtype=np.float32))

        mesh.update()
        return mesh

    def test_mesh_fast_path_vs_safe_path_bit_exact(self):
        """Verifies extract_mesh_data via Fast-Path and Safe-Path produce bit-exact geometry."""
        mesh = self._create_grid_mesh(20, 20)  # 400 faces, 441 vertices
        try:
            # Safe-Path (official foreach_get)
            mesh_safe = extract_mesh_data(mesh, use_dna=False)
            self.assertIsNotNone(mesh_safe)
            self.assertEqual(mesh_safe.face_count, 400)
            self.assertEqual(mesh_safe.vertex_count, 441)

            # Fast-Path (DNA direct read)
            mesh_fast = extract_mesh_data(mesh, use_dna=True)
            self.assertIsNotNone(mesh_fast)
            self.assertEqual(mesh_fast.face_count, 400)
            self.assertEqual(mesh_fast.vertex_count, 441)

            # Compare vertex counts and topology
            self.assertEqual(mesh_fast.triangle_count, mesh_safe.triangle_count)
            self.assertEqual(mesh_fast.quad_count, mesh_safe.quad_count)

            # Compare positions (bit-level exact)
            pos_fast = np.frombuffer(mesh_fast.positions_memoryview(), dtype=np.float32)
            pos_safe = np.frombuffer(mesh_safe.positions_memoryview(), dtype=np.float32)
            np.testing.assert_array_equal(pos_fast, pos_safe)

            # Compare loop UVs
            uv_fast = np.frombuffer(mesh_fast.loop_uvs_memoryview(), dtype=np.float32)
            uv_safe = np.frombuffer(mesh_safe.loop_uvs_memoryview(), dtype=np.float32)
            np.testing.assert_array_equal(uv_fast, uv_safe)

            # Compare triangle indices
            idx_fast = np.frombuffer(mesh_fast.indices_memoryview(), dtype=np.uint32)
            idx_safe = np.frombuffer(mesh_safe.indices_memoryview(), dtype=np.uint32)
            np.testing.assert_array_equal(idx_fast, idx_safe)

            # Compare quad indices
            q_fast = np.frombuffer(mesh_fast.quad_indices_memoryview(), dtype=np.uint32)
            q_safe = np.frombuffer(mesh_safe.quad_indices_memoryview(), dtype=np.uint32)
            np.testing.assert_array_equal(q_fast, q_safe)

            # Compare face materials
            mats_fast = np.frombuffer(mesh_fast.face_materials_memoryview(), dtype=np.uint16)
            mats_safe = np.frombuffer(mesh_safe.face_materials_memoryview(), dtype=np.uint16)
            np.testing.assert_array_equal(mats_fast, mats_safe)

            # Compare custom attribute
            attr_fast = np.frombuffer(mesh_fast.attribute_memoryview("test_custom"), dtype=np.float32)
            attr_safe = np.frombuffer(mesh_safe.attribute_memoryview("test_custom"), dtype=np.float32)
            np.testing.assert_array_equal(attr_fast, attr_safe)
        finally:
            bpy.data.meshes.remove(mesh)

    def test_inject_topology_dna_offset_write(self):
        """Verifies inject_topology_dna direct write of face_offset_indices produces valid mesh."""
        mesh = bpy.data.meshes.new("test_inject_topo")
        try:
            # Create a source mesh data using safe path
            src_mesh = self._create_grid_mesh(10, 10)
            mesh_data = extract_mesh_data(src_mesh, use_dna=False)
            bpy.data.meshes.remove(src_mesh)

            # Inject topology via inject_topology_dna
            v_count = mesh_data.vertex_count
            total_indices = mesh_data.triangle_count * 3
            success = inject_topology_dna(mesh, mesh_data, v_count, is_quad=True, total_indices=total_indices)
            self.assertTrue(success)

            mesh.update(calc_edges=True)
            # Blender validate() returns True if mesh is invalid, False if valid (0 errors)
            is_invalid = mesh.validate()
            self.assertFalse(is_invalid)
            self.assertEqual(len(mesh.polygons), 100)
            self.assertEqual(len(mesh.vertices), 121)
            self.assertEqual(mesh.polygons[0].loop_total, 4)
            self.assertEqual(mesh.polygons[1].loop_start, 4)
        finally:
            bpy.data.meshes.remove(mesh)

    def test_inject_face_materials_dna(self):
        """Verifies inject_face_materials_dna directly writes material_index attribute."""
        mesh = self._create_grid_mesh(5, 5)
        try:
            mesh_data = extract_mesh_data(mesh, use_dna=False)

            # Clear material indices
            mat_attr = mesh.attributes.get("material_index")
            if mat_attr:
                mat_attr.data.foreach_set("value", np.zeros(25, dtype=np.int32))

            # Direct inject via DNA
            success = inject_face_materials_dna(mesh, mesh_data)
            self.assertTrue(success)

            # Verify in Blender
            res = np.empty(25, dtype=np.int32)
            mesh.polygons.foreach_get("material_index", res)
            expected = np.arange(25, dtype=np.int32) % 5
            np.testing.assert_array_equal(res, expected)
        finally:
            bpy.data.meshes.remove(mesh)


    def test_point_cloud_fast_path_vs_safe_path_bit_exact(self):
        """Verifies extract_voxel_point_cloud Fast-Path and Safe-Path produce identical point clouds."""
        mesh = bpy.data.meshes.new("test_point_cloud")
        try:
            pt_count = 50
            mesh.vertices.add(pt_count)

            # Positions
            pos = np.linspace(-10.0, 10.0, pt_count * 3, dtype=np.float32)
            mesh.vertices.foreach_set("co", pos)

            # Attributes
            ax = mesh.attributes.new(name="mtk_block_x", type="INT", domain="POINT")
            ay = mesh.attributes.new(name="mtk_block_y", type="INT", domain="POINT")
            az = mesh.attributes.new(name="mtk_block_z", type="INT", domain="POINT")
            ast = mesh.attributes.new(name="mtk_state_idx", type="INT", domain="POINT")
            abm = mesh.attributes.new(name="mtk_biome_idx", type="INT", domain="POINT")
            aent = mesh.attributes.new(name="mtk_entity_idx", type="INT", domain="POINT")

            ax.data.foreach_set("value", np.arange(pt_count, dtype=np.int32))
            ay.data.foreach_set("value", np.arange(pt_count, dtype=np.int32) * 2)
            az.data.foreach_set("value", np.arange(pt_count, dtype=np.int32) * 3)
            ast.data.foreach_set("value", np.arange(pt_count, dtype=np.int32) % 3)
            abm.data.foreach_set("value", np.arange(pt_count, dtype=np.int32) % 2)
            aent.data.foreach_set("value", np.full(pt_count, -1, dtype=np.int32))

            mesh["mtk_palette"] = ["minecraft:stone", "minecraft:dirt", "minecraft:glass"]
            mesh["mtk_biome_palette"] = ["minecraft:plains", "minecraft:desert"]
            mesh["mtk_entity_palette"] = []

            # 1. Safe-Path extraction
            cloud_safe = extract_voxel_point_cloud(mesh, use_dna=False)
            self.assertIsNotNone(cloud_safe)
            self.assertEqual(len(cloud_safe), pt_count)

            # 2. Fast-Path extraction
            cloud_fast = extract_voxel_point_cloud(mesh, use_dna=True)
            self.assertIsNotNone(cloud_fast)
            self.assertEqual(len(cloud_fast), pt_count)

            # 3. Bit-exact comparisons
            np.testing.assert_array_equal(
                np.frombuffer(cloud_fast.positions_memoryview(), dtype=np.float32),
                np.frombuffer(cloud_safe.positions_memoryview(), dtype=np.float32),
            )
            np.testing.assert_array_equal(
                np.frombuffer(cloud_fast.block_x_memoryview(), dtype=np.int32),
                np.frombuffer(cloud_safe.block_x_memoryview(), dtype=np.int32),
            )
            np.testing.assert_array_equal(
                np.frombuffer(cloud_fast.block_y_memoryview(), dtype=np.int32),
                np.frombuffer(cloud_safe.block_y_memoryview(), dtype=np.int32),
            )
            np.testing.assert_array_equal(
                np.frombuffer(cloud_fast.block_z_memoryview(), dtype=np.int32),
                np.frombuffer(cloud_safe.block_z_memoryview(), dtype=np.int32),
            )
            np.testing.assert_array_equal(
                np.frombuffer(cloud_fast.state_indices_memoryview(), dtype=np.int32),
                np.frombuffer(cloud_safe.state_indices_memoryview(), dtype=np.int32),
            )
            np.testing.assert_array_equal(
                np.frombuffer(cloud_fast.biome_indices_memoryview(), dtype=np.int32),
                np.frombuffer(cloud_safe.biome_indices_memoryview(), dtype=np.int32),
            )
            self.assertEqual(cloud_fast.get_state_palette(), cloud_safe.get_state_palette())
            self.assertEqual(cloud_fast.get_biome_palette(), cloud_safe.get_biome_palette())
        finally:
            bpy.data.meshes.remove(mesh)


if __name__ == "__main__":
    unittest.main()
