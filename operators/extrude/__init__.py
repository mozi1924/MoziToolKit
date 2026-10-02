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
from .op_auto_extrude_repair import OPERATOR_CLASSES as AUTO_REPAIR_CLASSES
from .op_random_extrude import OPERATOR_CLASSES as RANDOM_EXTRUDE_CLASSES

OPERATOR_CLASSES = (
    PROPERTY_CLASSES
    + tuple(AUTO_REPAIR_CLASSES)
    + tuple(RANDOM_EXTRUDE_CLASSES)
)


def register():
    register_properties()
    register_watcher()


def unregister():
    unregister_watcher()
    unregister_properties()
