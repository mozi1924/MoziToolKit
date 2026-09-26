"""
MoziToolKit Live Sync Operators Subpackage.
"""

from .properties import (
    MoziSyncPaletteItem,
    MoziSyncDeltaItem,
    MoziSyncProperties,
    register as register_properties,
    unregister as unregister_properties,
)
from .op_sync_connect import OPERATOR_CLASSES as CONNECT_CLASSES
from .op_sync_rebuild import OPERATOR_CLASSES as REBUILD_CLASSES
from .op_sync_clear_history import OPERATOR_CLASSES as CLEAR_CLASSES

OPERATOR_CLASSES = (
    CONNECT_CLASSES
    + REBUILD_CLASSES
    + CLEAR_CLASSES
)


def register():
    register_properties()
    for cls in OPERATOR_CLASSES:
        import bpy
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(OPERATOR_CLASSES):
        try:
            import bpy
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    unregister_properties()
