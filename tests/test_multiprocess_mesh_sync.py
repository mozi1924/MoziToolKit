"""
Unit and integration test suite for multi-process section mesher (ProcessPoolExecutor)
and non-blocking event pump progressive ingestion.
"""

from __future__ import annotations

import sys
import os
import unittest
import bpy

from tests._bootstrap import bootstrap_environment
bootstrap_environment()

from utils.live_sync.storage import VoxelStorage
from utils.live_sync.worker_pool import (
    SectionMesherProcessPool,
    get_shared_section_pool,
    shutdown_section_pool,
)
from utils.live_sync.mesh_builder import (
    sync_world_mesh,
    get_or_create_world_root,
)
from utils.live_sync.session_manager import (
    _session_manager,
    _pump_main_thread_events,
)
from utils.live_sync import session_manager


class TestMultiprocessMeshSync(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_homefile(use_empty=True)
        session_manager._pump_timer_registered = True

    def tearDown(self):
        shutdown_section_pool()

    def test_process_pool_submission_and_result(self):
        """Verify that worker pool execution produces exact valid geometry buffers."""
        storage = VoxelStorage()
        for x in range(16):
            for y in range(16):
                for z in range(16):
                    storage.set_block(x, y, z, "minecraft:stone")

        pool = get_shared_section_pool(max_workers=2)
        future = pool.submit_section(
            storage=storage,
            sx=0, sy=0, sz=0,
            atlas_params=None,
            origin_centered=True,
            weld_vertices=True,
        )

        coords, buffer = future.result(timeout=10.0)
        self.assertEqual(coords, (0, 0, 0))
        self.assertEqual(len(buffer.faces), 1536)
        self.assertEqual(len(buffer.vertices), 1538)
        self.assertGreater(len(buffer.loop_uvs), 0)

    def test_multiprocess_world_sync_multi_section(self):
        """Verify that sync_world_mesh successfully builds multi-section worlds in parallel."""
        storage = VoxelStorage()
        # 32x16x32 world (4 sections: (0,0,0), (1,0,0), (0,0,1), (1,0,1))
        for x in range(32):
            for z in range(32):
                for y in range(8):
                    storage.set_block(x, y, z, "minecraft:stone")
                for y in range(8, 16):
                    storage.set_block(x, y, z, "minecraft:oak_planks")

        res = sync_world_mesh(bpy.context, storage, force_full_rebuild=True)
        self.assertIsNotNone(res.world_obj)
        children = [c for c in res.world_obj.children if "_Section_" in c.name]
        self.assertEqual(len(children), 4)

        total_polys = sum(len(c.data.polygons) for c in children)
        self.assertGreater(total_polys, 0)
        self.assertEqual(res.face_count, total_polys)

    def test_progressive_stream_event_pump_with_worker_pool(self):
        """Verify non-blocking event pump progressive stream ingestion with worker pool."""
        root = get_or_create_world_root(bpy.context, root_name="Async_Stream_World")
        session = _session_manager.get_or_create_session("Async_Stream_World")
        session.is_streaming = True
        session.stream_total_sections = 2
        session.stream_received_sections = 0

        # Feed 2 sections
        indices = [0] * 4096
        session.storage.set_section_snapshot(0, 0, 0, 0, 0, 0, 16, 16, 16, ["minecraft:stone"], indices)
        session.storage.set_section_snapshot(1, 0, 0, 16, 0, 0, 16, 16, 16, ["minecraft:dirt"], indices)

        session.stream_section_queue.put((0, 0, 0, ["minecraft:stone"]))
        session.stream_section_queue.put((1, 0, 0, ["minecraft:dirt"]))

        # Step event pump to dispatch to worker pool
        _pump_main_thread_events()

        # Allow futures to finish and pump again to ingest into Blender meshes
        import time
        t0 = time.time()
        while session.active_geometry_futures and (time.time() - t0 < 5.0):
            _pump_main_thread_events()
            time.sleep(0.01)

        # Pump to finalize
        _pump_main_thread_events()
        session_manager._finalize_stream_sync(session, None, root, 2)

        children = [c for c in root.children if "_Section_" in c.name]
        self.assertEqual(len(children), 2)
        for c in children:
            self.assertGreater(len(c.data.polygons), 0)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
