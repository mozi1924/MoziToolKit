"""
Operator to create a Yefira World Empty container for live synchronization.
"""

from __future__ import annotations

import bpy
from bpy.props import StringProperty
from ...utils.live_sync.constants import DEFAULT_WORLD_OBJECT_NAME


class MOZI_OT_add_yefira_world(bpy.types.Operator):
    """Create a new Yefira World Empty container for Minecraft Live Sync."""
    bl_idname = "mozi.add_yefira_world"
    bl_label = "Yefira World"
    bl_description = "Create a new Yefira World Empty container for Minecraft live synchronization"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(
        name="Name",
        description="Name of the Yefira World container object",
        default=DEFAULT_WORLD_OBJECT_NAME,
    )

    def execute(self, context):
        world_name = self.name if self.name.strip() else DEFAULT_WORLD_OBJECT_NAME
        root_obj = bpy.data.objects.new(world_name, None)
        root_obj.empty_display_type = 'PLAIN_AXES'
        root_obj.empty_display_size = 1.0
        root_obj["mtk:is_yefira_world"] = True
        root_obj["mtk:sync_manifest"] = "{}"

        # Place at 3D cursor or world origin
        if hasattr(context.scene, "cursor"):
            root_obj.location = context.scene.cursor.location
        else:
            root_obj.location = (0.0, 0.0, 0.0)

        context.collection.objects.link(root_obj)

        # Select and make active
        for obj in context.selected_objects:
            obj.select_set(False)
        root_obj.select_set(True)
        context.view_layer.objects.active = root_obj

        self.report({'INFO'}, f"Created Yefira World Empty: {root_obj.name}")
        return {'FINISHED'}
