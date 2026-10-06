"""
Operator to create a Yefira World Empty container for live synchronization.
"""

from __future__ import annotations

import logging
import uuid
import bpy
from bpy.props import StringProperty

from .hierarchy import (
    DEFAULT_WORLD_OBJECT_NAME,
    get_or_create_world_container,
    get_or_create_world_mesh_object,
)

logger = logging.getLogger("MoziToolKit.Sync.CreateWorld")


def switch_properties_tab_to_data(context=None):
    """Switch any visible Properties editor window to the DATA tab."""
    if context is None:
        context = getattr(bpy, "context", None)
    if not context:
        return
    try:
        wm = getattr(context, "window_manager", None) or getattr(bpy.context, "window_manager", None)
        windows = getattr(wm, "windows", []) if wm else []
        if not windows and getattr(context, "window", None):
            windows = [context.window]

        for win in windows:
            screen = getattr(win, "screen", None)
            if not screen:
                continue
            for area in screen.areas:
                if area.type == 'PROPERTIES':
                    for space in area.spaces:
                        if space.type == 'PROPERTIES':
                            space.context = 'DATA'
                            area.tag_redraw()
    except Exception as e:
        logger.debug("Failed switching properties tab to DATA: %s", e)


def switch_properties_tab_to_object(context=None):
    """Switch any visible Properties editor window to the OBJECT tab."""
    if context is None:
        context = getattr(bpy, "context", None)
    if not context:
        return
    try:
        wm = getattr(context, "window_manager", None) or getattr(bpy.context, "window_manager", None)
        windows = getattr(wm, "windows", []) if wm else []
        if not windows and getattr(context, "window", None):
            windows = [context.window]

        for win in windows:
            screen = getattr(win, "screen", None)
            if not screen:
                continue
            for area in screen.areas:
                if area.type == 'PROPERTIES':
                    for space in area.spaces:
                        if space.type == 'PROPERTIES':
                            space.context = 'OBJECT'
                            area.tag_redraw()
    except Exception as e:
        logger.debug("Failed switching properties tab to OBJECT: %s", e)


class MOZI_OT_add_yefira_world(bpy.types.Operator):
    """Create a new Yefira World Empty container for Minecraft Live Sync."""
    bl_idname = "mozi.add_yefira_world"
    bl_label = "New Live Sync Container"
    bl_description = "Create a new Empty container for Minecraft live synchronization"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(
        name="Name",
        description="Name of the Yefira World container object",
        default=DEFAULT_WORLD_OBJECT_NAME,
    )

    def execute(self, context):
        world_name = self.name.strip() if self.name.strip() else DEFAULT_WORLD_OBJECT_NAME

        # Deduplicate container name if exists
        final_name = world_name
        idx = 1
        while final_name in bpy.data.objects:
            final_name = f"{world_name}_{idx:02d}"
            idx += 1

        root_obj = bpy.data.objects.new(final_name, None)
        root_obj.empty_display_type = 'PLAIN_AXES'
        root_obj.empty_display_size = 1.0
        root_obj["mtk:is_yefira_world"] = True
        root_obj["mtk:is_container"] = True
        root_obj["mtk:container_type"] = "SYNC"
        root_obj["mtk:container_id"] = uuid.uuid4().hex
        root_obj["mtk:sync_manifest"] = "{}"
        root_obj["mtk:last_name"] = root_obj.name

        # Inherit default server URL
        if hasattr(root_obj, "mozi_sync"):
            scene_props = getattr(context.scene, "mozi_sync", None)
            root_obj.mozi_sync.url = scene_props.url if scene_props and scene_props.url else "ws://127.0.0.1:8765"

        # Place at 3D cursor or world origin
        if hasattr(context.scene, "cursor"):
            root_obj.location = context.scene.cursor.location
        else:
            root_obj.location = (0.0, 0.0, 0.0)

        coll = getattr(context, "collection", None) or context.scene.collection
        coll.objects.link(root_obj)

        # Pre-create child world mesh under root_obj
        get_or_create_world_mesh_object(context, root_container=root_obj)

        # Select root and make active
        if hasattr(context, "selected_objects"):
            for obj in list(context.selected_objects):
                obj.select_set(False)
        root_obj.select_set(True)
        if hasattr(context, "view_layer") and hasattr(context.view_layer, "objects"):
            context.view_layer.objects.active = root_obj

        switch_properties_tab_to_data(context)

        self.report({'INFO'}, f"Created Live Sync Container: {root_obj.name}")
        return {'FINISHED'}


class MOZI_OT_sync_select_root(bpy.types.Operator):
    """Select the parent Yefira World container object in the 3D Viewport."""
    bl_idname = "mozi.sync_select_root"
    bl_label = "Select Parent Container"
    bl_description = "Select the parent Yefira World Empty container object"
    bl_options = {'REGISTER', 'UNDO'}

    container_name: StringProperty(
        name="Container Name",
        description="Name of the root container object to select",
        default="",
    )

    def execute(self, context):
        target = bpy.data.objects.get(self.container_name)
        if target:
            if hasattr(context, "selected_objects"):
                for obj in list(context.selected_objects):
                    obj.select_set(False)
            target.select_set(True)
            if hasattr(context, "view_layer") and hasattr(context.view_layer, "objects"):
                context.view_layer.objects.active = target
            switch_properties_tab_to_data(context)
            self.report({'INFO'}, f"Selected parent container: {target.name}")
        return {'FINISHED'}


OPERATOR_CLASSES = (
    MOZI_OT_add_yefira_world,
    MOZI_OT_sync_select_root,
)
