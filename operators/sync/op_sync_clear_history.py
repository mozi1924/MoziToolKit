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

    target_container: bpy.props.StringProperty(name="Target Container", default="")

    def execute(self, context):
        target_obj = None
        if self.target_container:
            target_obj = bpy.data.objects.get(self.target_container)
        props = get_active_sync_props(context, target_obj=target_obj)
        if props:
            props.delta_history.clear()
            self.report({'INFO'}, "Cleared delta change history.")
        return {'FINISHED'}
