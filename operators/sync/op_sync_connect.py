"""
Operators for connecting, disconnecting, and refreshing Minecraft Live Sync.
"""

from __future__ import annotations

import logging
import time
from typing import Optional
import bpy

from ...utils.geometry_nodes.world_tree import setup_world_geometry_nodes
from ...utils.live_sync.client import SyncClientThread
from ...utils.live_sync.point_cloud import refresh_baker_sources, update_world_point_cloud
from ...utils.live_sync.storage import voxel_storage
from ...utils.materials.yefira import (
    extract_atlas_parameters,
    find_bound_atlas_material,
)
from ...utils.system.dependencies import has_websockets

logger = logging.getLogger("MoziToolKit.LiveSync")

_client_thread: Optional[SyncClientThread] = None
_last_seq_id: int = 0
_rebuild_timer_registered: bool = False
REBUILD_DEBOUNCE_SECONDS: float = 0.05

_cached_atlas_params: Optional[dict] = None
_cached_mat_id: Optional[int] = None


def get_active_sync_props(context: Optional[bpy.types.Context] = None):
    """Retrieve mozi_sync scene properties safely."""
    if context is None:
        context = bpy.context
    if hasattr(context, "scene") and hasattr(context.scene, "mozi_sync"):
        return context.scene.mozi_sync
    return None


def get_cached_atlas_params(mat: Optional[bpy.types.Material]) -> dict:
    """Retrieve or compute cached atlas parameters to avoid repeatedly parsing JSON on every delta."""
    global _cached_atlas_params, _cached_mat_id
    mat_id = id(mat) if mat else 0
    if _cached_atlas_params is not None and _cached_mat_id == mat_id:
        return _cached_atlas_params
    _cached_atlas_params = extract_atlas_parameters(mat)
    _cached_mat_id = mat_id
    return _cached_atlas_params


def clear_sync_caches() -> None:
    """Invalidate atlas parameter cache on material or world reset."""
    global _cached_atlas_params, _cached_mat_id
    _cached_atlas_params = None
    _cached_mat_id = None


def trigger_point_cloud_update(context: bpy.types.Context, force_gn_setup: bool = False) -> None:
    """Update Yefira_World point cloud and configure Geometry Nodes engine."""
    refresh_baker_sources()
    props = get_active_sync_props(context)
    filter_air = props.filter_air if props else True

    existing_world = bpy.data.objects.get("Yefira_World")
    mat = find_bound_atlas_material(existing_world) if existing_world else None
    atlas_params = get_cached_atlas_params(mat)
    atlas_mapping_dict = atlas_params.get("material_id_map", {})
    block_face_lut = atlas_params.get("block_face_lut", {})

    res = update_world_point_cloud(
        context=context,
        storage=voxel_storage,
        filter_air=filter_air,
        atlas_mapping_dict=atlas_mapping_dict,
        block_face_lut=block_face_lut,
        block_face_chunk_lut=atlas_params.get("block_face_chunk_lut", {}),
        block_face_texture_lut=atlas_params.get("block_face_texture_lut", {}),
        block_face_tint_lut=atlas_params.get("block_face_tint_lut", {}),
        block_face_anim_timing_lut=atlas_params.get("block_face_anim_timing_lut", {}),
        block_face_anim_frame_size_lut=atlas_params.get("block_face_anim_frame_size_lut", {}),
        block_face_uv_rot_lut=atlas_params.get("block_face_uv_rot_lut", {}),
        block_face_uv_bounds_lut=atlas_params.get("block_face_uv_bounds_lut", {}),
        atlas_mapping_textures=atlas_params.get("mapping", {}).get("textures", {}) if isinstance(atlas_params.get("mapping"), dict) else {},
        atlas_width=atlas_params["width"],
        atlas_height=atlas_params["height"],
        tile_size=atlas_params["tile_size"],
        tiles_per_row=atlas_params["tiles_per_row"],
        anim_atlas_width=atlas_params.get("anim_atlas_width", atlas_params.get("chunk_1_width", 896.0)),
        anim_atlas_height=atlas_params.get("anim_atlas_height", atlas_params.get("chunk_1_height", 1024.0)),
        anim_frame_width=atlas_params.get("anim_frame_width", atlas_params.get("chunk_1_tile_size", 16.0)),
        anim_frame_height=atlas_params.get("anim_frame_height", atlas_params.get("chunk_1_tile_size", 16.0)),
    )

    if res.world_obj:
        mod = res.world_obj.modifiers.get("Yefira_WorldModifier")
        if force_gn_setup or not mod or not mod.node_group:
            setup_world_geometry_nodes(res.world_obj)

    if props:
        props.point_count = res.point_count
        props.cubes_count = res.cubes_count
        props.props_count = res.props_count
        props.fluids_count = res.fluids_count


