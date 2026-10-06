"""
Comprehensive regression test suite for model fixes:
1. Resource Pack Priority: Custom models (e.g. Blockbench 3D chain in user resource pack) override vanilla 2D models.
2. Chest Orientation: All 4 horizontal facings (north, south, east, west) produce rotated coordinates.
3. Chiseled Bookshelf: Different slot occupancy states dynamically update occupied/empty slot elements and textures.
4. Skulls and Heads:
   - Floor skull rotations (0, 4, 8, 12) produce rotated coordinates.
   - Dragon head and piglin head use custom multi-cube geometries and correct entity textures.
   - Wall skulls position and orient against walls.
5. Pink Petals / Wildflowers:
   - flower_amount 1..4 and flowers alias resolve to petal planes rather than 6-sided solid cubes.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
site_pkgs = PROJECT_DIR / "site-packages"

for p in [str(site_pkgs), str(PROJECT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from unittest.mock import MagicMock
import types

if "mathutils" not in sys.modules:
    sys.modules["mathutils"] = MagicMock()

if "bpy_extras" not in sys.modules:
    bpy_extras = types.ModuleType("bpy_extras")
    bpy_extras.__path__ = []
    io_utils = types.ModuleType("bpy_extras.io_utils")
    io_utils.ExportHelper = object
    io_utils.ImportHelper = object
    bpy_extras.io_utils = io_utils
    sys.modules["bpy_extras"] = bpy_extras
    sys.modules["bpy_extras.io_utils"] = io_utils

try:
    import bpy
    HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "meshes")
except ImportError:
    bpy = MagicMock()
    HAS_BPY = False

if not HAS_BPY:
    class _MockOperator: pass
    class _MockPanel: pass
    class _MockMenu: pass
    class _MockPropertyGroup: pass
    class _MockUIList: pass
    class _MockAddonPreferences: pass

    class _MockTypes:
        Operator = _MockOperator
        Panel = _MockPanel
        Menu = _MockMenu
        PropertyGroup = _MockPropertyGroup
        UIList = _MockUIList
        AddonPreferences = _MockAddonPreferences

    bpy.types = _MockTypes
    bpy.app = MagicMock()
    bpy.props = MagicMock()

    sys.modules["bpy"] = bpy
    sys.modules["bpy.props"] = bpy.props
    sys.modules["bpy.types"] = _MockTypes
    sys.modules["bpy.app"] = bpy.app
    sys.modules["bmesh"] = MagicMock()
    HAS_BPY = False

import libmtk_py
from tools.mock_sync_server import generate_terrain


class TestModelRegressionFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from _assets import fabric_jar, resource_pack_zip

        cls.vanilla_jar = fabric_jar() or Path("/nonexistent-26.2-Fabric.jar")
        cls.spbr_21 = resource_pack_zip() or Path("/nonexistent-SPBR-21.zip")
        glowing = os.environ.get("MTK_TEST_RESOURCE_PACK_GLOWING")
        cls.spbr_glowing = (
            Path(glowing) if glowing else Path("/nonexistent-SPBR-GlowingOre.zip")
        )

        cls.stack = libmtk_py.ResourcePackStack()
        if cls.spbr_glowing.exists():
            cls.stack.add_zip_pack(str(cls.spbr_glowing))
        if cls.spbr_21.exists():
            cls.stack.add_zip_pack(str(cls.spbr_21))
        if cls.vanilla_jar.exists():
            cls.stack.add_zip_pack(str(cls.vanilla_jar))

        if cls.stack.get_pack_count() == 0:
            raise unittest.SkipTest("No test resource packs or vanilla jar found on system")

        baker = libmtk_py.ModelBaker()
        cls.db = baker.bake_all(cls.stack)

    def test_resource_pack_custom_model_priority(self):
        """Custom 3D chain model in user resource pack must override vanilla 2D cross model."""
        if not self.spbr_21.exists():
            raise unittest.SkipTest("SPBR-21.zip pack not found")

        res = self.db.get_mesh("minecraft:iron_chain[axis=y]", False)
        self.assertIsNotNone(res, "iron_chain[axis=y] must resolve")
        mesh, textures = res
        # Vanilla chain has only 4 faces (2 intersecting planes). SPBR 3D model has 100 faces.
        self.assertGreater(mesh.face_count, 10, "Custom 3D chain model must have many faces, not vanilla 4 faces")
        self.assertIn("minecraft:block/iron_chain", textures)

    def test_chest_orientation_distinct_coordinates(self):
        """Chests facing north, south, east, and west must have distinct rotated geometry."""
        res_n = self.db.get_mesh("minecraft:chest[facing=north,type=single,waterlogged=false]", False)
        res_s = self.db.get_mesh("minecraft:chest[facing=south,type=single,waterlogged=false]", False)
        res_e = self.db.get_mesh("minecraft:chest[facing=east,type=single,waterlogged=false]", False)
        res_w = self.db.get_mesh("minecraft:chest[facing=west,type=single,waterlogged=false]", False)

        self.assertIsNotNone(res_n)
        self.assertIsNotNone(res_s)
        self.assertIsNotNone(res_e)
        self.assertIsNotNone(res_w)

        pn = res_n[0].get_flat_positions()
        ps = res_s[0].get_flat_positions()
        pe = res_e[0].get_flat_positions()
        pw = res_w[0].get_flat_positions()

        self.assertNotEqual(pn, ps, "North and south chests must have distinct vertex coordinates")
        self.assertNotEqual(pn, pe, "North and east chests must have distinct vertex coordinates")
        self.assertNotEqual(pe, pw, "East and west chests must have distinct vertex coordinates")

    def test_chiseled_bookshelf_slot_states(self):
        """Chiseled bookshelf with different occupied slots must produce different geometry and textures."""
        shelf_empty = self.db.get_mesh(
            "minecraft:chiseled_bookshelf[facing=north,slot_0_occupied=false,slot_1_occupied=false,slot_2_occupied=false,slot_3_occupied=false,slot_4_occupied=false,slot_5_occupied=false]",
            False,
        )
        shelf_one = self.db.get_mesh(
            "minecraft:chiseled_bookshelf[facing=north,slot_0_occupied=true,slot_1_occupied=false,slot_2_occupied=false,slot_3_occupied=false,slot_4_occupied=false,slot_5_occupied=false]",
            False,
        )
        shelf_full = self.db.get_mesh(
            "minecraft:chiseled_bookshelf[facing=north,slot_0_occupied=true,slot_1_occupied=true,slot_2_occupied=true,slot_3_occupied=true,slot_4_occupied=true,slot_5_occupied=true]",
            False,
        )

        self.assertIsNotNone(shelf_empty)
        self.assertIsNotNone(shelf_one)
        self.assertIsNotNone(shelf_full)

        p_empty = shelf_empty[0].get_flat_positions()
        p_one = shelf_one[0].get_flat_positions()
        p_full = shelf_full[0].get_flat_positions()

        self.assertNotEqual(p_empty, p_one, "Empty and 1-book bookshelf must have different geometry")
        self.assertNotEqual(p_empty, p_full, "Empty and full bookshelf must have different geometry")

        # Textures check: occupied slot texture must only appear when a slot is occupied
        self.assertNotIn("minecraft:block/chiseled_bookshelf_occupied", shelf_empty[1])
        self.assertIn("minecraft:block/chiseled_bookshelf_occupied", shelf_one[1])
        self.assertIn("minecraft:block/chiseled_bookshelf_occupied", shelf_full[1])

    def test_skulls_and_heads(self):
        """Skulls must rotate with rotation property; dragon and piglin heads must use custom geometries."""
        head_r0 = self.db.get_mesh("minecraft:player_head[rotation=0]", False)
        head_r4 = self.db.get_mesh("minecraft:player_head[rotation=4]", False)
        head_r8 = self.db.get_mesh("minecraft:player_head[rotation=8]", False)

        self.assertIsNotNone(head_r0)
        self.assertIsNotNone(head_r4)
        self.assertIsNotNone(head_r8)

        self.assertNotEqual(
            head_r0[0].get_flat_positions(),
            head_r4[0].get_flat_positions(),
            "rotation=0 and rotation=4 must produce rotated skull vertices",
        )
        self.assertNotEqual(
            head_r0[0].get_flat_positions(),
            head_r8[0].get_flat_positions(),
            "rotation=0 and rotation=8 must produce rotated skull vertices",
        )

        # Dragon head (4 internal contact faces between horns/nostrils and base are deduplicated: 42 - 4 = 38)
        dragon = self.db.get_mesh("minecraft:dragon_head[rotation=0]", False)
        self.assertIsNotNone(dragon)
        mesh_d, tex_d = dragon
        self.assertEqual(mesh_d.face_count, 38, "Dragon head model has 38 faces after deduplicating 4 internal contact faces")
        self.assertIn("minecraft:entity/enderdragon/dragon", tex_d)

        # Piglin head (5 internal contact faces between tusks/snout and head are deduplicated; rotated ears preserve all faces: 36 - 5 = 31)
        piglin = self.db.get_mesh("minecraft:piglin_head[rotation=0]", False)
        self.assertIsNotNone(piglin)
        mesh_p, tex_p = piglin
        self.assertEqual(mesh_p.face_count, 31, "Piglin head model has 31 faces with rotated ears")
        self.assertIn("minecraft:entity/piglin/piglin", tex_p)

        # Wall skull
        wall_dragon = self.db.get_mesh("minecraft:dragon_wall_head[facing=north]", False)
        self.assertIsNotNone(wall_dragon)
        self.assertEqual(wall_dragon[0].face_count, 38)


    def test_pink_petals_geometry(self):
        """Pink petals / wildflowers must not fall back to 6-sided solid cubes."""
        for amt in [1, 2, 3, 4]:
            st = f"minecraft:pink_petals[facing=north,flower_amount={amt}]"
            res = self.db.get_mesh(st, False)
            self.assertIsNotNone(res, f"{st} must resolve")
            mesh, tex = res
            self.assertNotEqual(mesh.face_count, 6, f"{st} must not be a 6-sided solid cube")
            self.assertIn("minecraft:block/pink_petals", tex)

        # Alias resolution
        st_alias = "minecraft:pink_petals[facing=north,flowers=1]"
        res_alias = self.db.get_mesh(st_alias, False)
        self.assertIsNotNone(res_alias)
        self.assertNotEqual(res_alias[0].face_count, 6)

    def test_wall_isolated_and_connected_geometry(self):
        """Walls must resolve isolated post (not 4-way cross) and straight connection geometries."""
        # 1. Isolated wall (single post)
        res_iso = self.db.get_mesh(
            "minecraft:cobblestone_wall[east=none,north=none,south=none,west=none,up=true,waterlogged=false]",
            False,
        )
        self.assertIsNotNone(res_iso, "Isolated wall state must resolve")
        mesh_iso, _ = res_iso
        self.assertEqual(mesh_iso.face_count, 6, "Isolated wall must have 6 faces (post only, NOT cross)")
        pos_iso = mesh_iso.get_flat_positions()
        min_x, max_x = min(pos_iso[0::3]), max(pos_iso[0::3])
        min_z, max_z = min(pos_iso[2::3]), max(pos_iso[2::3])
        self.assertAlmostEqual(min_x, 0.25, places=2)
        self.assertAlmostEqual(max_x, 0.75, places=2)
        self.assertAlmostEqual(min_z, 0.25, places=2)
        self.assertAlmostEqual(max_z, 0.75, places=2)

        # 2. Bare unparameterized wall fallback
        res_bare = self.db.get_mesh("minecraft:cobblestone_wall", False)
        self.assertIsNotNone(res_bare, "Bare cobblestone_wall must resolve")
        self.assertEqual(res_bare[0].face_count, 6, "Bare wall must resolve to post only (6 faces)")

        # 3. Straight wall connected along Z (North-South)
        res_z = self.db.get_mesh(
            "minecraft:cobblestone_wall[east=none,north=low,south=low,west=none,up=false,waterlogged=false]",
            False,
        )
        self.assertIsNotNone(res_z)
        pos_z = res_z[0].get_flat_positions()
        min_z_c, max_z_c = min(pos_z[2::3]), max(pos_z[2::3])
        min_x_c, max_x_c = min(pos_z[0::3]), max(pos_z[0::3])
        self.assertAlmostEqual(min_z_c, 0.0, places=2, msg="Z-connected wall must reach boundary 0.0")
        self.assertAlmostEqual(max_z_c, 1.0, places=2, msg="Z-connected wall must reach boundary 1.0")
        self.assertGreater(min_x_c, 0.25, "Z-connected wall must not reach X=0.0")
        self.assertLess(max_x_c, 0.75, "Z-connected wall must not reach X=1.0")

        res_x = self.db.get_mesh(
            "minecraft:cobblestone_wall[east=low,north=none,south=none,west=low,up=false,waterlogged=false]",
            False,
        )
        self.assertIsNotNone(res_x)
        pos_x = res_x[0].get_flat_positions()
        min_x_c2, max_x_c2 = min(pos_x[0::3]), max(pos_x[0::3])
        min_z_c2, max_z_c2 = min(pos_x[2::3]), max(pos_x[2::3])
        self.assertAlmostEqual(min_x_c2, 0.0, places=2, msg="X-connected wall must reach boundary 0.0")
        self.assertAlmostEqual(max_x_c2, 1.0, places=2, msg="X-connected wall must reach boundary 1.0")
        self.assertGreater(min_z_c2, 0.25, "X-connected wall must not reach Z=0.0")
        self.assertLess(max_z_c2, 0.75, "X-connected wall must not reach Z=1.0")

    def test_fence_isolated_and_connected_geometry(self):
        """Fences must resolve isolated post and directional side connections."""
        # Isolated fence
        res_iso = self.db.get_mesh(
            "minecraft:oak_fence[east=false,north=false,south=false,west=false,waterlogged=false]",
            False,
        )
        self.assertIsNotNone(res_iso)
        self.assertEqual(res_iso[0].face_count, 6, "Isolated fence must have 6 faces (post only)")

        # Bare unparameterized fence
        res_bare = self.db.get_mesh("minecraft:oak_fence", False)
        self.assertIsNotNone(res_bare)
        self.assertEqual(res_bare[0].face_count, 6, "Bare fence must resolve to post only")

        # East-West connected fence
        res_ew = self.db.get_mesh(
            "minecraft:oak_fence[east=true,north=false,south=false,west=true,waterlogged=false]",
            False,
        )
        self.assertIsNotNone(res_ew)
        pos_ew = res_ew[0].get_flat_positions()
        self.assertAlmostEqual(min(pos_ew[0::3]), 0.0, places=2)
        self.assertAlmostEqual(max(pos_ew[0::3]), 1.0, places=2)

    def test_waterlogged_isolated_block_section_mesher(self):
        """Isolated waterlogged blocks must emit both solid element faces and fluid envelope faces."""
        storage = libmtk_py.VoxelStorage()
        storage.set_block(
            2, 2, 2,
            "minecraft:cobblestone_wall[east=none,north=none,south=none,west=none,up=true,waterlogged=true]",
        )
        storage.set_block(
            5, 5, 5,
            "minecraft:oak_stairs[facing=east,half=bottom,shape=straight,waterlogged=true]",
        )
        storage.set_block(
            8, 8, 8,
            "minecraft:oak_slab[type=bottom,waterlogged=true]",
        )
        config = libmtk_py.MesherConfig(enable_ao=False, mesh_fluids=True, z_up_coordinates=True)
        mesh = libmtk_py.SectionMesher.mesh_world(storage, config, None, self.db)

        # Wall: 6 solid + 6 water = 12
        # Stairs: 11 solid + 6 water = 17
        # Slab: 6 solid + 6 water = 12
        # Wall: 6 solid + 6 water = 12
        # Stairs: 11 solid + 6 water = 17
        # Slab: 6 solid + 6 water = 12
        # Total = 41 quads
        self.assertEqual(mesh.quad_count, 41, f"Expected 41 quads, got {mesh.quad_count}")

    def test_bell_body_elements_and_texture(self):
        """Bell must include both support frame and golden bell body (27 quads clipped, 28 unclipped)."""
        res = self.db.get_mesh("minecraft:bell[attachment=floor,facing=north]", False)
        self.assertIsNotNone(res, "bell[attachment=floor,facing=north] must resolve")
        mesh, textures = res
        self.assertIn(mesh.quad_count, (27, 28), f"Expected 27 or 28 quads for bell, got {mesh.quad_count}")
        self.assertIn("minecraft:entity/bell/bell_body", textures)
        self.assertIn("minecraft:block/dark_oak_planks", textures)
        self.assertIn("minecraft:block/stone", textures)

    def test_chest_uv_mapping_and_double_chest(self):
        """Single and double chest UV mappings must correctly align front, top, bottom, and side faces."""
        # Single chest
        res_single = self.db.get_mesh("minecraft:chest[facing=north,type=single,waterlogged=false]", False)
        self.assertIsNotNone(res_single)
        mesh_s, tex_s = res_single
        self.assertEqual(mesh_s.quad_count, 18)
        self.assertIn("minecraft:entity/chest/normal", tex_s)

        # Left double chest
        res_left = self.db.get_mesh("minecraft:chest[facing=north,type=left,waterlogged=false]", False)
        self.assertIsNotNone(res_left)
        mesh_l, tex_l = res_left
        self.assertEqual(mesh_l.quad_count, 18)
        self.assertIn("minecraft:entity/chest/normal_left", tex_l)
        # Left chest outer wall is West (min_x) and must be solid (U: ~0.45..0.67 in UV)
        uvs_l = mesh_l.get_flat_uvs()
        pos_l = mesh_l.get_flat_positions()
        idxs_l = mesh_l.get_quad_indices()
        west_quad_found = False
        for q in range(len(idxs_l) // 4):
            q_idxs = idxs_l[q*4 : (q+1)*4]
            q_pos = [pos_l[i*3 : (i+1)*3] for i in q_idxs]
            q_uvs = [uvs_l[i*2 : (i+1)*2] for i in q_idxs]
            min_x = min(p[0] for p in q_pos)
            max_x = max(p[0] for p in q_pos)
            min_y = min(p[1] for p in q_pos)
            max_y = max(p[1] for p in q_pos)
            if min_x == max_x and min_x < 0.1 and max_y < 0.7:  # West face of bottom
                min_u = min(u[0] for u in q_uvs)
                self.assertGreater(min_u, 0.4, "Left chest outer West face must be solid texture, not transparent 0..14")
                west_quad_found = True
        self.assertTrue(west_quad_found, "Left chest must have a West face")

        # Right double chest
        res_right = self.db.get_mesh("minecraft:chest[facing=north,type=right,waterlogged=false]", False)
        self.assertIsNotNone(res_right)
        mesh_r, tex_r = res_right
        self.assertEqual(mesh_r.quad_count, 18)
        self.assertIn("minecraft:entity/chest/normal_right", tex_r)
        # Right chest outer wall is East (max_x) and must be solid (U: 0.0..0.22 in UV)
        uvs_r = mesh_r.get_flat_uvs()
        pos_r = mesh_r.get_flat_positions()
        idxs_r = mesh_r.get_quad_indices()
        east_quad_found = False
        for q in range(len(idxs_r) // 4):
            q_idxs = idxs_r[q*4 : (q+1)*4]
            q_pos = [pos_r[i*3 : (i+1)*3] for i in q_idxs]
            q_uvs = [uvs_r[i*2 : (i+1)*2] for i in q_idxs]
            min_x = min(p[0] for p in q_pos)
            max_x = max(p[0] for p in q_pos)
            min_y = min(p[1] for p in q_pos)
            max_y = max(p[1] for p in q_pos)
            if min_x == max_x and max_x > 0.9 and max_y < 0.7:  # East face of bottom
                min_u = min(u[0] for u in q_uvs)
                self.assertLess(min_u, 0.05, "Right chest outer East face must be solid texture (U: 0..14)")
                east_quad_found = True
        self.assertTrue(east_quad_found, "Right chest must have an East face")


if __name__ == "__main__":
    unittest.main()
