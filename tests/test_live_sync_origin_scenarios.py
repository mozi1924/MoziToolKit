"""
Comprehensive integration test suite for object origin positioning across all 4 scenarios:
1. Initial world build when scene has no world object (场景内无世界时首次构建)
2. Incremental delta update (delta更新)
3. Full scene change / full rebuild update (全场景变化全量重构时更新)
4. World size changes update (世界大小发生变化的更新)

Verifies that throughout all lifecycle updates, the object origin in Blender (0, 0, 0)
remains precisely at the bottom center of the bounding volume:
- Minimum Z is 0.0 (ground base)
- Center of X is 0.0
- Center of Y is 0.0
And crucially: vertices NEVER fly up into the sky (Z >= 64).
"""

import asyncio
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
libmtk_release_path = PROJECT_DIR.parent / "libmozitoolkit" / "target" / "release"

for p in [str(libmtk_release_path), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import types
from unittest.mock import MagicMock

if "mathutils" not in sys.modules:
    sys.modules["mathutils"] = MagicMock()

if "bmesh" not in sys.modules:
    sys.modules["bmesh"] = MagicMock()

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
    sys.modules["bpy"] = bpy
    sys.modules["bpy.props"] = MagicMock()
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
    sys.modules["bpy.types"] = _MockTypes
    sys.modules["bpy.props"] = bpy.props
    sys.modules["bpy.app"] = bpy.app
    class _MockAttributeData:
        def __init__(self, count=0):
            self._count = count
        def __len__(self):
            return self._count
        def foreach_set(self, key, values):
            pass

    class _MockAttribute:
        def __init__(self, name, domain, data_type, count=100):
            self.name = name
            self.domain = domain
            self.data_type = data_type
            self.data = _MockAttributeData(count)

    class _MockAttributes(list):
        def get(self, name):
            for a in self:
                if a.name == name:
                    return a
            return None
        def new(self, name, type, domain):
            attr = _MockAttribute(name, domain, type, 100)
            self.append(attr)
            return attr
        def remove(self, attr):
            if attr in self:
                super().remove(attr)

    class _MockUVLayerData:
        def foreach_set(self, key, values):
            pass

    class _MockUVLayer:
        def __init__(self, name="UVMap"):
            self.name = name
            self.data = _MockUVLayerData()

    class _MockUVLayers(list):
        def __init__(self):
            super().__init__()
            self.active = None
        def get(self, name):
            for l in self:
                if l.name == name:
                    return l
            return None
        def new(self, name="UVMap"):
            l = _MockUVLayer(name)
            self.append(l)
            self.active = l
            return l

    class _MockMeshVertices:
        def __init__(self):
            self._coords = []
            self._normals = []
        def __len__(self):
            return len(self._coords)
        def foreach_set(self, attr, values):
            if attr == "co":
                self._coords = [(values[i * 3], values[i * 3 + 1], values[i * 3 + 2]) for i in range(len(values) // 3)]
            elif attr == "normal":
                self._normals = [(values[i * 3], values[i * 3 + 1], values[i * 3 + 2]) for i in range(len(values) // 3)]

    class _MockPolygonData:
        def foreach_set(self, attr, values):
            pass

    class _MockMesh:
        def __init__(self, name="Mesh"):
            self.name = name
            self.vertices = _MockMeshVertices()
            self.polygons = []
            self.materials = []
            self.uv_layers = _MockUVLayers()
            self.color_attributes = _MockAttributes()
            self.attributes = _MockAttributes()
            self.loops = []
        def clear_geometry(self):
            self.vertices = _MockMeshVertices()
            self.polygons = []
            self.loops = []
        def from_pydata(self, verts, edges, faces):
            self.vertices._coords = list(verts)
            self.polygons = [_MockPolygonData() for _ in range(len(faces))]
            self.loops = [None] * (len(faces) * 4)
        def update(self, *args, **kwargs):
            pass

    class _MockObject:
        def __init__(self, name="Obj", mesh=None):
            self.name = name
            self.data = mesh or _MockMesh(name)
            self.type = "MESH"
            self.location = (0.0, 0.0, 0.0)
            self._props = {}
        def __getitem__(self, item):
            return self._props[item]
        def __setitem__(self, item, value):
            self._props[item] = value
        def get(self, item, default=None):
            return self._props.get(item, default)

    class MockCollection(dict):
        def new(self, name, data=None):
            if data is not None:
                obj = _MockObject(name, data)
            else:
                obj = _MockMesh(name)
            self[name] = obj
            return obj

    _mock_objects = MockCollection()
    _mock_meshes = MockCollection()

    bpy.data = MagicMock()
    bpy.data.objects = _mock_objects
    bpy.data.meshes = _mock_meshes
    bpy.data.materials = MagicMock()

    class _MockContext:
        def __init__(self):
            self.active_object = None
            self.mode = "OBJECT"
            self.scene = MagicMock()
            self.scene.collection = MagicMock()
            self.collection = MagicMock()

    bpy.context = _MockContext()

from bridge.sync import SyncBridgeSession, is_sync_available
from operators.sync.hierarchy import (
    DEFAULT_WORLD_OBJECT_NAME,
    get_or_create_world_mesh_object,
    update_world_mesh,
)
from tools.mock_sync_server import MockLiveSyncServer


class AsyncServerRunner:
    """Manages MockLiveSyncServer in a background thread with its own asyncio event loop."""

    def __init__(self, port: int = 8795, origin=(0, 64, 0), size=(16, 16, 16), preset="flat"):
        self.port = port
        self.origin = origin
        self.size = size
        self.preset = preset
        self.loop = None
        self.server = None
        self.thread = None

    def start(self):
        self.loop = asyncio.new_event_loop()
        self.server = MockLiveSyncServer(
            host="127.0.0.1",
            port=self.port,
            preset=self.preset,
            mode="full",
            origin=self.origin,
            size=self.size,
            delta_interval=0.0,
        )

        def _run():
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(self.server.start())
            except (asyncio.CancelledError, Exception):
                pass

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()
        time.sleep(0.5)

    def stop(self):
        if self.server:
            self.server.stop()
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread:
            self.thread.join(timeout=1.0)

    def run_coro(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=5.0)

    def broadcast_delta(self, changes):
        return self.run_coro(self.server.broadcast_delta(changes))

    def broadcast_full_snapshot(self, preset=None):
        return self.run_coro(self.server.broadcast_full_snapshot(preset))

    def broadcast_selection_resize(self, new_origin, new_size, preset=None):
        return self.run_coro(self.server.broadcast_selection_resize(new_origin, new_size, preset))


class TestLiveSyncOriginScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not is_sync_available():
            raise unittest.SkipTest("libmtk_py is not available")

    def setUp(self):
        # Reset mock bpy.data before each test
        if hasattr(bpy.data, "objects") and isinstance(bpy.data.objects, dict):
            bpy.data.objects.clear()
        if hasattr(bpy.data, "meshes") and isinstance(bpy.data.meshes, dict):
            bpy.data.meshes.clear()

    def test_all_four_origin_scenarios_sequential(self):
        """
        Runs the full progression across all 4 scenarios in sequence on a single connection:
        1. Initial build with no world in scene
        2. Delta update on block
        3. Full scene change / rebuild
        4. World size changes update
        """
        server = AsyncServerRunner(port=8796, origin=(0, 64, 0), size=(16, 16, 16), preset="flat")
        server.start()

        session = SyncBridgeSession()
        try:
            # ---------------------------------------------------------------
            # SCENARIO 1: 场景内无世界时首次构建
            # ---------------------------------------------------------------
            self.assertNotIn(DEFAULT_WORLD_OBJECT_NAME, bpy.data.objects)

            connected = session.start(
                url="ws://127.0.0.1:8796",
                auto_reconnect=False,
                unified_mesh=True,
            )
            self.assertTrue(connected, "Client should connect to mock server")

            initial_mesh = None
            for _ in range(40):
                time.sleep(0.05)
                events = session.poll_events()
                for ev in events:
                    if ev.get("type") == "WORLD_MESH_READY":
                        initial_mesh = ev.get("mesh")
                if initial_mesh is not None:
                    break

            self.assertIsNotNone(initial_mesh, "Scenario 1: Should receive initial WORLD_MESH_READY")

            # In Blender, create world mesh object and inject
            world_obj = get_or_create_world_mesh_object(bpy.context)
            self.assertEqual(world_obj.location, (0.0, 0.0, 0.0))
            v_cnt, f_cnt = update_world_mesh(world_obj, initial_mesh)
            self.assertGreater(v_cnt, 0)

            # Check vertex bounds of initial build
            pos1 = initial_mesh.get_flat_positions()
            xs1 = [pos1[i * 3] for i in range(initial_mesh.vertex_count)]
            ys1 = [pos1[i * 3 + 1] for i in range(initial_mesh.vertex_count)]
            zs1 = [pos1[i * 3 + 2] for i in range(initial_mesh.vertex_count)]

            self.assertAlmostEqual(min(zs1), 0.0, places=3, msg="Scenario 1: Min Z must be 0.0 (ground base)")
            self.assertAlmostEqual((min(xs1) + max(xs1)) / 2.0, 0.0, places=3, msg="Scenario 1: Center X must be 0.0")
            self.assertAlmostEqual((min(ys1) + max(ys1)) / 2.0, 0.0, places=3, msg="Scenario 1: Center Y must be 0.0")
            self.assertLess(max(zs1), 20.0, msg="Scenario 1: Max Z should be within world height, not in sky")

            # ---------------------------------------------------------------
            # SCENARIO 2: delta更新
            # ---------------------------------------------------------------
            # Mutate blocks at relative position (4, 4, 4), which is world (4, 68, 4)
            changes = [
                ((4, 4, 4), "minecraft:diamond_block"),
                ((5, 4, 4), "minecraft:gold_block"),
            ]
            server.broadcast_delta(changes)

            delta_mesh = None
            delta_applied = False
            for _ in range(40):
                time.sleep(0.05)
                events = session.poll_events()
                for ev in events:
                    if ev.get("type") == "DELTA_APPLIED":
                        delta_applied = True
                    elif ev.get("type") == "WORLD_MESH_READY":
                        delta_mesh = ev.get("mesh")
                if delta_applied and delta_mesh is not None:
                    break

            self.assertTrue(delta_applied, "Scenario 2: DELTA_APPLIED event should be received")
            self.assertIsNotNone(delta_mesh, "Scenario 2: WORLD_MESH_READY should be received after delta")

            # Update world mesh in Blender
            v_cnt2, f_cnt2 = update_world_mesh(world_obj, delta_mesh)
            self.assertEqual(world_obj.location, (0.0, 0.0, 0.0), "Scenario 2: Object location should remain (0,0,0)")

            pos2 = delta_mesh.get_flat_positions()
            xs2 = [pos2[i * 3] for i in range(delta_mesh.vertex_count)]
            ys2 = [pos2[i * 3 + 1] for i in range(delta_mesh.vertex_count)]
            zs2 = [pos2[i * 3 + 2] for i in range(delta_mesh.vertex_count)]

            # CRITICAL CHECK: The origin must NOT fly up into the sky!
            self.assertAlmostEqual(min(zs2), 0.0, places=3, msg="Scenario 2: Delta update min Z must STILL be 0.0, NOT in sky!")
            self.assertAlmostEqual((min(xs2) + max(xs2)) / 2.0, 0.0, places=3, msg="Scenario 2: Delta update center X must be 0.0")
            self.assertAlmostEqual((min(ys2) + max(ys2)) / 2.0, 0.0, places=3, msg="Scenario 2: Delta update center Y must be 0.0")
            self.assertLess(max(zs2), 20.0, msg="Scenario 2: Max Z must NOT jump to 64+ in sky")

            # ---------------------------------------------------------------
            # SCENARIO 3: 全场景变化全量重构时更新
            # ---------------------------------------------------------------
            # Switch terrain preset to "hills" and broadcast full snapshot
            server.broadcast_full_snapshot(preset="hills")

            full_rebuild_mesh = None
            for _ in range(40):
                time.sleep(0.05)
                events = session.poll_events()
                for ev in events:
                    if ev.get("type") == "WORLD_MESH_READY":
                        full_rebuild_mesh = ev.get("mesh")
                if full_rebuild_mesh is not None:
                    break

            self.assertIsNotNone(full_rebuild_mesh, "Scenario 3: Should receive WORLD_MESH_READY on full scene rebuild")

            v_cnt3, f_cnt3 = update_world_mesh(world_obj, full_rebuild_mesh)
            pos3 = full_rebuild_mesh.get_flat_positions()
            xs3 = [pos3[i * 3] for i in range(full_rebuild_mesh.vertex_count)]
            ys3 = [pos3[i * 3 + 1] for i in range(full_rebuild_mesh.vertex_count)]
            zs3 = [pos3[i * 3 + 2] for i in range(full_rebuild_mesh.vertex_count)]

            self.assertAlmostEqual(min(zs3), 0.0, places=3, msg="Scenario 3: Full rebuild min Z must be 0.0")
            self.assertAlmostEqual((min(xs3) + max(xs3)) / 2.0, 0.0, places=3, msg="Scenario 3: Full rebuild center X must be 0.0")
            self.assertAlmostEqual((min(ys3) + max(ys3)) / 2.0, 0.0, places=3, msg="Scenario 3: Full rebuild center Y must be 0.0")

            # Also test direct get_world_mesh() rebuild query
            direct_mesh = session.get_world_mesh()
            self.assertIsNotNone(direct_mesh)
            self.assertGreater(direct_mesh.vertex_count, 0)
            d_pos = direct_mesh.get_flat_positions()
            d_zs = [d_pos[i * 3 + 2] for i in range(direct_mesh.vertex_count)]
            self.assertAlmostEqual(min(d_zs), 0.0, places=3, msg="Scenario 3: get_world_mesh() min Z must be 0.0")

            # ---------------------------------------------------------------
            # SCENARIO 4: 世界大小发生变化的更新
            # ---------------------------------------------------------------
            # Resize selection to 32x32x32 at origin (0, 64, 0)
            server.broadcast_selection_resize(new_origin=(0, 64, 0), new_size=(32, 32, 32), preset="flat")

            resized_mesh = None
            selection_updated = False
            for _ in range(40):
                time.sleep(0.05)
                events = session.poll_events()
                for ev in events:
                    if ev.get("type") == "SELECTION_UPDATED":
                        selection_updated = True
                        self.assertEqual(ev.get("size_x"), 32)
                        self.assertEqual(ev.get("size_y"), 32)
                        self.assertEqual(ev.get("size_z"), 32)
                    elif ev.get("type") == "WORLD_MESH_READY":
                        resized_mesh = ev.get("mesh")
                if selection_updated and resized_mesh is not None:
                    break

            self.assertTrue(selection_updated, "Scenario 4: SELECTION_UPDATED event should be received")
            self.assertIsNotNone(resized_mesh, "Scenario 4: WORLD_MESH_READY should be received for resized world")

            v_cnt4, f_cnt4 = update_world_mesh(world_obj, resized_mesh)
            pos4 = resized_mesh.get_flat_positions()
            xs4 = [pos4[i * 3] for i in range(resized_mesh.vertex_count)]
            ys4 = [pos4[i * 3 + 1] for i in range(resized_mesh.vertex_count)]
            zs4 = [pos4[i * 3 + 2] for i in range(resized_mesh.vertex_count)]

            # Check new 32x32x32 bounds:
            # Min Z must STILL be 0.0 (ground base)
            # Center of X must STILL be 0.0 (extending to -16..16)
            # Center of Y must STILL be 0.0 (extending to -16..16)
            self.assertAlmostEqual(min(zs4), 0.0, places=3, msg="Scenario 4: Resized world min Z must be 0.0")
            self.assertAlmostEqual((min(xs4) + max(xs4)) / 2.0, 0.0, places=3, msg="Scenario 4: Resized world center X must be 0.0")
            self.assertAlmostEqual((min(ys4) + max(ys4)) / 2.0, 0.0, places=3, msg="Scenario 4: Resized world center Y must be 0.0")
            self.assertAlmostEqual(min(xs4), -16.0, places=1, msg="Scenario 4: Resized world min X should reach -16")
            self.assertAlmostEqual(max(xs4), 16.0, places=1, msg="Scenario 4: Resized world max X should reach 16")

            # Delta on resized world should ALSO stay at bottom-center
            changes4 = [((16, 2, 16), "minecraft:obsidian")]
            server.broadcast_delta(changes4)

            delta4_mesh = None
            for _ in range(40):
                time.sleep(0.05)
                events = session.poll_events()
                for ev in events:
                    if ev.get("type") == "WORLD_MESH_READY":
                        delta4_mesh = ev.get("mesh")
                if delta4_mesh is not None:
                    break

            self.assertIsNotNone(delta4_mesh)
            pos4d = delta4_mesh.get_flat_positions()
            zs4d = [pos4d[i * 3 + 2] for i in range(delta4_mesh.vertex_count)]
            self.assertAlmostEqual(min(zs4d), 0.0, places=3, msg="Scenario 4: Delta on resized world must maintain min Z=0.0")

        finally:
            session.stop()
            server.stop()


if __name__ == "__main__":
    unittest.main()
