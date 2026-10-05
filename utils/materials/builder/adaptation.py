"""
Real-time Render Engine Adaptation Service.
Monitors scene render engine changes (Cycles <-> EEVEE) and updates material shader
trees (Transmission scale, Thin Wall, Subsurface Scattering) dynamically in real time.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

try:
    from .shading_config import resolve_material_shading_config
    from ...config import get_config_manager
except (ImportError, ValueError):
    try:
        from utils.materials.builder.shading_config import resolve_material_shading_config
        from utils.config import get_config_manager
    except Exception:
        resolve_material_shading_config = None
        get_config_manager = None

logger = logging.getLogger(__name__)

_is_updating_adaptation: bool = False
_last_known_engine_by_scene: Dict[int, str] = {}


def update_materials_render_engine_adaptation(
    scene: Optional[Any] = None,
    detected_engine: Optional[str] = None,
    context: Optional[Any] = None,
) -> int:
    """
    Updates all MTK materials in the blend file according to the active scene render engine.
    Returns the number of updated materials.
    """
    if not HAS_BPY or not hasattr(bpy, "data") or not hasattr(bpy.data, "materials"):
        return 0

    global _is_updating_adaptation
    if _is_updating_adaptation:
        return 0

    _is_updating_adaptation = True
    updated_count = 0

    try:
        # 1. Fetch user material preferences
        settings = None
        if get_config_manager is not None:
            try:
                settings = get_config_manager().get_material_settings()
            except Exception:
                settings = None

        pref_engine = getattr(settings, "render_engine", "AUTO") if settings else "AUTO"
        trans_mode = getattr(settings, "transmission_mode", "AUTO") if settings else "AUTO"
        disable_sss = getattr(settings, "disable_subsurface", False) if settings else False

        # 2. Determine target engine
        active_scene = scene or (bpy.context.scene if bpy.context else None)
        engine_str = detected_engine
        if not engine_str and active_scene and hasattr(active_scene, "render"):
            engine_str = getattr(active_scene.render, "engine", "CYCLES")

        if pref_engine == "AUTO":
            is_eevee = bool(engine_str in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"})
            target_engine = "EEVEE" if is_eevee else "CYCLES"
        else:
            target_engine = pref_engine.upper()
            is_eevee = (target_engine == "EEVEE")

        # 3. Calculate target transmission scale for Atlas materials
        if is_eevee or trans_mode == "DISABLED":
            atlas_trans_scale = 0.0
        else:
            atlas_trans_scale = 1.0

        # 4. Iterate over all MTK materials and apply adaptations
        for mat in bpy.data.materials:
            if not mat or not getattr(mat, "node_tree", None):
                continue

            mat_name = getattr(mat, "name", "")
            mat_mode = mat.get("mtk_material_mode")

            # Check if this is an MTK material
            is_atlas = (mat_mode == "ATLAS" or mat_name.startswith("MTK:Atlas:"))
            is_standalone = (mat_mode == "STANDALONE" or (mat_name.startswith("MTK:") and not is_atlas))

            if not is_atlas and not is_standalone and not mat_name.startswith("MTK:"):
                continue

            nodes = mat.node_tree.nodes

            if is_atlas:
                # Update Material Transmission Scale node
                scale_node = nodes.get("Material Transmission Scale")
                if scale_node and hasattr(scale_node, "inputs") and len(scale_node.inputs) > 1:
                    if scale_node.inputs[1].default_value != atlas_trans_scale:
                        scale_node.inputs[1].default_value = atlas_trans_scale
                        updated_count += 1

                # Update LabPBR Decoder SSS
                decoder_node = nodes.get("LabPBR Decoder")
                if decoder_node and hasattr(decoder_node, "inputs"):
                    if "Disable Subsurface" in decoder_node.inputs:
                        if decoder_node.inputs["Disable Subsurface"].default_value != bool(disable_sss):
                            decoder_node.inputs["Disable Subsurface"].default_value = bool(disable_sss)
                            updated_count += 1

            elif is_standalone:
                tex_key = mat.get("mtk_source_texture_key")
                clean_block = tex_key or mat_name.replace("MTK:", "")

                if resolve_material_shading_config is not None:
                    try:
                        cfg = resolve_material_shading_config(
                            clean_block=clean_block,
                            texture_key=tex_key,
                            render_engine=target_engine,
                        )
                        trans_weight = cfg.get("transmission_weight", 0.0)
                        cfg_disable_sss = cfg.get("disable_subsurface", False)

                        decoder_node = nodes.get("LabPBR Decoder")
                        if decoder_node and hasattr(decoder_node, "inputs"):
                            if "Transmission Weight" in decoder_node.inputs:
                                if decoder_node.inputs["Transmission Weight"].default_value != trans_weight:
                                    decoder_node.inputs["Transmission Weight"].default_value = trans_weight
                                    updated_count += 1
                            if "Disable Subsurface" in decoder_node.inputs:
                                if decoder_node.inputs["Disable Subsurface"].default_value != bool(cfg_disable_sss):
                                    decoder_node.inputs["Disable Subsurface"].default_value = bool(cfg_disable_sss)
                                    updated_count += 1
                        else:
                            bsdf_node = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
                            if bsdf_node and "Transmission Weight" in bsdf_node.inputs:
                                if bsdf_node.inputs["Transmission Weight"].default_value != trans_weight:
                                    bsdf_node.inputs["Transmission Weight"].default_value = trans_weight
                                    updated_count += 1
                    except Exception as e:
                        logger.debug("Failed updating standalone shading config for %s: %s", mat_name, e)

    except Exception as e:
        logger.warning("Error during real-time render engine material adaptation: %s", e)
    finally:
        _is_updating_adaptation = False

    return updated_count


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
