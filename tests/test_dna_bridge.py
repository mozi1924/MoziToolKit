"""
Tests for the Blender DNA & Direct Memory Ingestion Adapter Subsystem (bridge/dna).
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock

from bridge.dna import (
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
from bridge.engine import get_libmtk_blender, has_libmtk_dna


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
        attrs_dict = {
            "position": make_mock_attr(8),
            ".corner_vert": make_mock_attr(24),
            "UVMap": make_mock_attr(24),
            "material_index": make_mock_attr(6),
            "Color": make_mock_attr(8),
        }
        mesh.attributes.get = lambda k: attrs_dict.get(k)
        mesh.uv_layers.active.name = "UVMap"
        mesh.color_attributes.active.name = "Color"

        self.assertEqual(resolve_positions_ptr(mesh, expected_count=8), valid_ptr)
        self.assertEqual(resolve_corner_verts_ptr(mesh, expected_count=24), valid_ptr)
        self.assertEqual(resolve_loop_uvs_ptr(mesh, expected_count=24), valid_ptr)
        self.assertEqual(resolve_materials_ptr(mesh, expected_count=6), valid_ptr)
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
        self.assertTrue(hasattr(blender_dna, "copy_buffer_to_ptr"))
        self.assertTrue(hasattr(blender_dna, "copy_positions_to_ptr"))


if __name__ == "__main__":
    unittest.main()
