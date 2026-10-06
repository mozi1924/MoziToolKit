"""
MoziToolKit Extrude Operators Subpackage.
"""

from .properties import (
    UV_MODE_ITEMS,
    NOISE_TYPE_ITEMS,
    MOZI_PG_auto_extrude_repair,
    PROPERTY_CLASSES,
    register as register_properties,
    unregister as unregister_properties,
)
from .watcher import (
    register as register_watcher,
    unregister as unregister_watcher,
)
from .op_auto_extrude_repair import (
    MOZI_OT_auto_extrude_repair,
    OPERATOR_CLASSES as AUTO_REPAIR_CLASSES,
)
from .op_random_extrude import (
    MOZI_OT_random_extrude,
    OPERATOR_CLASSES as RANDOM_EXTRUDE_CLASSES,
)

OPERATOR_CLASSES = (
    PROPERTY_CLASSES
    + tuple(AUTO_REPAIR_CLASSES)
    + tuple(RANDOM_EXTRUDE_CLASSES)
)

__all__ = [
    "UV_MODE_ITEMS",
    "NOISE_TYPE_ITEMS",
    "MOZI_PG_auto_extrude_repair",
    "PROPERTY_CLASSES",
    "MOZI_OT_auto_extrude_repair",
    "MOZI_OT_random_extrude",
    "AUTO_REPAIR_CLASSES",
    "RANDOM_EXTRUDE_CLASSES",
    "OPERATOR_CLASSES",
    "register",
    "unregister",
]


def register():
    register_properties()
    register_watcher()


def unregister():
    unregister_watcher()
    unregister_properties()
