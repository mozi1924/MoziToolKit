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
from utils.live_sync.session.session_manager import (
    SyncSession,
    SyncSessionManager,
    get_active_session_manager,
    get_active_sync_props,
    start_main_thread_pump,
    _pump_main_thread_events,
    _finalize_stream_sync,
)
from utils.live_sync.meshing import (
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

        from utils.live_sync.session import start_main_thread_pump
        start_main_thread_pump()

        # Pump until queue and reconciliation are complete
        for _ in range(10):
            if not session.is_streaming and session.stream_section_queue.empty():
                break
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
        for _ in range(10):
            if not session.is_streaming and session.stream_section_queue.empty():
                break
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

    def test_selection_change_prunes_stale_section_objects(self):
        """Verify changing selection bounds cleans up previous section objects without overlapping."""
        root = get_or_create_world_root(bpy.context, root_name="Test_Prune_World")
        storage = VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        storage.set_section_snapshot(0, 0, 0, 0, 0, 0, 16, 16, 16, ["minecraft:stone"], [0] * 4096)

        sec0 = build_single_section_mesh(
            context=bpy.context,
            storage=storage,
            sx=0, sy=0, sz=0,
            root_obj=root,
        )
        self.assertIsNotNone(sec0)
        self.assertIn("Test_Prune_World_Section_0_0_0", bpy.data.objects)

        # Now change selection to a completely different region: (100, 0, 100) -> Section (6, 0, 6)
        storage.set_bounds(100, 0, 100, 16, 16, 16)
        storage.set_section_snapshot(6, 0, 6, 100, 0, 100, 16, 16, 16, ["minecraft:dirt"], [0] * 4096)

        # Pruning helper must remove old section (0, 0, 0)
        from utils.live_sync.meshing import prune_out_of_bounds_section_objects
        removed = prune_out_of_bounds_section_objects(root, storage)
        self.assertEqual(removed, 1)
        self.assertNotIn("Test_Prune_World_Section_0_0_0", bpy.data.objects)

        sec6 = build_single_section_mesh(
            context=bpy.context,
            storage=storage,
            sx=6, sy=0, sz=6,
            root_obj=root,
        )
        self.assertIsNotNone(sec6)
        self.assertIn("Test_Prune_World_Section_6_0_6", bpy.data.objects)
        self.assertNotIn("Test_Prune_World_Section_0_0_0", bpy.data.objects)

    def test_mesh_geometry_bottom_centered_on_root_empty(self):
        """Verify that reconstructed world mesh vertices are exactly centered in X/Y and bottom-aligned at Z=0."""
        root = get_or_create_world_root(bpy.context, root_name="Test_Origin_World")
        storage = VoxelStorage()
        # 32 x 16 x 32 bounding box from Minecraft (10, 60, 20)
        storage.set_bounds(10, 60, 20, 32, 16, 32)
        # Place block at bottom-min corner (10, 60, 20) and top-max corner (41, 75, 51)
        storage.set_block(10, 60, 20, "minecraft:stone")
        storage.set_block(41, 75, 51, "minecraft:stone")

        # Build sections
        sec0 = build_single_section_mesh(
            context=bpy.context,
            storage=storage,
            sx=0, sy=3, sz=1,
            root_obj=root,
            origin_centered=True,
        )
        sec1 = build_single_section_mesh(
            context=bpy.context,
            storage=storage,
            sx=2, sy=4, sz=3,
            root_obj=root,
            origin_centered=True,
        )

        all_verts = []
        for child in (sec0, sec1):
            if child and child.data:
                for v in child.data.vertices:
                    all_verts.append(v.co)

        self.assertGreater(len(all_verts), 0)
        min_x = min(v.x for v in all_verts)
        max_x = max(v.x for v in all_verts)
        min_y = min(v.y for v in all_verts)
        max_y = max(v.y for v in all_verts)
        min_z = min(v.z for v in all_verts)
        max_z = max(v.z for v in all_verts)

        # Min corner block bottom face: Z must be 0.0
        self.assertAlmostEqual(min_z, 0.0, places=3, msg="Lowest vertex Z must be 0.0 (bottom of Empty)")
        # Max corner block top face: Z must be 16.0
        self.assertAlmostEqual(max_z, 16.0, places=3, msg="Highest vertex Z must be height (16.0)")
        # Symmetrical centering: min_x = -16.0, max_x = +16.0
        self.assertAlmostEqual(min_x, -16.0, places=3, msg="Min X must be -half_width (-16.0)")
        self.assertAlmostEqual(max_x, 16.0, places=3, msg="Max X must be +half_width (+16.0)")
        # Symmetrical centering: min_y = -16.0, max_y = +16.0
        self.assertAlmostEqual(min_y, -16.0, places=3, msg="Min Y must be -half_depth (-16.0)")
        self.assertAlmostEqual(max_y, 16.0, places=3, msg="Max Y must be +half_depth (+16.0)")

    def test_reconnect_with_matching_crc_skips_rebuild(self):
        """Verify that disconnecting and reconnecting with identical manifest CRC skips full rebuild."""
        root = get_or_create_world_root(bpy.context, root_name="Test_Reconnect_World")
        props = get_active_sync_props(bpy.context, target_obj=root)

        # 1. Initial build: 1 section with stone
        storage = VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        storage.set_section_snapshot(0, 0, 0, 0, 0, 0, 16, 16, 16, ["minecraft:stone"], [0] * 4096)
        sec0 = build_single_section_mesh(
            context=bpy.context,
            storage=storage,
            sx=0, sy=0, sz=0,
            root_obj=root,
            origin_centered=True,
        )
        self.assertIsNotNone(sec0)

        # Persist sync manifest to root object (as done by live sync finalize)
        session1 = self.session_mgr.get_or_create_session(root.name)
        session1.storage = storage
        session1.persist_sync_state_to_scene(root)

        # 2. Simulate disconnect: remove session from session manager
        self.session_mgr.remove_session(root.name)
        self.assertIsNone(self.session_mgr.get_session(root.name))

        # 3. Simulate reconnect: create session and restore state
        session2 = self.session_mgr.get_or_create_session(root.name)
        restored = session2.restore_sync_state_from_scene(root)
        self.assertTrue(restored, "Must successfully restore sync state from scene object")
        self.assertEqual(session2.storage.size_x, 16)
        self.assertEqual(session2.storage.size_y, 16)
        self.assertEqual(session2.storage.size_z, 16)
        self.assertIn((0, 0, 0), session2.storage.section_crc_map)

        # 4. Simulate SelectionInfo incoming with identical bounds
        bounds_changed = session2.storage.set_bounds(0, 0, 0, 16, 16, 16)
        self.assertFalse(bounds_changed, "set_bounds must return False for identical bounds on reconnect")
        self.assertFalse(session2.pending_full_sync_request, "pending_full_sync_request must remain False")

        # 5. Simulate SectionManifest arriving from server with identical CRC
        server_crc = session2.storage.section_crc_map[(0, 0, 0)]
        mismatched = session2.storage.validate_manifest([(0, 0, 0, server_crc)], existing_section_meshes={(0, 0, 0)})
        self.assertEqual(len(mismatched), 0, "All sections must match manifest CRC on reconnect")

    def test_disconnect_and_reconnect_operator_retains_meshes_without_clearing(self):
        """Simulate real UI user clicking Disconnect then Connect: meshes must NEVER be wiped."""
        # 1. Create a world container with an existing section mesh child
        root = bpy.data.objects.new("Test_Reconn_World", None)
        bpy.context.collection.objects.link(root)
        root["mtk:is_yefira_world"] = True
        root["mtk_block_bounds"] = [0, 0, 0, 16, 16, 16]

        storage = VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        storage.set_block(0, 0, 0, "minecraft:stone")
        storage.calculate_and_store_section_crc(0, 0, 0)
        expected_crc = storage.section_crc_map.get((0, 0, 0), 0)

        sec0 = build_single_section_mesh(
            context=bpy.context,
            storage=storage,
            sx=0, sy=0, sz=0,
            root_obj=root,
            origin_centered=True,
        )
        self.assertIsNotNone(sec0)
        self.assertEqual(sec0.get("mtk:section_crc"), str(expected_crc))

        # 2. Trigger disconnect operator
        bpy.ops.mozi.sync_disconnect(target_container=root.name)
        existing_before = find_root_section_children(root)
        self.assertEqual(len(existing_before), 1, "Section mesh must survive disconnect")

        # 3. Simulate new connection session
        session = self.session_mgr.get_or_create_session(root.name)
        self.assertEqual(session.storage.size_x, 16, "Must restore bounds from scene object")
        self.assertIn((0, 0, 0), session.storage.section_crc_map, "Must restore CRC from child section mesh")

        # 4. Ingest selection info from server
        session.handle_selection_info(0, 0, 0, 16, 16, 16)
        existing_after_sel = find_root_section_children(root)
        self.assertEqual(len(existing_after_sel), 1, "Section mesh must NOT be cleared by selection info")

        # 5. Ingest section manifest with matching CRC
        session.handle_section_manifest(1, [(0, 0, 0, expected_crc)])
        existing_after_manifest = find_root_section_children(root)
        self.assertEqual(len(existing_after_manifest), 1, "Section mesh must NOT be deleted or cleared on manifest verification")
        self.assertTrue(session.skip_next_full_snapshot, "Must skip full snapshot rebuild when CRC is identical")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

