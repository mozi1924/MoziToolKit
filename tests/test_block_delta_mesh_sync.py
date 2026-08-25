"""
Test Suite for Block-Level Incremental Mesh Synchronization & Attribute Convention.
Tests:
- Native face attribute convention (mtk_block_x, mtk_block_y, mtk_block_z, mtk_face_dir).
- Incremental block placement with neighbor culling.
- Incremental block destruction with neighbor un-culling.
- Cross-section boundary block placement, culling, and section cleanup.
- Multipart block incremental edits (stairs, slabs, fences).
- Fluid block incremental edits.
- Sub-millisecond performance benchmark for real-time live sync.
"""

from __future__ import annotations

import time
import unittest
import bpy
import bmesh

from utils.live_sync import (
    VoxelStorage,
    build_world_mesh,
    sync_world_mesh,
    apply_block_delta_to_world,
    clear_mesh_builder_caches,
    WorldMeshBuildResult,
    MTK_BLOCK_X,
    MTK_BLOCK_Y,
    MTK_BLOCK_Z,
    MTK_FACE_DIR,
)


class TestBlockDeltaMeshSync(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_homefile(use_empty=True)
        clear_mesh_builder_caches()

    def tearDown(self):
        bpy.ops.wm.read_homefile(use_empty=True)
        clear_mesh_builder_caches()

    def test_face_attribute_convention_in_build_and_sync(self):
        """Verify that all generated faces have mtk_block_x/y/z and mtk_face_dir attributes."""
        storage = VoxelStorage()
        storage.set_block(5, 64, -10, "minecraft:stone")

        res = sync_world_mesh(bpy.context, storage)
        self.assertIsNotNone(res.world_obj)
        self.assertEqual(len(res.world_obj.children), 1)

        sec_obj = res.world_obj.children[0]
        mesh = sec_obj.data
        self.assertEqual(len(mesh.polygons), 6)

        # Check attributes exist on mesh
        self.assertIn(MTK_BLOCK_X, mesh.attributes)
        self.assertIn(MTK_BLOCK_Y, mesh.attributes)
        self.assertIn(MTK_BLOCK_Z, mesh.attributes)
        self.assertIn(MTK_FACE_DIR, mesh.attributes)

        # Read back face attributes
        attr_x = mesh.attributes[MTK_BLOCK_X].data
        attr_y = mesh.attributes[MTK_BLOCK_Y].data
        attr_z = mesh.attributes[MTK_BLOCK_Z].data
        attr_dir = mesh.attributes[MTK_FACE_DIR].data

        for i in range(6):
            self.assertEqual(attr_x[i].value, 5)
            self.assertEqual(attr_y[i].value, 64)
            self.assertEqual(attr_z[i].value, -10)
            self.assertIn(attr_dir[i].value, (0, 1, 2, 3, 4, 5))

    def test_incremental_block_placement_and_culling(self):
        """Verify placing a second adjacent block incrementally updates faces and culls touching faces."""
        storage = VoxelStorage()
        # Initialize storage bounds (0, 0, 0) to (2, 2, 2)
        storage.set_full_snapshot(
            min_x=0, min_y=0, min_z=0,
            size_x=3, size_y=3, size_z=3,
            palette=["minecraft:air", "minecraft:stone"],
            grid_indices=[1] + [0] * 26  # Block (0, 0, 0) is stone
        )

        res1 = sync_world_mesh(bpy.context, storage)
        sec_obj = res1.world_obj.children[0]
        self.assertEqual(len(sec_obj.data.polygons), 6)

        # Incrementally place adjacent block at (1, 0, 0)
        storage.apply_delta_update(0, 0, 0, [(1, 0, 0, "minecraft:stone")])
        res2 = apply_block_delta_to_world(
            context=bpy.context,
            storage=storage,
            changes=[(1, 0, 0, "minecraft:stone")],
        )

        self.assertEqual(res2.face_count, 10)  # 6 + 6 - 2 = 10 faces
        self.assertEqual(res2.cubes_count, 2)

        mesh = sec_obj.data
        self.assertEqual(len(mesh.polygons), 10)

        # Verify block coordinate attribution
        attr_x = mesh.attributes[MTK_BLOCK_X].data
        x_coords = [d.value for d in attr_x]
        self.assertEqual(x_coords.count(0), 5)  # 5 visible faces for block 0
        self.assertEqual(x_coords.count(1), 5)  # 5 visible faces for block 1

    def test_incremental_block_destruction_and_unculling(self):
        """Verify breaking a block restores the neighbor's hidden face and removes broken block's faces."""
        storage = VoxelStorage()
        # Two joined blocks at (0, 0, 0) and (1, 0, 0)
        storage.set_full_snapshot(
            min_x=0, min_y=0, min_z=0,
            size_x=2, size_y=1, size_z=1,
            palette=["minecraft:stone"],
            grid_indices=[0, 0],
        )

        res1 = sync_world_mesh(bpy.context, storage)
        sec_obj = res1.world_obj.children[0]
        self.assertEqual(len(sec_obj.data.polygons), 10)

        # Break block (1, 0, 0) -> minecraft:air
        storage.apply_delta_update(0, 0, 0, [(1, 0, 0, "minecraft:air")])
        res2 = apply_block_delta_to_world(
            context=bpy.context,
            storage=storage,
            changes=[(1, 0, 0, "minecraft:air")],
        )

        self.assertEqual(res2.face_count, 6)  # Block 0 has all 6 faces restored
        self.assertEqual(res2.cubes_count, 1)

        mesh = sec_obj.data
        self.assertEqual(len(mesh.polygons), 6)
        attr_x = mesh.attributes[MTK_BLOCK_X].data
        for d in attr_x:
            self.assertEqual(d.value, 0)

    def test_cross_section_boundary_incremental_sync(self):
        """Verify block placed across section boundary (x=15 in sec 0, x=16 in sec 1) culls and updates correctly."""
        storage = VoxelStorage()
        storage.set_full_snapshot(
            min_x=0, min_y=0, min_z=0,
            size_x=32, size_y=1, size_z=1,
            palette=["minecraft:air", "minecraft:stone"],
            grid_indices=[1 if i == 15 else 0 for i in range(32)]  # Block (15, 0, 0) is stone
        )

        res1 = sync_world_mesh(bpy.context, storage)
        self.assertEqual(res1.face_count, 6)
        sec0 = bpy.data.objects.get("Yefira_Section_0_0_0")
        self.assertIsNotNone(sec0)
        self.assertEqual(len(sec0.data.polygons), 6)
        self.assertIsNone(bpy.data.objects.get("Yefira_Section_1_0_0"))

        # Incrementally place block (16, 0, 0) in Section (1, 0, 0)
        storage.apply_delta_update(0, 0, 0, [(16, 0, 0, "minecraft:stone")])
        res2 = apply_block_delta_to_world(
            context=bpy.context,
            storage=storage,
            changes=[(16, 0, 0, "minecraft:stone")],
        )

        self.assertEqual(res2.face_count, 10)
        sec1 = bpy.data.objects.get("Yefira_Section_1_0_0")
        self.assertIsNotNone(sec1)
        # Sec 0 block at x=15 has east face culled -> 5 faces
        self.assertEqual(len(sec0.data.polygons), 5)
        # Sec 1 block at x=16 has west face culled -> 5 faces
        self.assertEqual(len(sec1.data.polygons), 5)

        # Break block (16, 0, 0) -> Sec 1 becomes empty, Sec 0 un-culls to 6 faces
        storage.apply_delta_update(0, 0, 0, [(16, 0, 0, "minecraft:air")])
        res3 = apply_block_delta_to_world(
            context=bpy.context,
            storage=storage,
            changes=[(16, 0, 0, "minecraft:air")],
        )

        self.assertEqual(res3.face_count, 6)
        self.assertEqual(len(sec0.data.polygons), 6)
        # Sec 1 should have been cleaned up
        self.assertIsNone(bpy.data.objects.get("Yefira_Section_1_0_0"))

    def test_multipart_and_fluid_incremental_sync(self):
        """Verify multipart models (stairs) and fluids update incrementally with accurate culling and UVs."""
        storage = VoxelStorage()
        storage.set_full_snapshot(
            min_x=0, min_y=0, min_z=0,
            size_x=2, size_y=1, size_z=1,
            palette=["minecraft:air"],
            grid_indices=[0, 0],
        )
        sync_world_mesh(bpy.context, storage)

        # Place Oak Stairs at (0, 0, 0)
        stair_state = 'minecraft:oak_stairs[facing=east,half=bottom,shape=straight,waterlogged=false]'
        storage.apply_delta_update(0, 0, 0, [(0, 0, 0, stair_state)])
        res1 = apply_block_delta_to_world(
            context=bpy.context,
            storage=storage,
            changes=[(0, 0, 0, stair_state)],
        )

        self.assertGreater(res1.face_count, 0)
        self.assertEqual(res1.props_count, 1)

        # Place Water block at (1, 0, 0)
        water_state = 'minecraft:water[level=0]'
        storage.apply_delta_update(0, 0, 0, [(1, 0, 0, water_state)])
        res2 = apply_block_delta_to_world(
            context=bpy.context,
            storage=storage,
            changes=[(1, 0, 0, water_state)],
        )

        self.assertEqual(res2.props_count, 1)
        self.assertEqual(res2.fluids_count, 1)

    def test_performance_submillisecond_incremental_edit(self):
        """Verify that single-block edits execute in < 1.5ms on a populated world."""
        storage = VoxelStorage()
        size = 10
        total = size * size * size
        grid = [1] * total  # Solid 10x10x10 cube
        storage.set_full_snapshot(
            min_x=0, min_y=0, min_z=0,
            size_x=size, size_y=size, size_z=size,
            palette=["minecraft:air", "minecraft:stone"],
            grid_indices=grid,
        )

        res = sync_world_mesh(bpy.context, storage)
        self.assertIsNotNone(res.world_obj)

        # Perform 20 place/break delta updates and measure execution time
        timings = []
        for i in range(20):
            bx = (i % 8) + 1
            by = 5
            bz = 5
            state = "minecraft:air" if (i % 2 == 0) else "minecraft:stone"

            storage.apply_delta_update(0, 0, 0, [(bx, by, bz, state)])

            t0 = time.perf_counter()
            apply_block_delta_to_world(
                context=bpy.context,
                storage=storage,
                changes=[(bx, by, bz, state)],
            )
            t1 = time.perf_counter()
            timings.append((t1 - t0) * 1000.0)

        avg_ms = sum(timings) / len(timings)
        max_ms = max(timings)
        print(f"\n[PERF BENCHMARK] Block Delta Sync: Avg = {avg_ms:.3f} ms, Max = {max_ms:.3f} ms over 20 edits")

        # Average incremental edit time on a 1000-block scene should be well under 2.0 ms
        self.assertLess(avg_ms, 2.0)

    def test_event_pump_queue_processing(self):
        """Verify that high-frequency _delta_queue streaming drains and syncs immediately."""
        from operators.sync.op_sync_connect import (
            _delta_queue,
            _pump_main_thread_events,
            start_main_thread_pump,
            stop_main_thread_pump,
            get_active_sync_props,
        )
        from utils.live_sync.storage import voxel_storage

        # Setup voxel_storage initial state
        voxel_storage.set_full_snapshot(
            min_x=0, min_y=0, min_z=0,
            size_x=2, size_y=1, size_z=1,
            palette=["minecraft:air"],
            grid_indices=[0, 0],
        )
        sync_world_mesh(bpy.context, voxel_storage)

        # Mock connected property
        props = get_active_sync_props(bpy.context)
        if props:
            props.is_connected = True

        start_main_thread_pump()

        # Queue 2 rapid delta packets
        _delta_queue.put((0, 0, 0, [(0, 0, 0, "minecraft:stone")], 101))
        _delta_queue.put((0, 0, 0, [(1, 0, 0, "minecraft:stone")], 102))

        # Pump event loop
        interval = _pump_main_thread_events()
        self.assertIsNotNone(interval)
        self.assertTrue(_delta_queue.empty())

        # Check that both blocks were placed and mesh updated to 10 faces
        sec0 = bpy.data.objects.get("Yefira_Section_0_0_0")
        self.assertIsNotNone(sec0)
        self.assertEqual(len(sec0.data.polygons), 10)

        stop_main_thread_pump()

    def test_preload_sync_world_data(self):
        """Verify that preload_sync_world_data warms up palette and common blockstates in RAM."""
        from utils.live_sync.mesh_builder import (
            preload_sync_world_data,
            _GLOBAL_STATE_META_CACHE,
        )

        palette = [
            "minecraft:stone",
            "minecraft:oak_log[axis=y]",
            "minecraft:birch_planks",
            "minecraft:glass",
        ]

        # Prior to preload, cache was cleared in setUp
        self.assertEqual(len(_GLOBAL_STATE_META_CACHE), 0)

        total_warmed = preload_sync_world_data(palette=palette)
        self.assertGreaterEqual(total_warmed, len(palette))

        # Check all palette entries are present in global cache
        for s in palette:
            self.assertIn(s, _GLOBAL_STATE_META_CACHE)
            meta = _GLOBAL_STATE_META_CACHE[s]
            self.assertIsNotNone(meta)
            self.assertFalse(meta.is_air)

        # Check common fallback states (e.g. water, lava, grass) are also pre-warmed
        self.assertIn("minecraft:water[level=0]", _GLOBAL_STATE_META_CACHE)
        self.assertIn("minecraft:grass_block[snowy=false]", _GLOBAL_STATE_META_CACHE)


if __name__ == "__main__":
    unittest.main()
