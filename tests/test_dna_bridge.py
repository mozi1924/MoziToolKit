"""
Unit tests for the C++ DNA raw memory direct-access bridge and version detector.
Runs 100% inside real Blender host environment with native bpy data structures.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import bpy

from MoziToolKit.bridge.dna import (
    BaseDnaResolver,
    get_blender_version,
    get_dna_resolver,
    is_dna_available,
    is_dna_enabled,
    is_version_supported,
    resolve_attribute_ptr,
    resolve_colors_ptr,
    resolve_corner_verts_ptr,
    resolve_loop_uvs_ptr,
    resolve_materials_ptr,
    resolve_point_cloud_ptrs,
    resolve_positions_ptr,
    safe_as_pointer,
    set_dna_enabled,
)
from MoziToolKit.bridge.engine import get_libmtk_blender, has_libmtk_dna


class TestDnaBridge(unittest.TestCase):
    def setUp(self):
        set_dna_enabled(None)

    def tearDown(self):
        set_dna_enabled(None)

    def test_version_detection(self):
        ver = get_blender_version()
        self.assertIsInstance(ver, tuple)
        self.assertEqual(len(ver), 3)
        self.assertGreaterEqual(ver[0], 4)

    def test_is_version_supported(self):
        ver = get_blender_version()
        supported = is_version_supported()
        if ver[0] in (4, 5):
            self.assertTrue(supported)
        else:
            self.assertFalse(supported)

    def test_guard_safe_as_pointer(self):
        self.assertIsNone(safe_as_pointer(None))
        self.assertIsNone(safe_as_pointer("not_an_object"))

        # Object with invalid pointer return
        class BadPtr:
            def as_pointer(self):
                return 0

        self.assertIsNone(safe_as_pointer(BadPtr()))

        # Object with valid pointer return from real Blender mesh
        mesh = bpy.data.meshes.new("test_ptr")
        try:
            self.assertGreater(safe_as_pointer(mesh), 0)
        finally:
            bpy.data.meshes.remove(mesh)

        # Object throwing exception
        class DeadRna:
            def as_pointer(self):
                raise RuntimeError("Dead RNA reference")

        self.assertIsNone(safe_as_pointer(DeadRna()))

    def test_resolver_instance(self):
        resolver = get_dna_resolver()
        self.assertIsInstance(resolver, BaseDnaResolver)

    def test_resolver_with_real_mesh(self):
        """Validates DNA pointer resolvers against a real Blender mesh."""
        mesh = bpy.data.meshes.new("test_resolver_real_mesh")
        try:
            mesh.vertices.add(4)
            mesh.loops.add(4)
            mesh.polygons.add(1)
            mesh.uv_layers.new(name="UVMap")
            mesh.color_attributes.new("Color", "FLOAT_COLOR", "POINT")

            pos_ptr = resolve_positions_ptr(mesh, expected_count=4)
            self.assertIsNotNone(pos_ptr)
            self.assertGreater(pos_ptr, 0)

            # Mismatched count should safely return None
            self.assertIsNone(resolve_positions_ptr(mesh, expected_count=999))

            uv_ptr = resolve_loop_uvs_ptr(mesh, expected_count=4)
            self.assertIsNotNone(uv_ptr)
            self.assertGreater(uv_ptr, 0)

            col_ptr = resolve_colors_ptr(mesh, expected_count=4)
            self.assertIsNotNone(col_ptr)
            self.assertGreater(col_ptr, 0)
        finally:
            bpy.data.meshes.remove(mesh)

    def test_resolver_point_cloud_with_real_mesh(self):
        """Validates Point Cloud DNA pointer resolution against a real Blender mesh."""
        cloud = bpy.data.meshes.new("test_resolver_cloud")
        try:
            cloud.vertices.add(5)
            cloud.attributes.new("mtk_block_x", "INT", "POINT")
            cloud.attributes.new("mtk_block_y", "INT", "POINT")
            cloud.attributes.new("mtk_block_z", "INT", "POINT")
            cloud.attributes.new("mtk_state_idx", "INT", "POINT")
            cloud.attributes.new("mtk_biome_idx", "INT", "POINT")
            cloud.attributes.new("mtk_entity_idx", "INT", "POINT")
            cloud.attributes.new("mtk_light", "INT", "POINT")

            ptrs = resolve_point_cloud_ptrs(cloud, expected_count=5)
            self.assertIsNotNone(ptrs)
            self.assertIsNotNone(ptrs["pos_ptr"])
            self.assertIsNotNone(ptrs["block_x_ptr"])
            self.assertIsNotNone(ptrs["state_idx_ptr"])
            self.assertIsNotNone(ptrs["biome_idx_ptr"])
            self.assertIsNotNone(ptrs["entity_idx_ptr"])
            self.assertIsNotNone(ptrs["light_ptr"])
        finally:
            bpy.data.meshes.remove(cloud)

    def test_native_dna_module(self):
        if not has_libmtk_dna():
            self.skipTest("libmtk native DNA accelerator is not loaded")

        blender_dna = get_libmtk_blender()
        self.assertIsNotNone(blender_dna)
        self.assertEqual(blender_dna.api_version(), 2)
        self.assertTrue(hasattr(blender_dna, "copy_f32"))
        self.assertTrue(hasattr(blender_dna, "copy_u32"))

    def test_inject_custom_attribute_dna_zero_elements(self):
        from MoziToolKit.bridge.mesh.dna import inject_custom_attribute_dna

        mesh = bpy.data.meshes.new("test_zero_attr")
        try:
            attr = mesh.attributes.new("test_zero", "INT", "POINT")
            self.assertTrue(inject_custom_attribute_dna(attr, b"", "INT", 0))
        finally:
            bpy.data.meshes.remove(mesh)

    def test_dna_underlying_functions_respect_disabled_state(self):
        """Defense-in-depth: underlying inject_*_dna functions must refuse execution when DNA is disabled."""
        from MoziToolKit.bridge.mesh.dna import (
            inject_topology_dna,
            inject_vertex_positions_dna,
            inject_vertex_normals_dna,
            inject_uvs_dna,
            inject_color_attributes_dna,
            inject_custom_attribute_dna,
        )
        from MoziToolKit.bridge.point_cloud.dna import inject_point_cloud_dna

        mesh = bpy.data.meshes.new("test_dna_disabled")

        # Explicitly disable DNA
        set_dna_enabled(False)
        self.assertFalse(is_dna_enabled())

        try:
            self.assertFalse(inject_topology_dna(mesh, None, 4, False, 6))
            self.assertFalse(inject_vertex_positions_dna(mesh, None))
            self.assertFalse(inject_vertex_normals_dna(mesh, None))
            self.assertFalse(inject_uvs_dna(mesh, None))
            self.assertFalse(inject_color_attributes_dna(mesh, None))
            self.assertFalse(inject_custom_attribute_dna(mesh, b"1234", "INT", 1))
            self.assertFalse(inject_point_cloud_dna(mesh, None, 10))
        finally:
            bpy.data.meshes.remove(mesh)

    def test_custom_attribute_dna_in_blender(self):
        if not is_dna_available():
            self.skipTest("libmtk_blender_dna not available")

        import numpy as np
        from MoziToolKit.bridge.mesh.dna import inject_custom_attribute_dna

        mesh = bpy.data.meshes.new("dna_attr_test")
        mesh.vertices.add(4)
        mesh.polygons.add(2)
        try:
            attr_int = mesh.attributes.new("test_int", "INT", "POINT")
            int_buf = np.array([42, 43, 44, 45], dtype=np.int32).tobytes()
            ok = inject_custom_attribute_dna(attr_int, int_buf, "INT", 4)
            self.assertTrue(ok)
            self.assertEqual([x.value for x in attr_int.data], [42, 43, 44, 45])

            attr_float = mesh.attributes.new("test_float", "FLOAT", "POINT")
            float_buf = np.array([1.25, 2.5, 3.75, 5.0], dtype=np.float32).tobytes()
            ok_f = inject_custom_attribute_dna(attr_float, float_buf, "FLOAT", 4)
            self.assertTrue(ok_f)
            self.assertEqual([round(x.value, 2) for x in attr_float.data], [1.25, 2.5, 3.75, 5.0])
        finally:
            bpy.data.meshes.remove(mesh)

    def test_preference_enable_dna_acceleration_toggle(self):
        from MoziToolKit.utils.system import get_prefs
        prefs = get_prefs()
        if prefs is None or not hasattr(prefs, "enable_dna_acceleration"):
            self.skipTest("Preferences not registered")

        orig = prefs.enable_dna_acceleration
        try:
            prefs.enable_dna_acceleration = False
            self.assertFalse(is_dna_enabled())

            prefs.enable_dna_acceleration = True
            self.assertEqual(is_dna_enabled(), is_dna_available())
        finally:
            prefs.enable_dna_acceleration = orig

    def test_mesh_batch_fallback_parity(self):
        import _mesh_arrays as ma
        from MoziToolKit.bridge.mesh import inject_mesh_data

        mesh_data = ma.unit_quads(3, material=1)
        mesh_dna = bpy.data.meshes.new("mesh_dna_test")
        mesh_batch = bpy.data.meshes.new("mesh_batch_test")

        try:
            # 1. Inject via DNA path
            inject_mesh_data(
                mesh_data,
                mesh_dna,
                update_topology=True,
                update_normals=True,
                use_dna=True,
            )

            # 2. Inject via Standard Batch Fallback path
            inject_mesh_data(
                mesh_data,
                mesh_batch,
                update_topology=True,
                update_normals=True,
                use_dna=False,
            )

            # 3. Verify absolute topology & attribute parity
            self.assertEqual(len(mesh_dna.vertices), len(mesh_batch.vertices))
            self.assertEqual(len(mesh_dna.polygons), len(mesh_batch.polygons))
            self.assertEqual(len(mesh_dna.loops), len(mesh_batch.loops))

            for v_dna, v_batch in zip(mesh_dna.vertices, mesh_batch.vertices):
                for c1, c2 in zip(v_dna.co, v_batch.co):
                    self.assertAlmostEqual(c1, c2, places=5)

            for l_dna, l_batch in zip(mesh_dna.loops, mesh_batch.loops):
                self.assertEqual(l_dna.vertex_index, l_batch.vertex_index)

            for p_dna, p_batch in zip(mesh_dna.polygons, mesh_batch.polygons):
                self.assertEqual(p_dna.loop_start, p_batch.loop_start)
                self.assertEqual(p_dna.loop_total, p_batch.loop_total)
                self.assertEqual(p_dna.material_index, p_batch.material_index)

            uv_dna = mesh_dna.uv_layers.active.data
            uv_batch = mesh_batch.uv_layers.active.data
            self.assertEqual(len(uv_dna), len(uv_batch))
            for u1, u2 in zip(uv_dna, uv_batch):
                self.assertAlmostEqual(u1.uv[0], u2.uv[0], places=5)
                self.assertAlmostEqual(u1.uv[1], u2.uv[1], places=5)
        finally:
            bpy.data.meshes.remove(mesh_dna)
            bpy.data.meshes.remove(mesh_batch)


if __name__ == "__main__":
    unittest.main()