def schedule_point_cloud_update(force_gn_setup: bool = False) -> None:
    """Coalesce live updates into a single main-thread point-cloud rebuild."""
    global _rebuild_timer_registered
    if _rebuild_timer_registered:
        return

    _rebuild_timer_registered = True

    def flush():
        global _rebuild_timer_registered
        try:
            if voxel_storage.size_x and voxel_storage.size_y and voxel_storage.size_z:
                trigger_point_cloud_update(bpy.context, force_gn_setup=force_gn_setup)
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type in ('VIEW_3D', 'PROPERTIES'):
                            area.tag_redraw()
        except Exception as e:
            logger.error(f"Deferred point-cloud update error: {e}")
        finally:
            _rebuild_timer_registered = False
        return None

    bpy.app.timers.register(flush, first_interval=REBUILD_DEBOUNCE_SECONDS)


class MOZI_OT_sync_connect(bpy.types.Operator):
    bl_idname = "mozi.sync_connect"
    bl_label = "Connect"
    bl_description = "Connect to Minecraft Live Sync WebSocket Server"

    def execute(self, context):
        global _client_thread, _last_seq_id
        props = get_active_sync_props(context)
        if not props:
            self.report({'ERROR'}, "Scene properties not initialized.")
            return {'CANCELLED'}

        if not has_websockets():
            self.report({'WARNING'}, "Missing 'websockets' library! Check bundled extension wheels.")
            return {'CANCELLED'}

        if _client_thread and _client_thread.is_alive():
            self.report({'INFO'}, "Already connected or connecting.")
            return {'FINISHED'}

        def run_in_main_thread(func):
            def wrapper():
                try:
                    func()
                except Exception as e:
                    logger.error(f"Main thread update error: {e}")
                return None
            bpy.app.timers.register(wrapper)

        def on_status_change(status: str):
            def update():
                props.connection_status = status
                props.is_connected = (status == "CONNECTED")
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == 'PROPERTIES':
                            area.tag_redraw()
            run_in_main_thread(update)

        def on_selection_info(min_x, min_y, min_z, size_x, size_y, size_z):
            def update():
                props.has_selection = True
                props.min_x, props.min_y, props.min_z = min_x, min_y, min_z
                props.max_x = min_x + size_x - 1
                props.max_y = min_y + size_y - 1
                props.max_z = min_z + size_z - 1
                props.size_x, props.size_y, props.size_z = size_x, size_y, size_z
                props.total_blocks = size_x * size_y * size_z
            run_in_main_thread(update)

        def on_full_snapshot(min_x, min_y, min_z, size_x, size_y, size_z, palette, grid_indices):
            def update():
                global _last_seq_id
                _last_seq_id = 0
                clear_sync_caches()
                props.has_selection = True
                props.min_x, props.min_y, props.min_z = min_x, min_y, min_z
                props.max_x = min_x + size_x - 1
                props.max_y = min_y + size_y - 1
                props.max_z = min_z + size_z - 1
                props.size_x, props.size_y, props.size_z = size_x, size_y, size_z
                props.palette_count = len(palette)
                total_blocks = size_x * size_y * size_z
                props.total_blocks = total_blocks
                props.update_counter += 1

                # 1. Update VoxelStorage
                voxel_storage.set_full_snapshot(min_x, min_y, min_z, size_x, size_y, size_z, palette, grid_indices)
                schedule_point_cloud_update(force_gn_setup=True)

                # Update Palette UI list
                props.palette_list.clear()
                for p_item in palette:
                    item = props.palette_list.add()
                    item.state_str = p_item

                props.last_update_info = f"Snapshot: {total_blocks} blocks (gen {voxel_storage.generation})"

                # Log delta history
                item = props.delta_history.add()
                item.timestamp = time.strftime("%H:%M:%S")
                item.pos_str = f"Bounds: {size_x}x{size_y}x{size_z}"
                item.block_state = f"Snapshot ({total_blocks} blks)"
                while len(props.delta_history) > 50:
                    props.delta_history.remove(0)
            run_in_main_thread(update)

        def on_delta_update(min_x, min_y, min_z, changes, seq_id):
            def update():
                global _last_seq_id
                if seq_id <= _last_seq_id:
                    return
                _last_seq_id = seq_id

                applied = voxel_storage.apply_delta_update(min_x, min_y, min_z, changes)
                if not applied:
                    return

                schedule_point_cloud_update()
                props.update_counter += 1
                props.last_update_info = f"Delta: {len(changes)} blocks (seq {seq_id})"

                # Efficient history list logging
                num_changes = len(changes)
                if num_changes <= 5:
                    for x, y, z, state_str in changes:
                        item = props.delta_history.add()
                        item.timestamp = time.strftime("%H:%M:%S")
                        item.pos_str = f"({x}, {y}, {z})"
                        item.block_state = state_str
                else:
                    item = props.delta_history.add()
                    item.timestamp = time.strftime("%H:%M:%S")
                    item.pos_str = f"Batch ({num_changes})"
                    item.block_state = f"{changes[0][3]} ... (+{num_changes-1})"

                # Keep max 50 items in delta history
                while len(props.delta_history) > 50:
                    props.delta_history.remove(0)
            run_in_main_thread(update)

        def on_section_manifest(server_seq_id, sections):
            def update():
                mismatched = voxel_storage.validate_manifest(sections)
                props.sync_verified = (len(mismatched) == 0)
                props.validation_info = "Verified (100% in sync)" if props.sync_verified else f"Mismatch in {len(mismatched)} section(s)"
                if mismatched and _client_thread:
                    _client_thread.send_repair_request(mismatched)
            run_in_main_thread(update)

        def on_section_snapshot(sec_x, sec_y, sec_z, start_x, start_y, start_z, size_x, size_y, size_z, palette, grid_indices):
            def update():
                updated = voxel_storage.set_section_snapshot(
                    sec_x, sec_y, sec_z, start_x, start_y, start_z,
                    size_x, size_y, size_z, palette, grid_indices
                )
                if updated:
                    schedule_point_cloud_update()
                    props.update_counter += 1
                    props.last_update_info = f"Repaired Section ({sec_x}, {sec_y}, {sec_z})"
            run_in_main_thread(update)

        _client_thread = SyncClientThread(
            url=props.url,
            on_status_change=on_status_change,
            on_selection_info=on_selection_info,
            on_full_snapshot=on_full_snapshot,
            on_delta_update=on_delta_update,
            on_section_manifest=on_section_manifest,
            on_section_snapshot=on_section_snapshot,
        )
        _client_thread.start()

        self.report({'INFO'}, f"Connecting to {props.url}...")
        return {'FINISHED'}


class MOZI_OT_sync_disconnect(bpy.types.Operator):
    bl_idname = "mozi.sync_disconnect"
    bl_label = "Disconnect"
    bl_description = "Disconnect from Minecraft Live Sync server"

    def execute(self, context):
        global _client_thread
        props = get_active_sync_props(context)

        if _client_thread:
            _client_thread.stop()
            _client_thread = None

        if props:
            props.is_connected = False
            props.connection_status = "DISCONNECTED"

        self.report({'INFO'}, "Disconnected from Live Sync server.")
        return {'FINISHED'}


class MOZI_OT_sync_refresh(bpy.types.Operator):
    bl_idname = "mozi.sync_refresh"
    bl_label = "Refresh"
    bl_description = "Reconnect and request fresh full snapshot"

    def execute(self, context):
        bpy.ops.mozi.sync_disconnect()
        bpy.ops.mozi.sync_connect()
        return {'FINISHED'}
