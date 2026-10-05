"""
Shading Configuration and Render Engine Adaptation Resolver.
Orchestrates Minecraft game semantics fallback, LabPBR gating, and Cycles/EEVEE adaptations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

try:
    from ...config import get_config_manager
except (ImportError, ValueError):
    try:
        from utils.config import get_config_manager
    except Exception:
        get_config_manager = None

logger = logging.getLogger(__name__)


def resolve_material_shading_config(
    clean_block: str,
    texture_key: Optional[str] = None,
    raw_props: Optional[Tuple[float, float, float, float]] = None,
    has_pbr: bool = False,
    render_engine: Optional[str] = None,
    enable_game_semantics: Optional[bool] = None,
    enable_transmission: Optional[bool] = None,
    enable_thin_wall: Optional[bool] = None,
    disable_subsurface: Optional[bool] = None,
    emission_override: Optional[float] = None,
    thin_wall_override: Optional[bool] = None,
    transmission_override: Optional[float] = None,
    sticker_threshold_override: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Resolve authoritative shader properties and EEVEE/Cycles settings.

    Returns dict with keys:
        - target_engine: "CYCLES" | "EEVEE"
        - is_eevee: bool
        - emission_strength: float
        - thin_wall: bool
        - transmission_weight: float
        - sticker_threshold: float
        - disable_subsurface: bool
        - use_raytrace_refraction: bool
    """
    # 1. Fetch user preferences if available
    settings = None
    if get_config_manager is not None:
        try:
            settings = get_config_manager().get_material_settings()
        except Exception:
            settings = None

    # 2. Determine target render engine ("CYCLES" vs "EEVEE")
    pref_engine = render_engine or (getattr(settings, "render_engine", "AUTO") if settings else "AUTO")
    if pref_engine == "AUTO":
        detected_engine = "CYCLES"
        if HAS_BPY and bpy.context and hasattr(bpy.context, "scene") and bpy.context.scene:
            eng = getattr(bpy.context.scene.render, "engine", "CYCLES")
            if eng in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}:
                detected_engine = "EEVEE"
            else:
                detected_engine = "CYCLES"
        target_engine = detected_engine
    else:
        target_engine = pref_engine.upper()

    is_eevee = (target_engine == "EEVEE")

    # 3. Base physical properties from catalog: [emission, thin_wall, transmission, sticker_threshold]
    props = raw_props or (0.0, 0.0, 0.0, 0.55)

    # 4. Minecraft Game Semantics & Emission
    # Rule: If PBR textures (_s) are present, uniform block emission is BYPASSED (0.0) so per-pixel texture takes full control.
    semantics_active = (
        enable_game_semantics
        if enable_game_semantics is not None
        else (getattr(settings, "enable_game_semantics", True) if settings else True)
    )

    if emission_override is not None:
        final_emission = float(emission_override)
    elif has_pbr:
        # PBR texture exists: bypass uniform emission
        final_emission = 0.0
    elif semantics_active:
        final_emission = float(props[0])
    else:
        final_emission = 0.0

    # 5. Transmission & Refraction (Glass / Water)
    # Rule: In EEVEE, physical transmission creates black overlapping artifacts and depth failure.
    # AUTO mode disables transmission in EEVEE and enables in Cycles.
    trans_mode = (
        "ENABLED" if enable_transmission is True
        else ("DISABLED" if enable_transmission is False
        else (getattr(settings, "transmission_mode", "AUTO") if settings else "AUTO"))
    )

    if transmission_override is not None:
        final_transmission = float(transmission_override)
    elif trans_mode == "DISABLED":
        final_transmission = 0.0
    elif trans_mode == "ENABLED":
        final_transmission = float(props[2])
    else:  # AUTO
        if is_eevee:
            final_transmission = 0.0  # EEVEE fallback to clean alpha blending
        else:
            final_transmission = float(props[2])

    final_sticker = (
        float(sticker_threshold_override)
        if sticker_threshold_override is not None
        else float(props[3])
    )

    # 6. Thin Wall (Foliage)
    tw_mode = (
        "ENABLED" if enable_thin_wall is True
        else ("DISABLED" if enable_thin_wall is False
        else (getattr(settings, "thin_wall_mode", "AUTO") if settings else "AUTO"))
    )

    if thin_wall_override is not None:
        final_thin_wall = bool(thin_wall_override)
    elif tw_mode == "DISABLED":
        final_thin_wall = False
    elif tw_mode == "ENABLED":
        final_thin_wall = bool(props[1] > 0.5)
    else:  # AUTO
        final_thin_wall = bool(props[1] > 0.5)

    # 7. Subsurface Scattering (SSS)
    pref_disable_sss = (
        disable_subsurface
        if disable_subsurface is not None
        else (getattr(settings, "disable_subsurface", False) if settings else False)
    )
    final_disable_sss = bool(pref_disable_sss)

    # 8. Refraction Raytracing on Blender Material
    use_raytrace = bool(final_transmission > 0.0 and not is_eevee)

    return {
        "target_engine": target_engine,
        "is_eevee": is_eevee,
        "emission_strength": final_emission,
        "thin_wall": final_thin_wall,
        "transmission_weight": final_transmission,
        "sticker_threshold": final_sticker,
        "disable_subsurface": final_disable_sss,
        "use_raytrace_refraction": use_raytrace,
    }
