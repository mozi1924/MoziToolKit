"""
Operator to clear delta change history log in MoziToolKit Live Sync.
"""

from __future__ import annotations

import bpy
from .op_sync_connect import get_active_sync_props


class MOZI_OT_sync_clear_history(bpy.types.Operator):
    bl_idname = "mozi.sync_clear_history"
    bl_label = "Clear History"
    bl_description = "Clear all entries from the live delta change history log"

    def execute(self, context):
        props = get_active_sync_props(context)
        if props:
            props.delta_history.clear()
            self.report({'INFO'}, "Cleared delta change history.")
        return {'FINISHED'}
