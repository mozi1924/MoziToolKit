"""
Shading Configuration Resolver (MtkPackedV1).

Only two material-level adaptations remain:

- ``disable_subsurface``: global override that skips the aux.B -> Subsurface Weight link.
- ``emission_strength``: constant multiplier applied to the per-texel emission mask.

Game semantics (thin wall / transmission / sticker / hardcoded emission) were removed in
v2.1; glass and liquids currently rely on albedo alpha only. See
``MoziToolKit/docs/materials/pbr_channel_spec.md`` §6.
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

from ...config import get_config_manager

logger = logging.getLogger(__name__)

DEFAULT_EMISSION_STRENGTH = 5.0
DEFAULT_SUBSURFACE_SCALE = 0.1


def resolve_material_shading_config(
    render_engine: Optional[str] = None,
    disable_subsurface: Optional[bool] = None,
    emission_strength: Optional[float] = None,
) -> Dict[str, Any]:
    """Resolve the remaining standard-PBR material settings.

    Returns:
        - ``target_engine``: ``"CYCLES"`` or ``"EEVEE"``
        - ``is_eevee``: bool
        - ``disable_subsurface``: bool
        - ``emission_strength``: float
        - ``subsurface_scale``: float
    """
    settings = None
    if get_config_manager is not None:
        try:
            settings = get_config_manager().get_material_settings()
        except Exception:
            settings = None

    pref_engine = render_engine or (
        getattr(settings, "render_engine", "AUTO") if settings else "AUTO"
    )
    if pref_engine == "AUTO":
        detected_engine = "CYCLES"
        if HAS_BPY and bpy.context and hasattr(bpy.context, "scene") and bpy.context.scene:
            engine = getattr(bpy.context.scene.render, "engine", "CYCLES")
            if engine in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}:
                detected_engine = "EEVEE"
        target_engine = detected_engine
    else:
        target_engine = str(pref_engine).upper()

    final_disable_sss = (
        bool(disable_subsurface)
        if disable_subsurface is not None
        else bool(getattr(settings, "disable_subsurface", False) if settings else False)
    )

    final_emission = (
        float(emission_strength)
        if emission_strength is not None
        else DEFAULT_EMISSION_STRENGTH
    )

    subsurface_method = (
        getattr(settings, "subsurface_method", "BURLEY") if settings else "BURLEY"
    )
    if subsurface_method not in {"BURLEY", "RANDOM_WALK"}:
        subsurface_method = "BURLEY"

    return {
        "target_engine": target_engine,
        "is_eevee": target_engine == "EEVEE",
        "disable_subsurface": final_disable_sss,
        "emission_strength": final_emission,
        "subsurface_scale": DEFAULT_SUBSURFACE_SCALE,
        "subsurface_method": subsurface_method,
    }
