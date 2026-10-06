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

    def execute(self, context):
        props = getattr(context.scene, "mozi_sync", None)
        if props:
            props.delta_history.clear()
        self.report({'INFO'}, "Delta history cleared.")
        return {'FINISHED'}


OPERATOR_CLASSES = (
    MOZI_OT_sync_clear_history,
)
