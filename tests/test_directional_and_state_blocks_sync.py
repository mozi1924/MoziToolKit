"""
Integration and regression test suite for directional blocks and state transitions in Live Sync:
- Logs (oak_log, birch_log) axis transitions (axis=y -> axis=x -> axis=z) and UV orientation
- Furnaces (furnace, blast_furnace) facing directions (north/east/south/west) and lit toggle
- Pistons & Piston Heads (normal & sticky) extension / retraction transitions and multi-element head models
- Torches and Wall Torches (floor torch vs wall torch facing, alias resolution)
- Verification that state transitions in DeltaUpdate never produce missing models, unknown blocks, or corrupted geometry.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_DIR = Path(__file__).parent.parent.resolve()
site_pkgs = PROJECT_DIR / "site-packages"

for p in [str(site_pkgs), str(PROJECT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

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
from bridge.sync import get_sync_bridge_session, is_sync_available
from tools.mock_sync_server import MockLiveSyncServer


class TestDirectionalAndStateBlocksSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from _assets import blender_datafiles_cache

        cache_root = blender_datafiles_cache()
        if cache_root is None:
            raise unittest.SkipTest(
                "Blender asset cache not found (set MOZI_CACHE_DIR / MTK_TEST_CACHE)"
            )
        cls.models_bin_path = cache_root / "models" / "models.bin"
        if not cls.models_bin_path.exists():
            raise unittest.SkipTest(f"models.bin cache not found at {cls.models_bin_path}")

        with open(cls.models_bin_path, "rb") as f:
            raw = f.read()
        cls.model_db = libmtk_py.BakedModelDatabase.from_bincode_bytes(raw)

    def test_log_axis_rotation_models(self):
        """Logs must resolve correct textures for axis=y, axis=x, and axis=z, and unparameterized fallback."""
        axes = ["axis=y", "axis=x", "axis=z"]
        for ax in axes:
            st = f"minecraft:oak_log[{ax}]"
            res = self.model_db.get_mesh(st, False)
            self.assertIsNotNone(res, f"Log {st} must resolve")
            mesh, textures = res
            self.assertEqual(mesh.face_count, 6, f"Log {st} must have 6 faces")
            self.assertIn("minecraft:block/oak_log", textures)
            self.assertIn("minecraft:block/oak_log_top", textures)

        # Unparameterized log fallback (defaults to axis=y)
        res_default = self.model_db.get_mesh("minecraft:oak_log", False)
        self.assertIsNotNone(res_default, "Unparameterized minecraft:oak_log must resolve")
        self.assertEqual(res_default[0].face_count, 6)

        # Stripped log
        res_stripped = self.model_db.get_mesh("minecraft:stripped_oak_log", False)
        self.assertIsNotNone(res_stripped, "Stripped log must resolve")

    def test_furnace_facing_and_lit_models(self):
        """Furnaces must resolve for all 4 horizontal facings, lit/unlit states, and unparameterized query."""
        facings = ["north", "south", "east", "west"]
        for facing in facings:
            st_off = f"minecraft:furnace[facing={facing},lit=false]"
            res_off = self.model_db.get_mesh(st_off, False)
            self.assertIsNotNone(res_off, f"Furnace {st_off} must resolve")
            mesh_off, tex_off = res_off
            self.assertEqual(mesh_off.face_count, 6)
            self.assertIn("minecraft:block/furnace_front", tex_off)
            self.assertNotIn("minecraft:block/furnace_front_on", tex_off)

            st_on = f"minecraft:furnace[facing={facing},lit=true]"
            res_on = self.model_db.get_mesh(st_on, False)
            self.assertIsNotNone(res_on, f"Furnace {st_on} must resolve")
            mesh_on, tex_on = res_on
            self.assertEqual(mesh_on.face_count, 6)
            self.assertIn("minecraft:block/furnace_front_on", tex_on)
            self.assertNotIn("minecraft:block/furnace_front", tex_on)

        # Query omitting lit (should default to lit=false)
        res_facing_only = self.model_db.get_mesh("minecraft:furnace[facing=east]", False)
        self.assertIsNotNone(res_facing_only, "minecraft:furnace[facing=east] must resolve")
        self.assertIn("minecraft:block/furnace_front", res_facing_only[1])

        # Bare unparameterized furnace
        res_bare = self.model_db.get_mesh("minecraft:furnace", False)
        self.assertIsNotNone(res_bare, "Bare minecraft:furnace must resolve")
        self.assertIn("minecraft:block/furnace_front", res_bare[1])

    def test_piston_and_piston_head_models(self):
        """Pistons must distinguish extended vs retracted states, and piston heads must provide 10-face custom meshes."""
        # Retracted piston
        res_retracted = self.model_db.get_mesh("minecraft:piston[facing=up,extended=false]", False)
        self.assertIsNotNone(res_retracted)
        m_ret, tex_ret = res_retracted
        self.assertEqual(m_ret.face_count, 6)
        self.assertIn("minecraft:block/piston_top", tex_ret)
        self.assertNotIn("minecraft:block/piston_inner", tex_ret)

        # Extended piston base
        res_extended = self.model_db.get_mesh("minecraft:piston[facing=up,extended=true]", False)
        self.assertIsNotNone(res_extended)
        m_ext, tex_ext = res_extended
        self.assertEqual(m_ext.face_count, 6)
        self.assertIn("minecraft:block/piston_inner", tex_ext)

        # Piston head (normal) - 10 to 15 faces depending on pack arm extension elements
        res_head = self.model_db.get_mesh("minecraft:piston_head[facing=up,type=normal,short=false]", False)
        self.assertIsNotNone(res_head)
        m_head, tex_head = res_head
        self.assertIn(m_head.face_count, (10, 15), "Piston head must have 10 or 15 faces (head + arm)")
        self.assertIn("minecraft:block/piston_top", tex_head)

        # Sticky piston head
        res_sticky = self.model_db.get_mesh("minecraft:piston_head[facing=up,type=sticky,short=false]", False)
        self.assertIsNotNone(res_sticky)
        self.assertIn("minecraft:block/piston_top_sticky", res_sticky[1])

        # Piston head omitting short=false
        res_head_omit = self.model_db.get_mesh("minecraft:piston_head[facing=up,type=normal]", False)
        self.assertIsNotNone(res_head_omit, "piston_head omitting short=false must resolve")
        self.assertIn(res_head_omit[0].face_count, (10, 15))

        # Bare piston and piston head
        self.assertIsNotNone(self.model_db.get_mesh("minecraft:piston", False))
        self.assertIsNotNone(self.model_db.get_mesh("minecraft:piston_head", False))

    def test_torch_and_wall_torch_models(self):
        """Wall torches must resolve tilted geometry, and torch[facing=north] must alias to wall_torch."""
        # Floor standing torch
        m_floor, tex_floor = self.model_db.get_mesh("minecraft:torch", False)
        self.assertEqual(m_floor.face_count, 6)
        pos_floor = m_floor.get_flat_positions()
        min_y_floor = min(pos_floor[1::3])
        max_y_floor = max(pos_floor[1::3])
        self.assertAlmostEqual(min_y_floor, 0.0, places=2)
        self.assertAlmostEqual(max_y_floor, 0.625, places=2)

        # Wall torch
        m_wall, tex_wall = self.model_db.get_mesh("minecraft:wall_torch[facing=north]", False)
        self.assertEqual(m_wall.face_count, 6)
        pos_wall = m_wall.get_flat_positions()
        min_y_wall = min(pos_wall[1::3])
        max_y_wall = max(pos_wall[1::3])
        # Wall torch is lifted off floor (min_y around 0.19)
        self.assertGreater(min_y_wall, 0.1)
        self.assertGreater(max_y_wall, 0.7)

        # Alias: torch[facing=north] must resolve to wall torch geometry!
        m_alias, tex_alias = self.model_db.get_mesh("minecraft:torch[facing=north]", False)
        self.assertIsNotNone(m_alias)
        pos_alias = m_alias.get_flat_positions()
        self.assertAlmostEqual(min(pos_alias[1::3]), min_y_wall, places=2)
        self.assertAlmostEqual(max(pos_alias[1::3]), max_y_wall, places=2)

        # Bare wall_torch query
        self.assertIsNotNone(self.model_db.get_mesh("minecraft:wall_torch", False))
        self.assertIsNotNone(self.model_db.get_mesh("minecraft:soul_wall_torch[facing=north]", False))
        self.assertIsNotNone(self.model_db.get_mesh("minecraft:redstone_wall_torch[facing=north]", False))

    def test_live_sync_delta_state_transitions(self):
        """
        Tests live sync scenario where directional blocks undergo dynamic state transitions:
        1. Initial Snapshot: Log(y), Furnace(north, unlit), Piston(up, retracted), Floor torch.
        2. Delta 1: Log rotated to axis=x, Furnace lit up, Piston extended with Head placed, Floor torch becomes Wall torch.
        3. Delta 2: Furnace rotated to east and unlit, Piston retracted and Head removed, Log rotated to axis=z.
        Ensures geometry updates smoothly without unknown blocks or crash.
        """
        port = 8893
        server = MockLiveSyncServer(
            host="127.0.0.1",
            port=port,
            origin=(0, 64, 0),
            size=(8, 8, 8),
            preset="flat",
            delta_interval=999999.0,
        )

        # Configure initial scene:
        # (1, 1, 1): Log axis=y
        # (2, 1, 1): Furnace north, lit=false
        # (3, 1, 1): Piston up, extended=false
        # (4, 1, 1): Floor torch
        server.grid.set_block(1, 1, 1, "minecraft:oak_log[axis=y]")
        server.grid.set_block(2, 1, 1, "minecraft:furnace[facing=north,lit=false]")
        server.grid.set_block(3, 1, 1, "minecraft:piston[facing=up,extended=false]")
        server.grid.set_block(4, 1, 1, "minecraft:torch")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        import threading
        server_thread = threading.Thread(
            target=lambda: loop.run_until_complete(server.start()),
            daemon=True,
        )
        server_thread.start()
        time.sleep(0.5)

        session = get_sync_bridge_session()
        try:
            connected = session.start(
                url=f"ws://127.0.0.1:{port}",
                auto_reconnect=False,
                model_db=self.model_db,
                unified_mesh=True,
            )
            self.assertTrue(connected, "Must connect to mock sync server")

            # 1. Wait for initial snapshot mesh
            initial_mesh = None
            for _ in range(60):
                time.sleep(0.05)
                session.poll_events()
                initial_mesh = session.get_world_mesh()
                if initial_mesh and initial_mesh.face_count > 0:
                    break

            self.assertIsNotNone(initial_mesh, "Initial world mesh must be received")
            init_faces = initial_mesh.face_count
            self.assertGreater(init_faces, 0)

            # 2. Delta #1: Mutate states
            # - Log -> axis=x
            # - Furnace -> north, lit=true
            # - Piston -> up, extended=true
            # - Piston head -> up, normal placed at (3, 2, 1)
            # - Torch removed from floor (4, 1, 1 -> air), placed on wall (4, 1, 2 -> wall_torch[facing=north])
            delta1_changes = [
                ((1, 1, 1), "minecraft:oak_log[axis=x]"),
                ((2, 1, 1), "minecraft:furnace[facing=north,lit=true]"),
                ((3, 1, 1), "minecraft:piston[facing=up,extended=true]"),
                ((3, 2, 1), "minecraft:piston_head[facing=up,type=normal,short=false]"),
                ((4, 1, 1), "minecraft:air"),
                ((4, 1, 2), "minecraft:wall_torch[facing=north]"),
            ]
            for (rx, ry, rz), st in delta1_changes:
                server.grid.set_block(rx, ry, rz, st)

            asyncio.run_coroutine_threadsafe(
                server.broadcast_delta(delta1_changes),
                loop,
            )

            # Wait for Delta #1 to be processed
            delta1_mesh = None
            for _ in range(60):
                time.sleep(0.05)
                session.poll_events()
                delta1_mesh = session.get_world_mesh()
                # Piston head adds faces (piston_head has 10 faces vs floor torch removed/wall torch placed)
                if delta1_mesh and delta1_mesh.face_count > init_faces:
                    break

            self.assertIsNotNone(delta1_mesh)
            self.assertGreater(
                delta1_mesh.face_count,
                init_faces,
                "Delta 1 adding piston head must increase overall face count",
            )

            # 3. Delta #2: Retract and rotate
            # - Piston -> up, extended=false
            # - Piston head -> air at (3, 2, 1)
            # - Furnace -> east, lit=false
            # - Log -> axis=z
            delta2_changes = [
                ((1, 1, 1), "minecraft:oak_log[axis=z]"),
                ((2, 1, 1), "minecraft:furnace[facing=east,lit=false]"),
                ((3, 1, 1), "minecraft:piston[facing=up,extended=false]"),
                ((3, 2, 1), "minecraft:air"),
            ]
            for (rx, ry, rz), st in delta2_changes:
                server.grid.set_block(rx, ry, rz, st)

            asyncio.run_coroutine_threadsafe(
                server.broadcast_delta(delta2_changes),
                loop,
            )

            delta2_mesh = None
            delta2_applied = False
            for _ in range(60):
                time.sleep(0.05)
                evs = session.poll_events()
                if any(e.get("type") == "DELTA_APPLIED" for e in evs):
                    delta2_applied = True
                delta2_mesh = session.get_world_mesh()
                if delta2_applied and delta2_mesh:
                    break

            self.assertIsNotNone(delta2_mesh)
            self.assertTrue(delta2_applied, "Delta 2 must be processed and applied")
            self.assertLess(
                delta2_mesh.vertex_count,
                delta1_mesh.vertex_count,
                "Delta 2 removing piston head must decrease vertex count back",
            )

            # Verify no coordinates are NaN or infinite
            flat_pos = delta2_mesh.get_flat_positions()
            for coord in flat_pos:
                self.assertFalse(
                    coord != coord or abs(coord) > 1e6,
                    f"Mesh vertex coordinate corrupted: {coord}",
                )

        finally:
            session.stop()
            server.stop()
            time.sleep(0.1)
            try:
                loop.call_soon_threadsafe(loop.stop)
                server_thread.join(timeout=1.0)
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
