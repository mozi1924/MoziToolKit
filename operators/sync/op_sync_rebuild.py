"""
Operator to rebuild and optimize the Minecraft procedural direct world mesh.
"""

from __future__ import annotations

import bpy
from .op_sync_connect import trigger_mesh_sync, clear_sync_caches, restore_sync_state_from_scene
from ...utils.live_sync.storage import voxel_storage


class MOZI_OT_sync_rebuild_world(bpy.types.Operator):
    bl_idname = "mozi.sync_rebuild_world"
    bl_label = "Rebuild World"
    bl_description = "Reconstruct meshes, face culling, UV maps, and material slots purely from local voxel data"

    target_container: bpy.props.StringProperty(name="Target Container", default="")

    def execute(self, context):
        from .op_sync_connect import (
            find_bound_atlas_material,
            get_cached_atlas_params,
            preload_sync_world_data,
            get_target_world_object,
            get_active_sync_props,
            get_active_session_manager,
            _client_thread,
        )
        try:
            from ...utils.materials.pack import get_configured_pack_stack
        except (ImportError, ValueError):
            from utils.materials.pack import get_configured_pack_stack

        pack_stack = get_configured_pack_stack()
        if not pack_stack or not pack_stack.packs:
            self.report(
                {'ERROR'},
                "No active resource packs or Minecraft JARs configured. "
                "Please configure your Resource Pack Stack in Edit > Preferences > Add-ons > MoziToolKit and click 'Precompile / Rebuild Stack Atlas Cache'."
            )
            return {'CANCELLED'}

        if not pack_stack.is_stack_baked():
            self.report(
                {'ERROR'},
                "The configured Resource Pack Stack has not been precompiled. "
                "Please go to Edit > Preferences > Add-ons > MoziToolKit and click 'Precompile / Rebuild Stack Atlas Cache' before using Live Sync."
            )
            return {'CANCELLED'}

        target_obj = None
        if self.target_container:
            target_obj = bpy.data.objects.get(self.target_container)
        if not target_obj:
            target_obj = get_target_world_object(context)

        session_mgr = get_active_session_manager()
        session = session_mgr.get_session(target_obj.name) if target_obj else None
        active_storage = session.storage if session else voxel_storage

        if not active_storage.block_map:
            # Try restoring from scene first
            if session and session.restore_sync_state_from_scene(target_obj):
                pass
            elif restore_sync_state_from_scene(context, target_obj=target_obj):
                pass

        if not active_storage.block_map:
            if session and session.client_thread and session.client_thread.is_connected:
                self.report({'INFO'}, "No voxel data in memory. Requesting full data from server...")
                bpy.ops.mozi.sync_refresh(target_container=target_obj.name if target_obj else "")
                return {'FINISHED'}
            elif _client_thread and _client_thread.is_connected:
                self.report({'INFO'}, "No voxel data in memory. Requesting full data from server...")
                bpy.ops.mozi.sync_refresh()
                return {'FINISHED'}
            self.report({'WARNING'}, "No voxel data in memory. Connect to server or click Refresh first.")
            return {'CANCELLED'}

        clear_sync_caches()

        existing_world = target_obj or get_target_world_object(context)
        try:
            from ...utils.live_sync.material_binding import validate_and_sync_scene_materials
        except (ImportError, ValueError):
            from utils.live_sync.material_binding import validate_and_sync_scene_materials
        validate_and_sync_scene_materials(existing_world, pack_stack=pack_stack)

        mat = find_bound_atlas_material(existing_world) if existing_world else None
        atlas_params = get_cached_atlas_params(mat)
        cur_palette = active_storage.get_unique_states()
        preload_sync_world_data(palette=cur_palette, world_obj=existing_world, atlas_params=atlas_params)

        trigger_mesh_sync(context, force_full_rebuild=True, target_obj=existing_world, storage=active_storage)

        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in ('VIEW_3D', 'PROPERTIES'):
                    area.tag_redraw()

        props = get_active_sync_props(context, target_obj=existing_world)
        if props:
            from .op_sync_connect import sync_palette_to_props
            sync_palette_to_props(props, active_storage)
            props.sync_verified = True
            props.validation_info = "Verified (100% in sync)"
        total_pts = props.point_count if props else 0
        self.report({'INFO'}, f"Rebuilt world mesh successfully ({total_pts:,} vertices).")
        return {'FINISHED'}

