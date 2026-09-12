"""
Material Preset Registry & Unified Alias Generator.
Builds structured alias lookup maps for passing to libmtk Rust core.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from .ice_cube import expand_ice_cube_candidates, is_ice_cube_internal_face
from .jmc2obj import expand_jmc2obj_candidates
from .mineways import expand_mineways_candidates


def detect_material_origin(material_name: str) -> str:
    """Heuristic auto-detection of importer format from a material name."""
    lower = material_name.strip().lower()
    if lower.startswith(("mineways", "mw_", "mwo_")) or lower.endswith("_y"):
        return "mineways"
    elif lower.startswith(("minecraft_block", "minecraft_entity", "minecraft_item", "jmc2obj", "pattern_")):
        return "jmc2obj"
    elif lower.startswith(("ice_cube", "icecube", "m_")):
        return "ice_cube"
    return "generic"


def generate_candidates_for_name(raw_name: str, origin: str = "auto") -> List[str]:
    """Generate prioritized candidate resource paths for a material name."""
    if not raw_name:
        return []

    orig = origin if origin != "auto" else detect_material_origin(raw_name)
    candidates: List[str] = []

    if orig == "jmc2obj":
        candidates.extend(expand_jmc2obj_candidates(raw_name))
    elif orig == "ice_cube":
        candidates.extend(expand_ice_cube_candidates(raw_name))
    elif orig == "mineways":
        candidates.extend(expand_mineways_candidates(raw_name))
    else:
        # Generic: query jmc2obj, icecube, mineways in priority order
        candidates.extend(expand_jmc2obj_candidates(raw_name))
        candidates.extend(expand_ice_cube_candidates(raw_name))
        candidates.extend(expand_mineways_candidates(raw_name))

    return list(dict.fromkeys(c for c in candidates if c))


def build_material_alias_map(
    material_names: List[str],
    origin: str = "auto",
) -> Dict[str, List[str]]:
    """
    Build a comprehensive alias mapping dictionary for a given set of raw material names.
    This dictionary is passed directly to Rust `libmtk` for zero-computation parallel resolution.
    """
    alias_map: Dict[str, List[str]] = {}
    for mat_name in material_names:
        if not mat_name or mat_name in alias_map:
            continue
        cands = generate_candidates_for_name(mat_name, origin=origin)
        if cands:
            alias_map[mat_name] = cands

    return alias_map


def build_matching_context(
    material_names: List[str],
    origin: str = "auto",
    atlas_size: tuple[int, int] = (1024, 1024),
) -> tuple[Dict[str, List[str]], Optional[object]]:
    """
    Assemble resolution aliases and optional GridAtlasSpec for a given set of mesh materials.
    Automatically detects whether GridAtlasSpec (Mineways) is required.

    Returns:
        (alias_map, grid_atlas_spec)
    """
    from .mineways import build_mineways_grid_spec
    from .mineways_table import MINEWAYS_ATLAS_NAME_PATTERNS

    alias_map = build_material_alias_map(material_names, origin=origin)
    has_grid_atlas = False

    if origin == "mineways":
        has_grid_atlas = True
    else:
        for name in material_names:
            clean = name.strip().lower()
            if any(pat in clean for pat in MINEWAYS_ATLAS_NAME_PATTERNS):
                has_grid_atlas = True
                break

    grid_spec = None
    if has_grid_atlas:
        grid_spec = build_mineways_grid_spec(atlas_size[0], atlas_size[1])

    return alias_map, grid_spec

