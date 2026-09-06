"""
Unit and Integration Tests for Multi-Container Live Sync Connection Binding
and Parent/Child Object Hierarchy Standardization.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[3]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy
from tests._bootstrap import bootstrap_environment
bootstrap_environment()

from utils.live_sync.meshing import (
    is_yefira_root_object,
    is_yefira_child_section,
    is_yefira_object,
    resolve_world_root_object,
    find_root_section_children,
    sync_child_section_names,
    get_section_object_name,
    get_section_mesh_name,
    sync_world_mesh,
    apply_block_delta_to_world,
)
from utils.live_sync.storage import VoxelStorage
from operators.sync.op_sync_connect import (
    SyncSession,
    SyncSessionManager,
    get_active_sync_props,
    get_target_world_object,
    cleanup_sync_state,
)


class TestMultiContainerLiveSync(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_homefile(use_empty=True)
        cleanup_sync_state()

    def tearDown(self):
        cleanup_sync_state()

    def test_parent_child_hierarchy_identification(self):
        """Verify robust identification of root containers vs child section meshes."""
        # 1. Create a parent container Empty
        root_empty = bpy.data.objects.new("City_Container", None)
        root_empty.empty_display_type = 'PLAIN_AXES'
        root_empty["mtk:is_yefira_world"] = True
        bpy.context.scene.collection.objects.link(root_empty)

        # 2. Create child section meshes
        sec_mesh_1 = bpy.data.meshes.new("Mesh_City_Container_Section_0_4_0")
        sec_obj_1 = bpy.data.objects.new("City_Container_Section_0_4_0", sec_mesh_1)
        sec_obj_1["mtk:section_pos"] = [0, 4, 0]
        sec_obj_1.parent = root_empty
        bpy.context.scene.collection.objects.link(sec_obj_1)

        sec_mesh_2 = bpy.data.meshes.new("Mesh_City_Container_Section_1_4_0")
        sec_obj_2 = bpy.data.objects.new("City_Container_Section_1_4_0", sec_mesh_2)
        sec_obj_2["mtk:section_pos"] = [1, 4, 0]
        sec_obj_2.parent = root_empty
        bpy.context.scene.collection.objects.link(sec_obj_2)

        # Unrelated object
        cube_mesh = bpy.data.meshes.new("RegularCubeMesh")
        cube_obj = bpy.data.objects.new("RegularCube", cube_mesh)
        bpy.context.scene.collection.objects.link(cube_obj)

        # Assert hierarchy detection
        self.assertTrue(is_yefira_root_object(root_empty))
        self.assertFalse(is_yefira_child_section(root_empty))
        self.assertTrue(is_yefira_object(root_empty))

        self.assertFalse(is_yefira_root_object(sec_obj_1))
        self.assertTrue(is_yefira_child_section(sec_obj_1))
        self.assertTrue(is_yefira_object(sec_obj_1))

        self.assertFalse(is_yefira_root_object(cube_obj))
        self.assertFalse(is_yefira_child_section(cube_obj))
        self.assertFalse(is_yefira_object(cube_obj))

        # Assert resolve_world_root_object climbs to root
        self.assertEqual(resolve_world_root_object(root_empty), root_empty)
        self.assertEqual(resolve_world_root_object(sec_obj_1), root_empty)
        self.assertEqual(resolve_world_root_object(sec_obj_2), root_empty)
        self.assertIsNone(resolve_world_root_object(cube_obj))

        # Assert find_root_section_children
        children_map = find_root_section_children(root_empty)
        self.assertEqual(len(children_map), 2)
        self.assertEqual(children_map[(0, 4, 0)], sec_obj_1)
        self.assertEqual(children_map[(1, 4, 0)], sec_obj_2)

    def test_sync_child_section_names_on_rename(self):
        """Verify section meshes are renamed automatically when root container is renamed."""
        root = bpy.data.objects.new("OldWorld", None)
        root["mtk:is_yefira_world"] = True
        bpy.context.scene.collection.objects.link(root)

        sec_mesh = bpy.data.meshes.new("Mesh_OldWorld_Section_2_3_4")
        sec_obj = bpy.data.objects.new("OldWorld_Section_2_3_4", sec_mesh)
        sec_obj["mtk:section_pos"] = [2, 3, 4]
        sec_obj.parent = root
        bpy.context.scene.collection.objects.link(sec_obj)

        root.name = "NewWorld"
        sync_child_section_names(root)

        self.assertEqual(sec_obj.name, "NewWorld_Section_2_3_4")
        self.assertEqual(sec_mesh.name, "Mesh_NewWorld_Section_2_3_4")

    def test_multi_container_property_and_session_isolation(self):
        """Verify multiple containers in the scene maintain isolated properties and voxel storages."""
        # Create Container 1 (Overworld)
        bpy.ops.mozi.add_yefira_world(name="Overworld_Container")
        overworld = bpy.data.objects["Overworld_Container"]
        overworld.mozi_sync.url = "ws://127.0.0.1:8765"

        # Create Container 2 (Nether)
        bpy.ops.mozi.add_yefira_world(name="Nether_Container")
        nether = bpy.data.objects["Nether_Container"]
        nether.mozi_sync.url = "ws://192.168.1.120:8765"

        # Verify property isolation
        props_1 = get_active_sync_props(bpy.context, target_obj=overworld)
        props_2 = get_active_sync_props(bpy.context, target_obj=nether)

        self.assertEqual(props_1.url, "ws://127.0.0.1:8765")
        self.assertEqual(props_2.url, "ws://192.168.1.120:8765")

        # Set selection on Container 1
        props_1.min_x, props_1.min_y, props_1.min_z = 0, 64, 0
        props_1.size_x, props_1.size_y, props_1.size_z = 16, 16, 16
        props_1.total_blocks = 4096

        # Container 2 must remain unaffected
        self.assertEqual(props_2.total_blocks, 0)

        # Verify Session Manager maintains separate VoxelStorage instances
        session_mgr = SyncSessionManager()
        sess_1 = session_mgr.get_or_create_session("Overworld_Container", url=props_1.url)
        sess_2 = session_mgr.get_or_create_session("Nether_Container", url=props_2.url)

        self.assertIsNot(sess_1.storage, sess_2.storage)

        palette_1 = ["minecraft:air", "minecraft:stone"]
        grid_1 = [1] * 4096
        sess_1.storage.set_full_snapshot(0, 64, 0, 16, 16, 16, palette_1, grid_1)

        palette_2 = ["minecraft:air", "minecraft:netherrack"]
        grid_2 = [1] * 4096
        sess_2.storage.set_full_snapshot(100, 64, 100, 16, 16, 16, palette_2, grid_2)

        self.assertEqual(sess_1.storage.get_block(0, 64, 0), "minecraft:stone")
        self.assertEqual(sess_2.storage.get_block(100, 64, 100), "minecraft:netherrack")
        self.assertIsNone(sess_1.storage.get_block(100, 64, 100))

    def test_multi_container_mesh_sync_isolation(self):
        """Verify building mesh on Container 1 does not contaminate or clobber Container 2."""
        root_1 = bpy.data.objects.new("Container_A", None)
        root_1["mtk:is_yefira_world"] = True
        bpy.context.scene.collection.objects.link(root_1)

        root_2 = bpy.data.objects.new("Container_B", None)
        root_2["mtk:is_yefira_world"] = True
        bpy.context.scene.collection.objects.link(root_2)

        storage_1 = VoxelStorage()
        storage_1.set_full_snapshot(0, 0, 0, 2, 2, 2, ["minecraft:air", "minecraft:stone"], [1]*8)

        storage_2 = VoxelStorage()
        storage_2.set_full_snapshot(10, 0, 10, 2, 2, 2, ["minecraft:air", "minecraft:sand"], [1]*8)

        res_1 = sync_world_mesh(bpy.context, storage_1, target_obj=root_1, force_full_rebuild=True)
        res_2 = sync_world_mesh(bpy.context, storage_2, target_obj=root_2, force_full_rebuild=True)

        self.assertEqual(res_1.world_obj, root_1)
        self.assertEqual(res_2.world_obj, root_2)

        children_1 = find_root_section_children(root_1)
        children_2 = find_root_section_children(root_2)

        self.assertEqual(len(children_1), 1)
        self.assertEqual(len(children_2), 1)

        sec_1 = list(children_1.values())[0]
        sec_2 = list(children_2.values())[0]

        self.assertTrue(sec_1.name.startswith("Container_A_Section_"))
        self.assertTrue(sec_2.name.startswith("Container_B_Section_"))
        self.assertEqual(sec_1.parent, root_1)
        self.assertEqual(sec_2.parent, root_2)

    def test_live_sync_panel_context_tabs(self):
        """Verify MOZI_PT_live_sync_data polls only for Empty objects and MOZI_PT_live_sync for Mesh objects."""
        from ui.panel_sync import MOZI_PT_live_sync, MOZI_PT_live_sync_data

        root_empty = bpy.data.objects.new("Tab_Container", None)
        root_empty["mtk:is_yefira_world"] = True
        bpy.context.scene.collection.objects.link(root_empty)

        sec_mesh = bpy.data.meshes.new("Mesh_Tab_Section")
        sec_obj = bpy.data.objects.new("Tab_Section_0_0_0", sec_mesh)
        sec_obj["mtk:section_pos"] = (0, 0, 0)
        sec_obj.parent = root_empty
        bpy.context.scene.collection.objects.link(sec_obj)

        # Context with Empty active
        bpy.context.view_layer.objects.active = root_empty
        self.assertTrue(MOZI_PT_live_sync_data.poll(bpy.context))
        self.assertFalse(MOZI_PT_live_sync.poll(bpy.context))

        # Context with Mesh child section active
        bpy.context.view_layer.objects.active = sec_obj
        self.assertFalse(MOZI_PT_live_sync_data.poll(bpy.context))
        self.assertTrue(MOZI_PT_live_sync.poll(bpy.context))

    def test_concurrent_multi_container_connection_and_disconnect(self):
        """Verify multiple containers can independently connect and disconnect without affecting each other."""
        from operators.sync.op_sync_connect import get_active_session_manager
        session_mgr = get_active_session_manager()

        # Create Container 1 and Container 2
        bpy.ops.mozi.add_yefira_world(name="Container_Alpha")
        alpha = bpy.data.objects["Container_Alpha"]
        alpha.mozi_sync.url = "ws://127.0.0.1:8765"

        bpy.ops.mozi.add_yefira_world(name="Container_Beta")
        beta = bpy.data.objects["Container_Beta"]
        beta.mozi_sync.url = "ws://127.0.0.1:8766"

        # Mock thread on session
        sess_a = session_mgr.get_or_create_session(alpha.name, url=alpha.mozi_sync.url)
        sess_b = session_mgr.get_or_create_session(beta.name, url=beta.mozi_sync.url)

        class DummyThread:
            def __init__(self):
                self.is_connected = True
            def is_alive(self):
                return True
            def stop(self):
                self.is_connected = False

        sess_a.client_thread = DummyThread()
        alpha.mozi_sync.is_connected = True
        alpha.mozi_sync.connection_status = "CONNECTED"

        sess_b.client_thread = DummyThread()
        beta.mozi_sync.is_connected = True
        beta.mozi_sync.connection_status = "CONNECTED"

        self.assertEqual(len(session_mgr.get_all_sessions()), 2)

        # Disconnect only Container_Alpha
        res = bpy.ops.mozi.sync_disconnect(target_container="Container_Alpha")
        self.assertEqual(res, {'FINISHED'})

        # Alpha must be disconnected and removed from sessions
        self.assertIsNone(session_mgr.get_session("Container_Alpha"))
        self.assertFalse(alpha.mozi_sync.is_connected)

        # Beta must still be connected and present in sessions!
        self.assertIsNotNone(session_mgr.get_session("Container_Beta"))
        self.assertTrue(beta.mozi_sync.is_connected)
        self.assertTrue(sess_b.client_thread.is_connected)

        # Disconnect Container_Beta
        bpy.ops.mozi.sync_disconnect(target_container="Container_Beta")
        self.assertIsNone(session_mgr.get_session("Container_Beta"))
        self.assertFalse(beta.mozi_sync.is_connected)

    def test_multi_container_chunk_streaming_isolation(self):
        """Verify chunk streaming ingestion and mesh creation target only the designated container."""
        from operators.sync.op_sync_connect import get_active_session_manager
        from utils.live_sync.session.event_pump import _pump_main_thread_events
        session_mgr = get_active_session_manager()

        root_a = bpy.data.objects.new("Container_Stream_A", None)
        root_a["mtk:is_yefira_world"] = True
        bpy.context.scene.collection.objects.link(root_a)

        root_b = bpy.data.objects.new("Container_Stream_B", None)
        root_b["mtk:is_yefira_world"] = True
        bpy.context.scene.collection.objects.link(root_b)

        # Make root_b active to ensure selection does NOT hijack stream
        bpy.context.view_layer.objects.active = root_b

        sess_a = session_mgr.get_or_create_session("Container_Stream_A")
        sess_a.storage.set_bounds(0, 0, 0, 16, 16, 16)
        sess_a.is_streaming = True
        sess_a.stream_phase = "BUILD"
        sess_a.server_stream_finished = True
        sess_a.stream_total_sections = 1
        sess_a.storage.set_full_snapshot(0, 0, 0, 16, 16, 16, ["minecraft:air", "minecraft:stone"], [1]*4096)
        sess_a.stream_section_queue.put((0, 0, 0, ["minecraft:air", "minecraft:stone"]))

        # Run event pump step
        from utils.live_sync.session.event_pump import start_main_thread_pump
        start_main_thread_pump()
        _pump_main_thread_events()

        # Section mesh must be under Container_Stream_A, NOT Container_Stream_B
        children_a = find_root_section_children(root_a)
        children_b = find_root_section_children(root_b)

        self.assertEqual(len(children_a), 1)
        self.assertEqual(len(children_b), 0)

        sec_obj = list(children_a.values())[0]
        self.assertEqual(sec_obj.parent, root_a)
        self.assertTrue(sec_obj.name.startswith("Container_Stream_A_Section_"))

    def test_multi_container_material_addressing_isolation(self):
        """Verify material addressing and slot mapping are strictly isolated across containers."""
        from utils.live_sync.material.binding import (
            get_shared_material_manager,
            clear_shared_material_manager,
            sync_section_material_slots,
        )
        from utils.materials.yefira.atlas_integration import find_bound_atlas_material

        clear_shared_material_manager()

        root_1 = bpy.data.objects.new("World_City", None)
        root_1["mtk:is_yefira_world"] = True
        bpy.context.scene.collection.objects.link(root_1)

        root_2 = bpy.data.objects.new("World_Nether", None)
        root_2["mtk:is_yefira_world"] = True
        bpy.context.scene.collection.objects.link(root_2)

        # Create two distinct atlas chunk materials in scene
        mat_chunk_0 = bpy.data.materials.new("MC_Atlas_Chunk_0")
        mat_chunk_0["mtk:atlas_chunk_id"] = 0
        mat_chunk_0["mtk:atlas_mapping"] = "{}"

        mat_chunk_1 = bpy.data.materials.new("MC_Atlas_Chunk_1")
        mat_chunk_1["mtk:atlas_chunk_id"] = 1
        mat_chunk_1["mtk:atlas_mapping"] = "{}"

        # Create child section for root_1 and assign mat_chunk_0
        mesh_1 = bpy.data.meshes.new("Mesh_City_Sec")
        sec_1 = bpy.data.objects.new("World_City_Section_0_0_0", mesh_1)
        sec_1["mtk:section_pos"] = [0, 0, 0]
        sec_1.parent = root_1
        mesh_1.materials.append(mat_chunk_0)
        bpy.context.scene.collection.objects.link(sec_1)

        # Create child section for root_2 and assign mat_chunk_1
        mesh_2 = bpy.data.meshes.new("Mesh_Nether_Sec")
        sec_2 = bpy.data.objects.new("World_Nether_Section_0_0_0", mesh_2)
        sec_2["mtk:section_pos"] = [0, 0, 0]
        sec_2.parent = root_2
        mesh_2.materials.append(mat_chunk_1)
        bpy.context.scene.collection.objects.link(sec_2)

        # Verify find_bound_atlas_material correctly resolves bound material via Empty root container
        found_mat_1 = find_bound_atlas_material(root_1)
        found_mat_2 = find_bound_atlas_material(root_2)
        self.assertEqual(found_mat_1, mat_chunk_0)
        self.assertEqual(found_mat_2, mat_chunk_1)
        self.assertNotEqual(found_mat_1, found_mat_2)

        # Verify get_shared_material_manager returns independent isolated instances
        mgr_1 = get_shared_material_manager(world_obj=root_1, atlas_params={"mapping": {}})
        mgr_2 = get_shared_material_manager(world_obj=root_2, atlas_params={"mapping": {}})

        self.assertIsNot(mgr_1, mgr_2)
        self.assertEqual(mgr_1.world_obj, root_1)
        self.assertEqual(mgr_2.world_obj, root_2)

        # Assign chunk 0 on manager 1 and chunk 1 on manager 2
        mgr_1.chunk_materials[0] = mat_chunk_0
        mgr_2.chunk_materials[1] = mat_chunk_1

        # Synchronize slots on root_1's section vs root_2's section
        sync_section_material_slots(sec_1, mgr_1)
        sync_section_material_slots(sec_2, mgr_2)

        # Assert slots are completely independent and not cross-polluted
        self.assertEqual(list(sec_1.data.materials), [mat_chunk_0])
        self.assertEqual(list(sec_2.data.materials), [mat_chunk_1])

        # Clearing manager for root_1 leaves manager for root_2 intact
        clear_shared_material_manager(world_obj=root_1)
        from utils.live_sync.material.binding import _CONTAINER_MAT_MANAGERS
        self.assertNotIn(root_1.as_pointer(), _CONTAINER_MAT_MANAGERS)
        self.assertIn(root_2.as_pointer(), _CONTAINER_MAT_MANAGERS)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])


