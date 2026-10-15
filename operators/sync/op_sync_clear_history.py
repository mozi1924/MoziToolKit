"""
Operator to clear live sync delta history logs.
"""

from __future__ import annotations

import bpy


class MOZI_OT_sync_clear_history(bpy.types.Operator):
    """Clear all delta modification log entries."""
    bl_idname = "mozi.sync_clear_history"
    bl_label = "Clear Log"
    bl_description = "Clear the recorded delta update modification history"
    bl_options = {'REGISTER', 'UNDO'}

    target_container: bpy.props.StringProperty(
        name="Target Container",
        description="Name of the root Empty container to clear history",
        default="",
    )

    def execute(self, context):
        target_obj = None
        if self.target_container and self.target_container in bpy.data.objects:
            target_obj = bpy.data.objects[self.target_container]

        cleared = False
        if target_obj and hasattr(target_obj, "mozi_sync"):
            target_obj.mozi_sync.delta_history.clear()
            cleared = True

        scene_props = getattr(context.scene, "mozi_sync", None)
        if scene_props and hasattr(scene_props, "delta_history"):
            scene_props.delta_history.clear()
            cleared = True

        self.report({'INFO'}, "Delta history cleared.")
        return {'FINISHED'}


OPERATOR_CLASSES = (
    MOZI_OT_sync_clear_history,
)
