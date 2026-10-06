"""
Depsgraph update watcher for Live Sync.
Monitors Empty container rename events and cascades names to child mesh and point clouds.
Guards against Edit Mode conflicts while synchronization is actively connected.
"""

from __future__ import annotations

import logging
from typing import Set
import bpy

try:
    from .hierarchy import (
        is_yefira_root_object,
        sync_container_child_names,
    )
    from .properties import get_active_sync_container, set_active_sync_container
except (ImportError, ValueError):
    from operators.sync.hierarchy import (
        is_yefira_root_object,
        sync_container_child_names,
    )
    from operators.sync.properties import get_active_sync_container, set_active_sync_container

logger = logging.getLogger("MoziToolKit.Sync.Watcher")

_pending_rename_roots: Set[str] = set()


def _get_pending_rename_roots() -> Set[str]:
    global _pending_rename_roots
    return _pending_rename_roots


def _deferred_sync_renamed_roots(scene: Optional[bpy.types.Scene] = None) -> None:
    """Execute rename propagation safely on Blender's main event queue outside depsgraph evaluation."""
    pending = _get_pending_rename_roots()
    if not pending:
        return None
    root_names = list(pending)
    pending.clear()

    target_scenes = []
    if scene is not None:
        target_scenes.append(scene)
    elif bpy.context and hasattr(bpy.context, "scene") and bpy.context.scene:
        target_scenes.append(bpy.context.scene)
    if hasattr(bpy, "data") and hasattr(bpy.data, "scenes"):
        scenes_coll = bpy.data.scenes.values() if hasattr(bpy.data.scenes, "values") else bpy.data.scenes
        for s in scenes_coll:
            if s and s not in target_scenes:
                target_scenes.append(s)

    for name in root_names:
        if not hasattr(bpy, "data") or not hasattr(bpy.data, "objects"):
            continue
        obj = bpy.data.objects.get(name) if hasattr(bpy.data.objects, "get") else None
        if obj and getattr(obj, "type", "") == 'EMPTY' and is_yefira_root_object(obj):
            last_name = None
            if hasattr(obj, "get"):
                last_name = obj.get("mtk:last_name")
            else:
                last_name = getattr(obj, "mtk:last_name", None)

            sync_container_child_names(obj)

            # Update scene active container reference if it was pointing to the old name
            for s in target_scenes:
                if hasattr(s, "mozi_active_sync_container_name"):
                    if last_name and s.mozi_active_sync_container_name == last_name:
                        s.mozi_active_sync_container_name = obj.name

            logger.info("Cascaded rename from '%s' to '%s' for children of container", last_name, obj.name)
    return None


def _deferred_enforce_object_mode() -> None:
    """Safely switch back to Object Mode on Blender's main event queue outside depsgraph evaluation."""
    if not bpy.context:
        return None
    active_obj = getattr(bpy.context, "active_object", None)
    if bpy.context.mode == 'EDIT_MESH' or (active_obj and getattr(active_obj, "mode", None) == 'EDIT'):
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception as e:
            logger.debug("Failed returning to Object Mode: %s", e)
    return None


def _safe_persistent(fn):
    """Safely apply bpy.app.handlers.persistent without being replaced by MagicMock."""
    if hasattr(bpy, "app") and hasattr(bpy.app, "handlers") and hasattr(bpy.app.handlers, "persistent"):
        p = bpy.app.handlers.persistent
        if callable(p) and not str(type(p)).endswith("MagicMock'>"):
            return p(fn)
    return fn


@_safe_persistent
def on_sync_depsgraph_update_post(scene, depsgraph) -> None:
    """
    Non-blocking depsgraph listener.
    Detects container renames in the Outliner and guards against Edit Mode while Live Sync is streaming.
    """
    if not depsgraph or not hasattr(depsgraph, "updates"):
        return

    try:
        # 1. Guard against Edit Mode while Live Sync is actively connected
        active_container = get_active_sync_container(scene)
        is_connected = False
        if active_container and hasattr(active_container, "mozi_sync"):
            is_connected = getattr(active_container.mozi_sync, "is_connected", False)

        if is_connected and bpy.context:
            active_obj = getattr(bpy.context, "active_object", None)
            if bpy.context.mode == 'EDIT_MESH' or (active_obj and getattr(active_obj, "mode", None) == 'EDIT'):
                if hasattr(bpy.app, "timers") and not bpy.app.timers.is_registered(_deferred_enforce_object_mode):
                    bpy.app.timers.register(_deferred_enforce_object_mode, first_interval=0.0)

        # 2. Check for renamed Empty container objects via depsgraph updates
        for update in depsgraph.updates:
            target = getattr(update, "id", None)
            if target and getattr(target, "type", "") == 'EMPTY':
                is_root = is_yefira_root_object(target)
                if is_root:
                    last_name = None
                    if hasattr(target, "get"):
                        last_name = target.get("mtk:last_name")
                    else:
                        last_name = getattr(target, "mtk:last_name", None)

                    if last_name and last_name != target.name:
                        _get_pending_rename_roots().add(target.name)
                        if hasattr(bpy.app, "timers") and not bpy.app.timers.is_registered(_deferred_sync_renamed_roots):
                            bpy.app.timers.register(_deferred_sync_renamed_roots, first_interval=0.0)
    except Exception as e:
        logger.debug("Error in Live Sync depsgraph handler: %s", e)


def register():
    """Register depsgraph update post handler."""
    if hasattr(bpy.app, "handlers") and hasattr(bpy.app.handlers, "depsgraph_update_post"):
        if on_sync_depsgraph_update_post not in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.append(on_sync_depsgraph_update_post)


def unregister():
    """Unregister depsgraph update post handler and cancel pending timer callbacks."""
    if hasattr(bpy.app, "handlers") and hasattr(bpy.app.handlers, "depsgraph_update_post"):
        if on_sync_depsgraph_update_post in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(on_sync_depsgraph_update_post)

    if hasattr(bpy.app, "timers"):
        if bpy.app.timers.is_registered(_deferred_sync_renamed_roots):
            try:
                bpy.app.timers.unregister(_deferred_sync_renamed_roots)
            except Exception:
                pass
        if bpy.app.timers.is_registered(_deferred_enforce_object_mode):
            try:
                bpy.app.timers.unregister(_deferred_enforce_object_mode)
            except Exception:
                pass

    _get_pending_rename_roots().clear()
