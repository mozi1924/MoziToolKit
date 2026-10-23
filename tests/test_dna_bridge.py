"""
Tests for the Blender DNA & Direct Memory Ingestion Adapter Subsystem (bridge/dna).
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock

from MoziToolKit.bridge.dna import (
    BaseDnaResolver,
    check_pointer_alignment,
    get_blender_version,
    get_dna_resolver,
    is_dna_available,
    is_dna_enabled,
    is_valid_pointer,
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
    """Test suite for bridge.dna subsystem."""

    def tearDown(self):
        set_dna_enabled(None)
        if "MTK_DISABLE_DNA" in os.environ:
            del os.environ["MTK_DISABLE_DNA"]

    def test_detector_version(self):
        ver = get_blender_version()
        self.assertIsInstance(ver, tuple)
        self.assertGreaterEqual(len(ver), 2)
        self.assertIsInstance(ver[0], int)
        self.assertIsInstance(ver[1], int)
        self.assertTrue(is_version_supported())

    def test_detector_toggle(self):
        # Override disable
        set_dna_enabled(False)
        self.assertFalse(is_dna_enabled())

        # Override enable (will be True only if available)
        set_dna_enabled(True)
        self.assertEqual(is_dna_enabled(), is_dna_available())

        # Reset override
        set_dna_enabled(None)

        # Environment variable override
        os.environ["MTK_DISABLE_DNA"] = "1"
        self.assertFalse(is_dna_available())
        self.assertFalse(is_dna_enabled())

    def test_guard_pointer_validation(self):
        self.assertFalse(is_valid_pointer(0))
        self.assertFalse(is_valid_pointer(None))
        self.assertFalse(is_valid_pointer("0x1234"))
        self.assertFalse(is_valid_pointer(100))  # < MIN_VALID_POINTER
        self.assertFalse(is_valid_pointer(-1))
        self.assertFalse(is_valid_pointer(0xFFFFFFFFFFFFFFFFFF))  # Out of range

        valid_addr = 0x100000000
        self.assertTrue(is_valid_pointer(valid_addr))
        self.assertTrue(check_pointer_alignment(valid_addr, 4))
        self.assertTrue(check_pointer_alignment(valid_addr, 8))
        self.assertFalse(check_pointer_alignment(valid_addr + 1, 4))

    def test_guard_safe_as_pointer(self):
        self.assertIsNone(safe_as_pointer(None))
        self.assertIsNone(safe_as_pointer("not_an_object"))

        # Object with invalid pointer return
        mock_bad = MagicMock()
        mock_bad.as_pointer.return_value = 0
        self.assertIsNone(safe_as_pointer(mock_bad))

        # Object with valid pointer return
        mock_good = MagicMock()
        mock_good.as_pointer.return_value = 0x200000000
        self.assertEqual(safe_as_pointer(mock_good), 0x200000000)

        # Object throwing exception
        mock_err = MagicMock()
        mock_err.as_pointer.side_effect = RuntimeError("Dead RNA reference")
        self.assertIsNone(safe_as_pointer(mock_err))

    def test_resolver_instance(self):
        resolver = get_dna_resolver()
        self.assertIsInstance(resolver, BaseDnaResolver)

    def test_resolver_with_mock_mesh(self):
        valid_ptr = 0x300000000

        # Create mock attribute layer
        def make_mock_attr(count: int = 10):
            attr = MagicMock()
            elem0 = MagicMock()
            elem0.as_pointer.return_value = valid_ptr
            attr.data = [elem0] * count
            return attr

        # Test attribute resolution
        attr = make_mock_attr(10)
        self.assertEqual(resolve_attribute_ptr(attr), valid_ptr)

        # Empty attribute should return None
        attr_empty = MagicMock()
        attr_empty.data = []
        self.assertIsNone(resolve_attribute_ptr(attr_empty))

        # Test mesh attribute resolution
        mesh = MagicMock()
        color_mock = make_mock_attr(8)
        color_mock.data_type = "FLOAT_COLOR"
        color_mock.name = "Color"
        attrs_dict = {
            "position": make_mock_attr(8),
            ".corner_vert": make_mock_attr(24),
            "UVMap": make_mock_attr(24),
            "material_index": make_mock_attr(6),
            "Color": color_mock,
        }
        mesh.attributes.get = lambda k: attrs_dict.get(k)
        mesh.uv_layers.active.name = "UVMap"
        mesh.color_attributes.active = color_mock
        mesh.color_attributes.__len__.return_value = 1
        mesh.color_attributes.__contains__.side_effect = lambda k: k in ("Color",)

        self.assertEqual(resolve_positions_ptr(mesh, expected_count=8), valid_ptr)
        self.assertEqual(resolve_corner_verts_ptr(mesh, expected_count=24), valid_ptr)
        self.assertEqual(resolve_loop_uvs_ptr(mesh, expected_count=24), valid_ptr)
        # Material index resolution is intentionally deferred to Stage 2 Python API
        self.assertIsNone(resolve_materials_ptr(mesh, expected_count=6))
        self.assertEqual(resolve_colors_ptr(mesh, expected_count=8), valid_ptr)

        # Mismatched count should return None
        self.assertIsNone(resolve_positions_ptr(mesh, expected_count=999))

    def test_resolver_point_cloud(self):
        valid_ptr = 0x400000000

        def make_mock_attr():
            attr = MagicMock()
            elem0 = MagicMock()
            elem0.as_pointer.return_value = valid_ptr
            attr.data = [elem0] * 5
            return attr

        cloud = MagicMock()
        cloud_attrs = {
            "position": make_mock_attr(),
            "block_x": make_mock_attr(),
            "block_y": make_mock_attr(),
            "block_z": make_mock_attr(),
            "state_index": make_mock_attr(),
            "biome_index": make_mock_attr(),
            "light_level": make_mock_attr(),
        }
        cloud.attributes.get = lambda k: cloud_attrs.get(k)

        ptrs = resolve_point_cloud_ptrs(cloud, expected_count=5)
        self.assertEqual(ptrs["pos_ptr"], valid_ptr)
        self.assertEqual(ptrs["block_x_ptr"], valid_ptr)
        self.assertEqual(ptrs["state_idx_ptr"], valid_ptr)
        self.assertEqual(ptrs["biome_idx_ptr"], valid_ptr)

    def test_native_dna_module(self):
        if not has_libmtk_dna():
            self.skipTest("libmtk native DNA accelerator is not loaded")

        blender_dna = get_libmtk_blender()
        self.assertIsNotNone(blender_dna)
        self.assertEqual(blender_dna.api_version(), 1)
        self.assertTrue(hasattr(blender_dna, "copy_f32"))
        self.assertTrue(hasattr(blender_dna, "copy_u32"))

    def test_inject_custom_attribute_dna_zero_elements(self):
        from MoziToolKit.bridge.mesh.dna import inject_custom_attribute_dna

        attr = MagicMock()
        attr.data = []
        self.assertTrue(inject_custom_attribute_dna(attr, b"", "INT", 0))

    def test_custom_attribute_dna_in_blender(self):
        try:
            import bpy
            if isinstance(bpy, MagicMock) or isinstance(getattr(bpy, "data", None), MagicMock):
                self.skipTest("Requires real Blender host environment")
        except ImportError:
            self.skipTest("bpy not available")

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
        try:
            import bpy
            if isinstance(bpy, MagicMock) or isinstance(getattr(bpy, "data", None), MagicMock):
                self.skipTest("Requires real Blender host environment")
        except ImportError:
            self.skipTest("bpy not available")

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
        try:
            import bpy
            if isinstance(bpy, MagicMock) or isinstance(getattr(bpy, "data", None), MagicMock):
                self.skipTest("Requires real Blender host environment")
        except ImportError:
            self.skipTest("bpy not available")

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
