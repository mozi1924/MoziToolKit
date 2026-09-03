"""
Unit tests for Dynamic Selection Resizing, Shifting, and Boundary Seam Face Culling Re-evaluation.
Verifies that moving or resizing a selection preserves overlapping voxel/mesh data,
prunes out-of-bounds sections, requests only newly introduced sections,
and accurately restores previously culled faces or culls newly joined faces at the boundary seams.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy
from tests._bootstrap import bootstrap_environment
bootstrap_environment()

from utils.live_sync.storage import VoxelStorage
from utils.live_sync.meshing import (
    build_single_section_mesh,
    get_or_create_world_root,
    find_root_section_children,
    prune_out_of_bounds_section_objects,
    clear_all_section_objects,
    _get_mesh_vertex_and_face_count,
)
from utils.live_sync.material.binding import get_shared_material_manager
from utils.mc_baker import get_shared_state_baker


class TestDynamicSelectionResizingAndShifting(unittest.TestCase):
    def setUp(self):
        self.storage = VoxelStorage()
        self.world_root = get_or_create_world_root(bpy.context, root_name="Test_Resize_World")
        clear_all_section_objects(self.world_root)

    def tearDown(self):
        clear_all_section_objects(self.world_root)
        if self.world_root.name in bpy.data.objects:
            bpy.data.objects.remove(self.world_root, do_unlink=True)
        self.storage.clear()

    def test_selection_shift_preserves_overlapping_voxels(self):
        """Moving selection by 1 chunk to the right retains overlapping chunk and prunes shifted-out chunk."""
        # Initial bounds: 32x16x16 covers Section (0,0,0) and Section (1,0,0)
        self.storage.set_bounds(0, 0, 0, 32, 16, 16)
        for x in range(16):
            self.storage.set_block(x, 0, 0, "minecraft:stone")       # in Section 0
            self.storage.set_block(x + 16, 0, 0, "minecraft:dirt")   # in Section 1

        crc_0 = self.storage.calculate_and_store_section_crc(0, 0, 0)
        crc_1 = self.storage.calculate_and_store_section_crc(1, 0, 0)

        # Shift selection to the right: bounds [16, 0, 0, size=(32, 16, 16)] covering (1,0,0) and (2,0,0)
        bounds_changed = self.storage.set_bounds(16, 0, 0, 32, 16, 16)
        self.assertTrue(bounds_changed)

        # Section 0 blocks must be pruned
        self.assertIsNone(self.storage.get_block(0, 0, 0))
        self.assertNotIn((0, 0, 0), self.storage.section_crc_map)
        self.assertNotIn((0, 0, 0), self.storage._section_map)

        # Section 1 blocks must be preserved
        self.assertEqual(self.storage.get_block(16, 0, 0), "minecraft:dirt")
        self.assertEqual(self.storage.get_block(31, 0, 0), "minecraft:dirt")
        self.assertIn((1, 0, 0), self.storage._section_map)

    def test_selection_zero_overlap_clears_storage(self):
        """Teleporting to a completely disjoint selection area clears old data."""
        self.storage.set_bounds(0, 0, 0, 16, 16, 16)
        self.storage.set_block(0, 0, 0, "minecraft:stone")

        # Move far away
        bounds_changed = self.storage.set_bounds(1000, 0, 1000, 16, 16, 16)
        self.assertTrue(bounds_changed)
        self.assertEqual(len(self.storage.block_map), 0)
        self.assertEqual(len(self.storage.section_crc_map), 0)

    def test_prune_out_of_bounds_objects_on_resize(self):
        """prune_out_of_bounds_section_objects removes section objects outside the new bounds."""
        # Setup 2 sections in storage and scene
        self.storage.set_bounds(0, 0, 0, 32, 16, 16)
        self.storage.set_block(0, 0, 0, "minecraft:stone")
        self.storage.set_block(16, 0, 0, "minecraft:stone")
        self.storage.calculate_and_store_section_crc(0, 0, 0)
        self.storage.calculate_and_store_section_crc(1, 0, 0)

        mat_mgr = get_shared_material_manager(world_obj=self.world_root, atlas_params=None)
        baker = get_shared_state_baker()

        obj_0 = build_single_section_mesh(bpy.context, self.storage, 0, 0, 0, self.world_root, mat_mgr, baker)
        obj_1 = build_single_section_mesh(bpy.context, self.storage, 1, 0, 0, self.world_root, mat_mgr, baker)

        self.assertIsNotNone(obj_0)
        self.assertIsNotNone(obj_1)
        self.assertEqual(len(find_root_section_children(self.world_root)), 2)

        # Shrink bounds to cover only Section (0,0,0)
        self.storage.set_bounds(0, 0, 0, 16, 16, 16)
        pruned_count = prune_out_of_bounds_section_objects(self.world_root, self.storage)

        self.assertEqual(pruned_count, 1)
        children = find_root_section_children(self.world_root)
        self.assertEqual(len(children), 1)
        self.assertIn((0, 0, 0), children)
        self.assertNotIn((1, 0, 0), children)

    def test_face_culling_restores_culled_faces_when_selection_shrinks(self):
        """
        CRITICAL TEST: When two adjacent blocks in different sections share a contact face,
        that contact face was originally culled. When selection shrinks and removes the neighbor,
        re-evaluating the seam section must restore the exposed boundary face!
        """
        # Place two blocks: (15, 0, 0) in Section 0 and (16, 0, 0) in Section 1.
        # They touch on the X axis: face +X of block (15,0,0) touches face -X of block (16,0,0).
        self.storage.set_bounds(0, 0, 0, 32, 16, 16)
        self.storage.set_block(15, 0, 0, "minecraft:stone")
        self.storage.set_block(16, 0, 0, "minecraft:stone")

        mat_mgr = get_shared_material_manager(world_obj=self.world_root, atlas_params=None)
        baker = get_shared_state_baker()

        # Build Section 0: Block (15,0,0) has neighbor at (16,0,0), so its east (+X) face is culled.
        # Single cube has 6 faces; with 1 face culled, it has 5 faces.
        sec_obj_0 = build_single_section_mesh(bpy.context, self.storage, 0, 0, 0, self.world_root, mat_mgr, baker)
        _, faces_initial = _get_mesh_vertex_and_face_count(sec_obj_0.data)
        self.assertEqual(faces_initial, 5, "East face of (15,0,0) should be culled due to neighbor at (16,0,0)")

        # Now shrink selection to only [0..15] (covering Section 0 only)
        self.storage.set_bounds(0, 0, 0, 16, 16, 16)
        # Block (16,0,0) was pruned
        self.assertIsNone(self.storage.get_block(16, 0, 0))

        # Re-build Section 0 at the boundary seam:
        # Since neighbor at (16,0,0) is gone, the east (+X) face must be RESTORED (now 6 faces total).
        sec_obj_0_rebuilt = build_single_section_mesh(bpy.context, self.storage, 0, 0, 0, self.world_root, mat_mgr, baker)
        _, faces_after_shrink = _get_mesh_vertex_and_face_count(sec_obj_0_rebuilt.data)
        self.assertEqual(faces_after_shrink, 6, "East face of (15,0,0) must be restored when neighbor section is removed")

    def test_face_culling_occludes_boundary_faces_when_selection_expands(self):
        """
        When selection expands and a new neighbor block is placed adjacent to an existing boundary block,
        re-evaluating the seam section must cull the now-occluded contact face!
        """
        # Start with single block in Section 0
        self.storage.set_bounds(0, 0, 0, 16, 16, 16)
        self.storage.set_block(15, 0, 0, "minecraft:stone")

        mat_mgr = get_shared_material_manager(world_obj=self.world_root, atlas_params=None)
        baker = get_shared_state_baker()

        # Initially 6 faces
        sec_obj_0 = build_single_section_mesh(bpy.context, self.storage, 0, 0, 0, self.world_root, mat_mgr, baker)
        _, faces_single = _get_mesh_vertex_and_face_count(sec_obj_0.data)
        self.assertEqual(faces_single, 6)

        # Expand selection to [0, 0, 0, size=(32, 16, 16)] and add block (16, 0, 0)
        self.storage.set_bounds(0, 0, 0, 32, 16, 16)
        self.storage.set_block(16, 0, 0, "minecraft:stone")

        # Re-build Section 0: East face must now be culled (5 faces)
        sec_obj_0_after_expand = build_single_section_mesh(bpy.context, self.storage, 0, 0, 0, self.world_root, mat_mgr, baker)
        _, faces_after_expand = _get_mesh_vertex_and_face_count(sec_obj_0_after_expand.data)
        self.assertEqual(faces_after_expand, 5, "East face of (15,0,0) must be culled when adjacent neighbor is added")

    def test_stream_preemption_purges_queue_on_selection_change(self):
        """When selection changes while streaming is in progress, lingering queue items are purged instantly."""
        from utils.live_sync.session.session_manager import SyncSession
        session = SyncSession(target_object_name=self.world_root.name)

        # Simulate stream 1 running with 10 sections queued
        session.storage.set_bounds(0, 0, 0, 16, 16, 16)
        session.handle_stream_begin(stream_id=1, total_sections=10, flags=0)
        for i in range(10):
            session.stream_section_queue.put((i, 0, 0, ["minecraft:stone"]))
        self.assertEqual(session.stream_section_queue.qsize(), 10)
        self.assertTrue(session.is_streaming)

        # User moves selection before stream 1 finishes -> stream 2 begins
        session.handle_selection_info(16, 0, 0, 16, 16, 16)
        session.handle_stream_begin(stream_id=2, total_sections=5, flags=0)

        # Stream 1 queue items must have been purged
        self.assertEqual(session.stream_section_queue.qsize(), 0)
        self.assertEqual(session.current_stream_id, 2)
        self.assertEqual(session.stream_total_sections, 5)
        self.assertEqual(session.stream_received_sections, 0)
        session.stop()

    def test_stale_section_snapshot_fencing_drops_out_of_bounds(self):
        """Out-of-bounds section snapshot from a cancelled stream is dropped and not enqueued."""
        from utils.live_sync.session.session_manager import SyncSession
        session = SyncSession(target_object_name=self.world_root.name)

        # Active selection is [100, 0, 0, size=(16, 16, 16)]
        session.storage.set_bounds(100, 0, 0, 16, 16, 16)

        # A late arriving snapshot for old section (0, 0, 0) arrives: start_x = 0
        session.handle_section_snapshot(
            sec_x=0, sec_y=0, sec_z=0,
            start_x=0, start_y=0, start_z=0,
            size_x=16, size_y=16, size_z=16,
            palette=["minecraft:stone"],
            grid_indices=[0] * 4096,
        )

        # Should be dropped: queue remains empty, storage untouched
        self.assertTrue(session.stream_section_queue.empty())
        self.assertIsNone(session.storage.get_block(0, 0, 0))
        session.stop()

    def test_stream_cancelled_status_stops_streaming_without_finalize(self):
        """STREAM_END with status CANCELLED stops streaming cleanly without finalizing stale progress."""
        from utils.live_sync.session.session_manager import SyncSession
        from utils.live_sync.constants import StreamStatus
        session = SyncSession(target_object_name=self.world_root.name)
        session.handle_stream_begin(stream_id=1, total_sections=10, flags=0)
        self.assertTrue(session.is_streaming)

        # Receive STREAM_END with CANCELLED status
        session.handle_stream_end(stream_id=1, sent_sections=3, status=StreamStatus.CANCELLED)

        self.assertFalse(session.is_streaming)
        self.assertFalse(session.server_stream_finished)
        session.stop()

    def test_stream_boundary_seam_face_culling_healing_on_initial_sync(self):
        """
        CRITICAL TEST FOR INITIAL SYNC:
        When scene is completely empty, Section 0 arrives first and builds (with seam face un-culled because Section 1 is not yet in storage).
        Then Section 1 arrives and builds.
        When streaming finishes, the boundary reconcile pass MUST automatically heal Section 0's mesh,
        culling the internal contact face so that both sections have only 5 faces each without manual rebuild!
        """
        from utils.live_sync.session.session_manager import SyncSession, _finalize_stream_sync
        session = SyncSession(target_object_name=self.world_root.name)
        session.storage.set_bounds(0, 0, 0, 32, 16, 16)
        mat_mgr = get_shared_material_manager(world_obj=self.world_root, atlas_params=None)
        baker = get_shared_state_baker()

        # 1. Stream begins
        session.handle_stream_begin(stream_id=1, total_sections=2, flags=0)

        # 2. Section 0 arrives first with block at (15, 0, 0)
        grid_0 = [0] * 4096
        # index for (15, 0, 0) within 16x16x16: x=15, y=0, z=0 -> 15 * 256 + 0 + 0 = 3840
        grid_0[3840] = 0
        session.storage.set_block(15, 0, 0, "minecraft:stone")
        session.storage.calculate_and_store_section_crc(0, 0, 0)

        # Build Section 0 immediately as it would happen during streaming
        sec_obj_0 = build_single_section_mesh(bpy.context, session.storage, 0, 0, 0, self.world_root, mat_mgr, baker)
        _, faces_sec0_initial = _get_mesh_vertex_and_face_count(sec_obj_0.data)
        # Because Section 1 is not yet in storage, (15,0,0) has no east neighbor -> 6 faces
        self.assertEqual(faces_sec0_initial, 6, "Section 0 must initially have 6 faces because Section 1 has not arrived yet")

        # 3. Section 1 arrives later with block at (16, 0, 0)
        session.handle_section_snapshot(
            sec_x=1, sec_y=0, sec_z=0,
            start_x=16, start_y=0, start_z=0,
            size_x=16, size_y=16, size_z=16,
            palette=["minecraft:stone", "minecraft:air"],
            grid_indices=[1] * 4096, # air
        )
        session.storage.set_block(16, 0, 0, "minecraft:stone")
        session.storage._dirty_sections.add((0, 0, 0)) # Section 0 marked dirty by Section 1 arrival
        session.storage._dirty_sections.add((1, 0, 0))

        # Build Section 1
        sec_obj_1 = build_single_section_mesh(bpy.context, session.storage, 1, 0, 0, self.world_root, mat_mgr, baker)
        _, faces_sec1_initial = _get_mesh_vertex_and_face_count(sec_obj_1.data)
        self.assertEqual(faces_sec1_initial, 5, "Section 1 sees Section 0 and culls its west face")

        # 4. Stream finishes -> trigger finalize / reconcile pass
        session.server_stream_finished = True
        _finalize_stream_sync(session, None, self.world_root, 2)

        # 5. Verify Section 0 has been automatically healed! (now 5 faces, internal face culled)
        _, faces_sec0_healed = _get_mesh_vertex_and_face_count(sec_obj_0.data)
        self.assertEqual(faces_sec0_healed, 5, "Section 0 must be automatically healed during stream finalization to cull the seam face!")

        session.stop()


if __name__ == "__main__":
    unittest.main()
