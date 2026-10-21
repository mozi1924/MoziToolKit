"""
Render Engine Adaptation Hooks (standard PBR).

The v2.1 material graph has no per-engine transmission / thin-wall / sticker branches,
so there is nothing to rewrite when the scene switches between Cycles and EEVEE. These
handlers are kept as add-on lifecycle hooks for future standard-PBR adaptations
(for example an optional global subsurface override).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

_last_known_engine_by_scene: Dict[int, str] = {}


def update_materials_render_engine_adaptation(
    scene: Optional[Any] = None,
    detected_engine: Optional[str] = None,
    context: Optional[Any] = None,
) -> int:
    """No-op placeholder for future standard-PBR engine adaptations.

    Returns the number of updated materials (currently always 0).
    """
    return 0


@bpy.app.handlers.persistent
def depsgraph_render_engine_adaptation_handler(scene, depsgraph=None):
    """
    Lightweight depsgraph listener that triggers material adaptation when scene.render.engine changes.
    """
    if not scene or not hasattr(scene, "render"):
        return

    scene_id = hash(scene)
    current_engine = getattr(scene.render, "engine", "CYCLES")
    last_engine = _last_known_engine_by_scene.get(scene_id)

    if current_engine != last_engine:
        _last_known_engine_by_scene[scene_id] = current_engine
        update_materials_render_engine_adaptation(scene=scene, detected_engine=current_engine)


@bpy.app.handlers.persistent
def on_blend_file_loaded_engine_adaptation(scene=None, depsgraph=None):
    """Update material shading adaptations immediately when a .blend file finishes loading."""
    update_materials_render_engine_adaptation(scene=bpy.context.scene if bpy.context else None)


def register_render_engine_adaptation_handlers():
    """Register persistent depsgraph and file-load handlers for automatic engine adaptation."""
    if not HAS_BPY:
        return

    if depsgraph_render_engine_adaptation_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(depsgraph_render_engine_adaptation_handler)

    if on_blend_file_loaded_engine_adaptation not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_blend_file_loaded_engine_adaptation)


def unregister_render_engine_adaptation_handlers():
    """Unregister render engine adaptation handlers."""
    if not HAS_BPY:
        return

    if depsgraph_render_engine_adaptation_handler in bpy.app.handlers.depsgraph_update_post:
        try:
            bpy.app.handlers.depsgraph_update_post.remove(depsgraph_render_engine_adaptation_handler)
        except Exception:
            pass

    if on_blend_file_loaded_engine_adaptation in bpy.app.handlers.load_post:
        try:
            bpy.app.handlers.load_post.remove(on_blend_file_loaded_engine_adaptation)
        except Exception:
            pass
