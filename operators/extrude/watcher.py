"""
Real-time background polling, depsgraph listener, and deferred repair tick service.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Set

try:
    import bmesh
    import bpy
except ImportError:
    bmesh = None
    bpy = None

if bpy is None:
    class _DummyBpyApp:
        class handlers:
            depsgraph_update_post = []
            persistent = staticmethod(lambda f: f)
        class timers:
            @staticmethod
            def is_registered(func): return False
            @staticmethod
            def register(func, **kwargs): pass
            @staticmethod
            def unregister(func): pass
    class _DummyBpy:
        app = _DummyBpyApp
        context = None
    bpy = _DummyBpy()

try:
    from ...bridge.extrude import repair_extruded_side_faces
except (ImportError, ValueError):
    try:
        from ..bridge.extrude import repair_extruded_side_faces
    except (ImportError, ValueError):
        from bridge.extrude import repair_extruded_side_faces

logger = logging.getLogger("MoziToolKit.AutoExtrudeRepair.Watcher")

_smart_extrude_sessions: Dict[int, Dict[str, Set[int]]] = {}
_pending_repairs: Set[int] = set()
_is_updating: bool = False
_idle_ticks: int = 0
_SMART_EXTRUDE_POLL_INTERVAL = 0.03
_MAX_IDLE_TICKS = 5


def _is_uv_editing_active(context) -> bool:
    """Return True if the user is in or interacting with UV editing / Image Editor."""
    if not context:
        return False

    area = getattr(context, "area", None)
    if area and area.type == "IMAGE_EDITOR":
        return True

    space_data = getattr(context, "space_data", None)
    if space_data and getattr(space_data, "type", None) == "IMAGE_EDITOR":
        return True

    window = getattr(context, "window", None)
    if window:
        for op in getattr(window, "modal_operators", []):
            identifier = getattr(op, "bl_idname", "")
            if not identifier:
                bl_rna = getattr(op, "bl_rna", None)
                identifier = getattr(bl_rna, "identifier", "")
            identifier_upper = identifier.upper()
            if (
                identifier_upper.startswith("UV_OT_")
                or identifier_upper.startswith("IMAGE_OT_")
                or identifier_upper.startswith("CLIP_OT_")
                or identifier_upper.startswith("NODE_OT_")
            ):
                return True

    return False


def _is_extrude_operator_identifier(identifier: str) -> bool:
    """Return True if the operator identifier corresponds to a mesh face extrusion operation."""
    if not identifier:
        return False
    id_upper = identifier.upper()
    return (
        id_upper.startswith("MESH_OT_EXTRUDE")
        or id_upper.startswith("MESH_OT_DUPLI_EXTRUDE")
        or id_upper.startswith("MESH_OT_POLYBUILD_EXTRUDE")
        or "EXTRUDE" in id_upper
    )


def _is_extrude_in_progress(context) -> bool:
    """
    Return True only if an extrusion operator or an extrusion-related modal transform
    is actively running in the 3D Viewport.
    """
    if _is_uv_editing_active(context):
        return False

    window = getattr(context, "window", None)
    if not window:
        return False

    modal_ops = getattr(window, "modal_operators", [])
    if not modal_ops:
        return False

    for op in modal_ops:
        identifier = getattr(op, "bl_idname", "")
        if not identifier:
            bl_rna = getattr(op, "bl_rna", None)
            identifier = getattr(bl_rna, "identifier", "")
        id_upper = identifier.upper()
        if _is_extrude_operator_identifier(id_upper) or (
            id_upper.startswith("TRANSFORM_OT_") and _has_recent_extrude_operator(context)
        ):
            return True

    return False


def _has_recent_extrude_operator(context) -> bool:
    """Return True if the most recent executed operator was an extrusion."""
    window_manager = getattr(context, "window_manager", None)
    if not window_manager:
        return False
    recent_ops = getattr(window_manager, "operators", [])
    if recent_ops:
        for op in list(recent_ops)[-5:]:
            identifier = getattr(op, "bl_idname", "")
            if not identifier:
                bl_rna = getattr(op, "bl_rna", None)
                identifier = getattr(bl_rna, "identifier", "")
            if _is_extrude_operator_identifier(identifier):
                return True
    return False


def _deferred_extrude_repair_tick():
    """
    Safely executes auto extrude repair in Blender's main event loop (outside depsgraph evaluation).
    Polls while a modal extrusion/transform is active, and returns None to sleep when idle.
    """
    global _is_updating, _pending_repairs, _smart_extrude_sessions, _idle_ticks

    if _is_updating:
        return _SMART_EXTRUDE_POLL_INTERVAL

    context = bpy.context
    if not context or getattr(context, "mode", None) != "EDIT_MESH" or _is_uv_editing_active(context):
        _pending_repairs.clear()
        _smart_extrude_sessions.clear()
        _idle_ticks = 0
        return None

    props = getattr(context.scene, "mozi_auto_extrude_repair", None)
    if not props or not props.enabled or not (props.repair_uv or props.add_mean_crease):
        _pending_repairs.clear()
        _smart_extrude_sessions.clear()
        _idle_ticks = 0
        return None

    obj = context.active_object
    if not obj or obj.type != "MESH":
        _pending_repairs.clear()
        _smart_extrude_sessions.clear()
        _idle_ticks = 0
        return None

    repaired_count = 0
    try:
        _is_updating = True
        bm = bmesh.from_edit_mesh(obj.data)
        if props.uv_mode == "SMART":
            session = _smart_extrude_sessions.setdefault(
                obj.as_pointer(), {"side_face_indices": set()}
            )
            repaired_count = repair_extruded_side_faces(
                bm,
                obj=obj,
                context=context,
                repair_uv=props.repair_uv,
                add_crease=props.add_mean_crease,
                crease_val=props.crease_value,
                only_collapsed=True,
                uv_mode="SMART",
                smart_side_face_indices=session["side_face_indices"],
            )
        else:
            repaired_count = repair_extruded_side_faces(
                bm,
                obj=obj,
                context=context,
                repair_uv=props.repair_uv,
                add_crease=props.add_mean_crease,
                crease_val=props.crease_value,
                only_collapsed=True,
                uv_mode=props.uv_mode,
            )
        if repaired_count > 0:
            bmesh.update_edit_mesh(obj.data)
    except Exception as e:
        logger.error(f"Error in auto extrude repair tick: {e}", exc_info=True)
    finally:
        _is_updating = False

    _pending_repairs.discard(obj.as_pointer())

    # Keep polling continuously while extrusion/transform is in progress
    if _is_extrude_in_progress(context):
        _idle_ticks = 0
        return _SMART_EXTRUDE_POLL_INTERVAL
    elif _idle_ticks < _MAX_IDLE_TICKS:
        _idle_ticks += 1
        return _SMART_EXTRUDE_POLL_INTERVAL

    # Finished and idle: clean up and return None to automatically stop the timer
    _smart_extrude_sessions.clear()
    _pending_repairs.clear()
    _idle_ticks = 0
    return None


@bpy.app.handlers.persistent
def depsgraph_auto_extrude_repair_handler(scene, depsgraph):
    """
    Lightweight depsgraph listener: marks dirty objects and schedules deferred main-thread execution.
    Never modifies mesh data directly within depsgraph_update_post to prevent re-evaluation cascades.
    Guards against non-3D / UV editor updates to avoid interfering with UV transforms.
    """
    if _is_updating:
        return
    try:
        context = bpy.context
        if not context or context.mode != "EDIT_MESH":
            return

        # Do not run if active in UV Editor / Image Editor
        if _is_uv_editing_active(context):
            return

        props = getattr(scene, "mozi_auto_extrude_repair", None)
        if not props or not props.enabled or not (props.repair_uv or props.add_mean_crease):
            return

        obj = context.active_object
        if not obj or obj.type != "MESH":
            return

        # Check if an extrusion is actively in progress or recently executed
        if not (_is_extrude_in_progress(context) or _has_recent_extrude_operator(context)):
            return

        # Check if geometry was updated
        geo_updated = False
        for update in depsgraph.updates:
            if update.is_updated_geometry:
                geo_updated = True
                break

        if geo_updated or not depsgraph.updates:
            _pending_repairs.add(obj.as_pointer())
            if not bpy.app.timers.is_registered(_deferred_extrude_repair_tick):
                bpy.app.timers.register(_deferred_extrude_repair_tick, first_interval=0.001, persistent=True)
    except Exception as e:
        logger.error(f"Error in depsgraph_auto_extrude_repair_handler: {e}", exc_info=True)


def register():
    if depsgraph_auto_extrude_repair_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(depsgraph_auto_extrude_repair_handler)


def unregister():
    if depsgraph_auto_extrude_repair_handler in bpy.app.handlers.depsgraph_update_post:
        try:
            bpy.app.handlers.depsgraph_update_post.remove(depsgraph_auto_extrude_repair_handler)
        except Exception:
            pass
    if bpy.app.timers.is_registered(_deferred_extrude_repair_tick):
        try:
            bpy.app.timers.unregister(_deferred_extrude_repair_tick)
        except Exception:
            pass
    _smart_extrude_sessions.clear()
    _pending_repairs.clear()
