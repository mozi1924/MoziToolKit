"""
Auto Extrude UV Repair and Random Extrude Operators for MoziToolKit.

Modularized under operators/extrude/. This module provides backward-compatible
re-exports of all properties, watcher services, and operators.
"""

from __future__ import annotations

try:
    from .extrude.properties import (
        NOISE_TYPE_ITEMS,
        UV_MODE_ITEMS,
        MOZI_PG_auto_extrude_repair,
        PROPERTY_CLASSES,
        register as register_properties,
        unregister as unregister_properties,
    )
    from .extrude.watcher import (
        _MAX_IDLE_TICKS,
        _SMART_EXTRUDE_POLL_INTERVAL,
        _deferred_extrude_repair_tick,
        _has_recent_extrude_operator,
        _idle_ticks,
        _is_extrude_in_progress,
        _is_extrude_operator_identifier,
        _is_updating,
        _is_uv_editing_active,
        _pending_repairs,
        _smart_extrude_sessions,
        depsgraph_auto_extrude_repair_handler,
        register as register_watcher,
        unregister as unregister_watcher,
    )
    from .extrude.op_auto_extrude_repair import (
        MOZI_OT_auto_extrude_repair,
        OPERATOR_CLASSES as AUTO_REPAIR_CLASSES,
    )
    from .extrude.op_random_extrude import (
        MOZI_OT_random_extrude,
        OPERATOR_CLASSES as RANDOM_EXTRUDE_CLASSES,
    )
    from .extrude import OPERATOR_CLASSES, register, unregister
except (ImportError, ValueError):
    from operators.extrude.properties import (
        NOISE_TYPE_ITEMS,
        UV_MODE_ITEMS,
        MOZI_PG_auto_extrude_repair,
        PROPERTY_CLASSES,
        register as register_properties,
        unregister as unregister_properties,
    )
    from operators.extrude.watcher import (
        _MAX_IDLE_TICKS,
        _SMART_EXTRUDE_POLL_INTERVAL,
        _deferred_extrude_repair_tick,
        _has_recent_extrude_operator,
        _idle_ticks,
        _is_extrude_in_progress,
        _is_extrude_operator_identifier,
        _is_updating,
        _is_uv_editing_active,
        _pending_repairs,
        _smart_extrude_sessions,
        depsgraph_auto_extrude_repair_handler,
        register as register_watcher,
        unregister as unregister_watcher,
    )
    from operators.extrude.op_auto_extrude_repair import (
        MOZI_OT_auto_extrude_repair,
        OPERATOR_CLASSES as AUTO_REPAIR_CLASSES,
    )
    from operators.extrude.op_random_extrude import (
        MOZI_OT_random_extrude,
        OPERATOR_CLASSES as RANDOM_EXTRUDE_CLASSES,
    )
    from operators.extrude import OPERATOR_CLASSES, register, unregister

__all__ = [
    "UV_MODE_ITEMS",
    "NOISE_TYPE_ITEMS",
    "MOZI_PG_auto_extrude_repair",
    "PROPERTY_CLASSES",
    "_smart_extrude_sessions",
    "_pending_repairs",
    "_is_updating",
    "_idle_ticks",
    "_SMART_EXTRUDE_POLL_INTERVAL",
    "_MAX_IDLE_TICKS",
    "_is_uv_editing_active",
    "_is_extrude_operator_identifier",
    "_is_extrude_in_progress",
    "_has_recent_extrude_operator",
    "_deferred_extrude_repair_tick",
    "depsgraph_auto_extrude_repair_handler",
    "MOZI_OT_auto_extrude_repair",
    "MOZI_OT_random_extrude",
    "AUTO_REPAIR_CLASSES",
    "RANDOM_EXTRUDE_CLASSES",
    "OPERATOR_CLASSES",
    "register_properties",
    "unregister_properties",
    "register_watcher",
    "unregister_watcher",
    "register",
    "unregister",
]
