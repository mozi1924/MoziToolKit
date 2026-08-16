"""Unit tests for MC_Atlas_UV_Tiling node group."""

import unittest
import bpy

from utils.node_groups.atlas_uv_tiling import ensure_atlas_uv_tiling, ATLAS_UV_TILING_VERSION


class TestAtlasUVTiling(unittest.TestCase):
    def test_atlas_uv_tiling_group_creation(self):
        group = ensure_atlas_uv_tiling()
        self.assertIsNotNone(group)
        self.assertEqual(group.name, "MC_Atlas_UV_Tiling")
        self.assertEqual(group.get("mozi_template_version"), ATLAS_UV_TILING_VERSION)
        self.assertTrue(group.get("mozi_template_complete"))

        # Verify interface sockets
        input_names = [
            s.name for s in group.interface.items_tree
            if s.item_type == "SOCKET" and s.in_out == "INPUT"
        ]
        output_names = [
            s.name for s in group.interface.items_tree
            if s.item_type == "SOCKET" and s.in_out == "OUTPUT"
        ]

        expected_inputs = [
            "Vector",
            "Scale",
            "Location",
            "Rotation",
            "Mapped Vector",
            "Use External Vector",
            "Atlas Width",
            "Atlas Height",
            "Tile Width",
            "Tile Height",
        ]
        expected_outputs = ["Atlas UV", "Local UV"]

        for exp in expected_inputs:
            self.assertIn(exp, input_names)
        for exp in expected_outputs:
            self.assertIn(exp, output_names)


if __name__ == "__main__":
    unittest.main()
