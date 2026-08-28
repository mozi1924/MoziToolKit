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

    def execute(self, context):
        from .op_sync_connect import (
            find_bound_atlas_material,
            get_cached_atlas_params,
            preload_sync_world_data,
            DEFAULT_WORLD_OBJECT_NAME,
            get_active_sync_props,
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
                "Please go to Edit > Preferences > Add-ons > MoziToolKit and click 'Precompile / Rebuild Stack Atlas Cache'."
            )
            return {'CANCELLED'}

        if not voxel_storage.block_map:
            if _client_thread and _client_thread.is_connected:
                self.report({'INFO'}, "No voxel data in memory. Requesting full data from server...")
                bpy.ops.mozi.sync_refresh()
                return {'FINISHED'}
            self.report({'WARNING'}, "No voxel data in memory. Connect to server or click Refresh first.")
            return {'CANCELLED'}

        clear_sync_caches()

        existing_world = bpy.data.objects.get(DEFAULT_WORLD_OBJECT_NAME)
        mat = find_bound_atlas_material(existing_world) if existing_world else None
        atlas_params = get_cached_atlas_params(mat)
        cur_palette = list(voxel_storage.get_state_counts().keys())
        preload_sync_world_data(palette=cur_palette, world_obj=existing_world, atlas_params=atlas_params)

        trigger_mesh_sync(context, force_full_rebuild=True)

        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in ('VIEW_3D', 'PROPERTIES'):
                    area.tag_redraw()

        props = get_active_sync_props(context)
        total_pts = props.point_count if props else 0
        self.report({'INFO'}, f"Rebuilt world mesh successfully ({total_pts:,} vertices).")
        return {'FINISHED'}

