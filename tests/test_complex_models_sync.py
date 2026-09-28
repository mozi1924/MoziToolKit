"""
Integration test for non-cubic JSON models live sync and voxel mesh reconstruction.
Verifies stairs, slabs, lanterns, torches, fences, beds, and chests are resolved
from models.bin and correctly meshed into custom geometry instead of fallback unit cubes.
"""

from __future__ import annotations

import os
import subprocess
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
from operators.sync.hierarchy import get_or_create_world_mesh_object, update_world_mesh


class TestComplexModelsSync(unittest.TestCase):
    def setUp(self):
        self.models_bin_path = Path(
            os.path.expanduser(
                "~/Library/Application Support/Blender/5.2/datafiles/MoziToolKit/cache/models/models.bin"
            )
        )
        if not self.models_bin_path.exists():
            self.skipTest(f"models.bin cache not found at {self.models_bin_path}")

        with open(self.models_bin_path, "rb") as f:
            raw = f.read()
        self.model_db = libmtk_py.BakedModelDatabase.from_bincode_bytes(raw)

    def test_smart_blockstate_lookup_non_cubic(self):
        """Tests that BlockState property stripping and variant matching resolves non-cubic models."""
        test_states = [
            ("minecraft:oak_stairs[facing=east,half=bottom,shape=straight,waterlogged=false]", 11),
            ("minecraft:oak_stairs[facing=north,half=top,shape=inner_left,waterlogged=true]", 15),
            ("minecraft:torch", 6),
            ("minecraft:wall_torch[facing=north]", 6),
            ("minecraft:lantern[hanging=false,waterlogged=false]", 13),
            ("minecraft:oak_fence[east=false,north=true,south=false,waterlogged=false,west=true]", 20),
            ("minecraft:red_bed[facing=north,occupied=false,part=head]", 15),
            ("minecraft:smooth_stone_slab[type=bottom,waterlogged=false]", 6),
            ("minecraft:chest[facing=south,type=single,waterlogged=false]", 18),
        ]

        for state, min_expected_faces in test_states:
            res = self.model_db.get_mesh(state, clip_hidden=False)
            self.assertIsNotNone(res, f"Failed to resolve model for state: {state}")
            mesh, textures = res
            self.assertGreaterEqual(
                mesh.face_count,
                min_expected_faces,
                f"State {state} expected at least {min_expected_faces} faces, got {mesh.face_count}",
            )
            self.assertGreater(len(textures), 0, f"State {state} should have texture mappings")

    def test_live_sync_complex_preset_streaming(self):
        """Tests LiveSyncSession ingesting 'complex' terrain preset from mock_sync_server."""
        port = 8792
        server_script = PROJECT_DIR / "tools" / "mock_sync_server.py"
        server_proc = subprocess.Popen(
            [
                sys.executable,
                str(server_script),
                "--port",
                str(port),
                "--preset",
                "complex",
                "--size",
                "16",
                "16",
                "16",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        time.sleep(1.0)
        try:
            session = get_sync_bridge_session()
            connected = session.start(
                url=f"ws://127.0.0.1:{port}",
                auto_reconnect=False,
                model_db=self.model_db,
                unified_mesh=True,
            )
            self.assertTrue(connected, "Session should connect to mock server")

            world_mesh = None
            for _ in range(50):
                time.sleep(0.1)
                events = session.poll_events()
                for ev in events:
                    if ev.get("type") == "WORLD_MESH_READY":
                        world_mesh = ev.get("mesh")
                        break
                if world_mesh:
                    break

            session.stop()
        finally:
            server_proc.terminate()
            server_proc.wait()

        self.assertIsNotNone(world_mesh, "World mesh should be generated and received")
        self.assertGreater(world_mesh.vertex_count, 1000, "Complex scene should have >1000 vertices")
        self.assertGreater(world_mesh.face_count, 1000, "Complex scene should have >1000 faces")

        attrs = world_mesh.attribute_names()
        self.assertIn("mtk_material_slot", attrs)
        self.assertIn("mtk_atlas_chunk_id", attrs)
        self.assertIn("mtk_block_x", attrs)


if __name__ == "__main__":
    unittest.main()
