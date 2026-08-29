"""
Yefira World Material and Direct Mesh Integration Module.

Provides object detection, block state parsing, and material slot helpers
for Yefira-based live sync Minecraft worlds.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional
import bpy

logger = logging.getLogger("MoziToolKit.Materials")

from pathlib import Path
from ...mc_baker import (
    StateBaker,
    get_shared_state_baker,
    refresh_shared_baker_sources,
    clear_shared_baker_cache,
    EMISSIVE_BLOCKS,
    is_block_emissive as _mc_is_block_emissive,
)
from ...live_sync.constants import (
    DEFAULT_WORLD_OBJECT_NAME,
)


def refresh_baker_sources() -> None:
    """Synchronize StateBaker resource loaders with the configured Resource Pack Stack."""
    refresh_shared_baker_sources()


EMISSIVE_BLOCK_NAMES = EMISSIVE_BLOCKS
HARDCODED_TINT_BLOCKS = {
    "spruce_leaves": (1.0, 1.0, 1.0, 1.0),
    "birch_leaves": (1.0, 1.0, 1.0, 1.0),
    "lily_pad": (1.0, 1.0, 1.0, 1.0),
    "redstone_wire": (1.0, 1.0, 1.0, 1.0),
}


def parse_block_state_str(state: str) -> tuple[str, dict[str, str]]:
    """Parse a serialized block state string into clean block name and properties dict."""
    state_clean = state.strip()
    bracket_idx = state_clean.find("[")
    if bracket_idx == -1:
        block_name = state_clean
        props = {}
    else:
        block_name = state_clean[:bracket_idx]
        props_str = state_clean[bracket_idx + 1:].rstrip("]")
        props = {}
        if props_str:
            for pair in props_str.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    props[k.strip()] = v.strip()
    block_name = block_name.removeprefix("minecraft:").removeprefix("block/")
    return block_name, props


def is_block_emissive(block_name: str, props: Optional[dict[str, str]] = None) -> int:
    """Return 1 if block/state is emissive (light emitting), else 0."""
    return 1 if _mc_is_block_emissive(block_name, props) else 0


def is_yefira_object(obj: Optional[bpy.types.Object]) -> bool:
    """Identify whether a Blender object is a Yefira live sync world object (root Empty or child section)."""
    if not obj:
        return False
    if obj.get("mtk:is_yefira_world") or obj.get("mtk:section_pos") is not None:
        return True
    if obj.name == DEFAULT_WORLD_OBJECT_NAME or obj.name.startswith("Yefira_World") or obj.name.startswith("Yefira_Section_"):
        return True
    if "_Section_" in obj.name:
        return True
    if obj.type == 'EMPTY' and any(c.get("mtk:section_pos") is not None or "_Section_" in c.name for c in obj.children):
        return True
    if obj.parent and (obj.parent.get("mtk:is_yefira_world") or obj.parent.name.startswith("Yefira_World") or obj.parent.name == DEFAULT_WORLD_OBJECT_NAME):
        return True
    return False


def has_yefira_objects(objects: Iterable[Optional[bpy.types.Object]]) -> bool:
    """Return True if any object in the given collection is a Yefira world."""
    return any(is_yefira_object(obj) for obj in objects if obj)


from .atlas_integration import (
    extract_atlas_parameters,
    find_active_atlas_material,
    find_all_atlas_chunk_materials,
    find_bound_atlas_material,
    get_or_create_atlas_material,
    parse_atlas_mapping,
    setup_material_slots_for_object,
)
