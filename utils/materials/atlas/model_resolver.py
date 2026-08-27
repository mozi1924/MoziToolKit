"""
Minecraft Block and Item model JSON texture variable resolver.
Maps model inheritance hierarchy and #variable references to canonical face textures.
"""

from __future__ import annotations

from typing import Dict, Any


def resolve_model_textures(models: Dict[str, Any], model_name: str, depth: int = 0) -> dict:
    """Recursively resolve texture variables from block model JSONs."""
    if depth > 10 or model_name not in models:
        return {}
    m = models[model_name]
    res = {}

    parent = m.get("parent")
    if parent and isinstance(parent, str):
        parent_clean = parent.replace("minecraft:block/", "").replace("block/", "").lower()
        res.update(resolve_model_textures(models, parent_clean, depth + 1))

    texs = m.get("textures", {})
    if isinstance(texs, dict):
        for k, v in texs.items():
            if isinstance(v, str):
                res[k] = v.replace("minecraft:block/", "").replace("block/", "").lower()
    return res


def expand_variables(tex_dict: dict) -> dict:
    """Resolve #variable references in texture dictionary."""
    resolved = dict(tex_dict)
    for _ in range(5):
        changed = False
        for k, v in list(resolved.items()):
            if v.startswith("#"):
                var_key = v[1:]
                if var_key in resolved and not resolved[var_key].startswith("#"):
                    resolved[k] = resolved[var_key]
                    changed = True
        if not changed:
            break
    return resolved


def get_6_faces_for_model(models: Dict[str, Any], model_name: str) -> dict:
    """
    Map block model to 6 face sub-textures:
    +X (East), -X (West), +Y (Up), -Y (Down), +Z (South), -Z (North).
    """
    raw_texs = resolve_model_textures(models, model_name)
    exp = expand_variables(raw_texs)

    fallback = list(exp.values())[0] if exp else model_name
    east = exp.get("east") or exp.get("side") or exp.get("all") or fallback
    west = exp.get("west") or exp.get("side") or exp.get("all") or east
    up = exp.get("up") or exp.get("top") or exp.get("end") or exp.get("all") or east
    down = exp.get("down") or exp.get("bottom") or exp.get("end") or exp.get("all") or east
    south = exp.get("south") or exp.get("side") or exp.get("all") or east
    north = exp.get("north") or exp.get("side") or exp.get("front") or exp.get("all") or east

    return {
        "+X": east,
        "-X": west,
        "+Y": up,
        "-Y": down,
        "+Z": south,
        "-Z": north
    }
