from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from tests._bootstrap import bootstrap_environment
bootstrap_environment()

import bpy
import time

from utils.live_sync.storage import VoxelStorage
from utils.live_sync.session_manager import (
    SyncSession,
    SyncSessionManager,
    get_active_session_manager,
    get_active_sync_props,
    start_main_thread_pump,
    _pump_main_thread_events,
    _finalize_stream_sync,
)
from utils.live_sync.mesh_builder import (
    build_single_section_mesh,
    get_or_create_world_root,
    find_root_section_children,
)
from operators.sync.op_sync_stream_modal import (
    MOZI_OT_sync_stream_runner,
    start_stream_modal_lock,
)


class TestLiveSyncProgressiveAndLock(unittest.TestCase):

    def setUp(self):
        self.session_mgr = get_active_session_manager()
        self.session_mgr.clear_all()
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in list(bpy.data.meshes):
            bpy.data.meshes.remove(mesh, do_unlink=True)

    def tearDown(self):
        self.session_mgr.clear_all()
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in list(bpy.data.meshes):
            bpy.data.meshes.remove(mesh, do_unlink=True)

    def test_progressive_stream_mesh_building(self):
        """Verify that streaming chunk sections creates individual section meshes in real-time."""
        root = get_or_create_world_root(bpy.context, root_name="Test_Stream_World")
        session = self.session_mgr.get_or_create_session(root.name)
        session.storage.set_bounds(0, 0, 0, 32, 16, 16)
        session.is_streaming = True
        session.stream_total_sections = 2
        session.stream_received_sections = 0

        # Push Section (0, 0, 0)
        palette_0 = ["minecraft:stone", "minecraft:dirt"]
        grid_0 = [0] * (16 * 16 * 16)
        session.storage.set_section_snapshot(0, 0, 0, 0, 0, 0, 16, 16, 16, palette_0, grid_0)
        session.stream_section_queue.put((0, 0, 0, palette_0))

        # Push Section (1, 0, 0)
        palette_1 = ["minecraft:oak_planks"]
        grid_1 = [0] * (16 * 16 * 16)
        session.storage.set_section_snapshot(1, 0, 0, 16, 0, 0, 16, 16, 16, palette_1, grid_1)
        session.stream_section_queue.put((1, 0, 0, palette_1))

        from utils.live_sync.session_manager import start_main_thread_pump
        start_main_thread_pump()

        # Pump once - should drain and build both sections
        _pump_main_thread_events()

        children = find_root_section_children(root)
        self.assertIn((0, 0, 0), children)
        self.assertIn((1, 0, 0), children)

        sec0 = children[(0, 0, 0)]
        self.assertGreater(len(sec0.data.polygons), 0)
        sec1 = children[(1, 0, 0)]
        self.assertGreater(len(sec1.data.polygons), 0)

        # Verify streaming is marked complete after all sections are drained
        self.assertFalse(session.is_streaming)
        props = get_active_sync_props(bpy.context, target_obj=root)
        self.assertTrue(props.sync_verified)
        self.assertFalse(props.is_locked)

    def test_build_single_section_mesh_empty_cleanup(self):
        """Verify build_single_section_mesh safely cleans up objects when a section becomes empty air."""
        root = get_or_create_world_root(bpy.context, root_name="Test_Cleanup_World")
        storage = VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)

        # Build solid section
        storage.set_section_snapshot(0, 0, 0, 0, 0, 0, 16, 16, 16, ["minecraft:stone"], [0] * 4096)
        sec_obj = build_single_section_mesh(
            context=bpy.context,
            storage=storage,
            sx=0, sy=0, sz=0,
            root_obj=root,
        )
        self.assertIsNotNone(sec_obj)
        self.assertIn(sec_obj.name, bpy.data.objects)

        # Update section to pure air
        storage.set_section_snapshot(0, 0, 0, 0, 0, 0, 16, 16, 16, ["minecraft:air"], [0] * 4096)
        sec_obj_after = build_single_section_mesh(
            context=bpy.context,
            storage=storage,
            sx=0, sy=0, sz=0,
            root_obj=root,
        )
        self.assertIsNone(sec_obj_after)
        self.assertNotIn("Test_Cleanup_World_Section_0_0_0", bpy.data.objects)

    def test_full_sync_lock_lifecycle(self):
        """Verify is_locked transitions appropriately during streaming and finalize."""
        root = get_or_create_world_root(bpy.context, root_name="Test_Lock_World")
        props = get_active_sync_props(bpy.context, target_obj=root)
        self.assertFalse(props.is_locked)

        session = self.session_mgr.get_or_create_session(root.name)
        session.is_streaming = True
        session.stream_total_sections = 1
        session.storage.set_bounds(0, 0, 0, 16, 16, 16)
        session.storage.set_section_snapshot(0, 0, 0, 0, 0, 0, 16, 16, 16, ["minecraft:glass"], [0] * 4096)
        session.stream_section_queue.put((0, 0, 0, ["minecraft:glass"]))

        # During streaming, props.is_locked can be set
        props.is_locked = True
        self.assertTrue(props.is_locked)

        start_main_thread_pump()

        # Pump to finalize
        _pump_main_thread_events()

        # Finalized should release lock
        self.assertFalse(props.is_locked)
        self.assertFalse(session.is_streaming)

    def test_delta_sync_remains_unlocked(self):
        """Verify incremental block delta edits execute without locking user interaction."""
        root = get_or_create_world_root(bpy.context, root_name="Test_Delta_World")
        props = get_active_sync_props(bpy.context, target_obj=root)
        props.is_connected = True
        session = self.session_mgr.get_or_create_session(root.name)
        session.storage.set_bounds(0, 0, 0, 16, 16, 16)
        session.storage.set_section_snapshot(0, 0, 0, 0, 0, 0, 16, 16, 16, ["minecraft:stone"], [0] * 4096)

        start_main_thread_pump()

        # Build initial world
        _pump_main_thread_events()

        self.assertFalse(props.is_locked)

        # Push delta edit
        start_main_thread_pump()
        session.delta_queue.put((0, 0, 0, [(0, 0, 0, "minecraft:diamond_block")], 1))
        _pump_main_thread_events()

        # Delta sync must complete lock-free
        self.assertFalse(props.is_locked)
        self.assertEqual(session.storage.get_block(0, 0, 0), "minecraft:diamond_block")

    def test_connect_to_empty_port_non_blocking_and_fast_fail(self):
        """Verify connecting to an empty/non-existent port does not block the main thread and reports status cleanly."""
        root = get_or_create_world_root(bpy.context, root_name="Test_Empty_Port_World")
        props = get_active_sync_props(bpy.context, target_obj=root)
        props.url = "ws://127.0.0.1:59998"

        # Operator execution must return in milliseconds
        t0 = time.time()
        res = bpy.ops.mozi.sync_connect(target_container=root.name)
        elapsed = time.time() - t0

        self.assertEqual(res, {'FINISHED'})
        self.assertLess(elapsed, 0.5, "sync_connect MUST return immediately without blocking UI")

        session = self.session_mgr.get_session(root.name)
        self.assertIsNotNone(session)
        self.assertIsNotNone(session.client_thread)

        # Allow client thread up to 3 seconds to attempt and cleanly fail
        session.client_thread.join(timeout=3.0)
        self.assertFalse(session.client_thread.is_connected)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
