"""
Unit and regression tests for redstone wire model baking, direction handling,
and dynamic power signal tint addressing via libmtk bridge.
"""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

import os

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

try:
    import libmtk_py
    HAS_LIBMTK = True
except ImportError:
    HAS_LIBMTK = False

from bridge.material import BiomeResolver, is_material_bridge_available


class TestRedstoneWireBakingAndAddressing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAS_LIBMTK:
            raise unittest.SkipTest("libmtk_py is required for redstone wire tests")
        from _assets import assets_root, fabric_jar

        cls.stack = libmtk_py.ResourcePackStack()
        jar_path = fabric_jar()
        mc_path = assets_root()
        if jar_path is not None:
            cls.stack.add_zip_pack(str(jar_path))
        elif mc_path is not None:
            cls.stack.add_directory_pack(str(mc_path))
        else:
            raise unittest.SkipTest(
                "Minecraft assets unavailable (set MTK_TEST_JAR / MTK_TEST_ASSETS)"
            )
        cls.baker = libmtk_py.ModelBaker()

    def test_redstone_wire_signal_tints_power_0_to_15(self):
        """Dynamic BiomeResolver addressing must map power 0..15 to canonical Minecraft colors."""
        resolver = BiomeResolver()

        # Power 0 (Off)
        info_off = resolver.get_tint_info(
            "redstone_dust_line0", "minecraft:redstone_wire[power=0]", 0
        )
        self.assertTrue(info_off.get("is_hardcoded"))
        self.assertEqual(info_off.get("tint_type"), 4)  # TINT_TYPE_HARDCODED
        self.assertEqual(info_off.get("hardcoded_hex"), "#4B0000")

        # Power 15 (Max signal)
        info_on = resolver.get_tint_info(
            "redstone_dust_line0", "minecraft:redstone_wire[power=15]", 0
        )
        self.assertTrue(info_on.get("is_hardcoded"))
        self.assertEqual(info_on.get("tint_type"), 4)
        self.assertEqual(info_on.get("hardcoded_hex"), "#FF2600")
        on_color = info_on.get("hardcoded_color")
        self.assertIsNotNone(on_color)
        self.assertAlmostEqual(on_color[0], 1.0, places=2)

        # Intermediate Power 8
        info_mid = resolver.get_tint_info(
            "redstone_dust_line0", "minecraft:redstone_wire[power=8]", 0
        )
        self.assertTrue(info_mid.get("is_hardcoded"))
        self.assertEqual(info_mid.get("tint_type"), 4)
        self.assertIsNotNone(info_mid.get("hardcoded_hex"))
        mid_color = info_mid.get("hardcoded_color")
        self.assertIsNotNone(mid_color)
        self.assertAlmostEqual(mid_color[0], 0.41, places=1)

        # Legacy _on / _off name suffixes
        info_legacy_on = resolver.get_tint_info("redstone_dust_line0_on")
        self.assertEqual(info_legacy_on.get("hardcoded_hex"), "#FF2600")

        info_legacy_off = resolver.get_tint_info("redstone_dust_line0_off")
        self.assertEqual(info_legacy_off.get("hardcoded_hex"), "#4B0000")

    def test_redstone_wire_builtin_fallback_baking(self):
        """Redstone wire models must bake correctly from resource pack assets with emission and tints."""
        if self.stack.get_pack_count() == 0:
            raise unittest.SkipTest("No resource pack available for redstone wire")

        # 1. Straight line along Z (off state)
        mesh_z, tex_z = self.baker.bake_blockstate(
            self.stack, "minecraft:redstone_wire[north=side,south=side,power=0]", False
        )
        self.assertIsNotNone(mesh_z)
        self.assertEqual(mesh_z.face_count, 2, "Straight line must have 2 faces (north arm + south arm)")
        em_z = mesh_z.get_attribute_data("mtk_emission")
        self.assertIsNotNone(em_z)
        for val in em_z:
            self.assertAlmostEqual(val, 0.0, places=3)

        # 2. Power 15 with vertical wall wire (north=up, south=side)
        mesh_up, tex_up = self.baker.bake_blockstate(
            self.stack, "minecraft:redstone_wire[north=up,power=15,south=side]", False
        )
        self.assertIsNotNone(mesh_up)
        self.assertGreater(mesh_up.face_count, 0)

        # Check emission level = 1.0 for power 15
        self.assertTrue(mesh_up.has_attribute("mtk_emission"))
        em_up = mesh_up.get_attribute_data("mtk_emission")
        for val in em_up:
            self.assertAlmostEqual(val, 1.0, places=3)

        # 3. Intermediate power 8 dot wire
        mesh_dot, tex_dot = self.baker.bake_blockstate(
            self.stack, "minecraft:redstone_wire[east=none,north=none,power=8,south=none,west=none]", False
        )
        self.assertIsNotNone(mesh_dot)
        self.assertEqual(mesh_dot.face_count, 1, "Isolated dot wire must have 1 face")
        em_dot = mesh_dot.get_attribute_data("mtk_emission")
        expected_em = 8.0 / 15.0
        for val in em_dot:
            self.assertAlmostEqual(val, expected_em, places=2)

    def test_redstone_wire_directional_geometry(self):
        """Corner and cross wires must generate appropriate geometry faces."""
        if self.stack.get_pack_count() == 0:
            raise unittest.SkipTest("No resource pack available for redstone wire")

        # Corner wire (north=side, east=side): dot + north arm + east arm
        mesh_corner, tex_corner = self.baker.bake_blockstate(
            self.stack, "minecraft:redstone_wire[north=side,east=side,power=15]", False
        )
        self.assertIsNotNone(mesh_corner)
        self.assertEqual(mesh_corner.face_count, 3, "Corner wire must have 3 faces (dot + 2 arms)")
        self.assertTrue(any("redstone_dust_dot" in t for t in tex_corner))

        # Four-way cross wire: dot + all 4 arms
        mesh_cross, tex_cross = self.baker.bake_blockstate(
            self.stack,
            "minecraft:redstone_wire[north=side,south=side,east=side,west=side,power=15]",
            False,
        )
        self.assertIsNotNone(mesh_cross)
        self.assertEqual(mesh_cross.face_count, 5, "Cross wire must have 5 faces (dot + 4 arms)")
        self.assertTrue(any("redstone_dust_dot" in t for t in tex_cross))


if __name__ == "__main__":
    unittest.main()
