"""
Procedural model registry and dispatcher for Minecraft blocks without JSON elements.
"""

from __future__ import annotations
from typing import Optional, Callable

from .chest import build_chest_elements
from .shulker_box import build_shulker_box_elements
from .banner import build_banner_elements
from .bed import build_bed_elements
from .skull import build_skull_elements
from .conduit import build_conduit_elements
from .decorated_pot import build_decorated_pot_elements
from .bell import build_bell_elements
from .end_portal import build_end_portal_elements


def is_chest_block(short_name: str) -> bool:
    name = short_name.removeprefix("waxed_")
    return name in (
        "chest", "trapped_chest", "ender_chest",
        "copper_chest", "exposed_copper_chest",
        "weathered_copper_chest", "oxidized_copper_chest",
    )


def is_shulker_block(short_name: str) -> bool:
    return short_name == "shulker_box" or short_name.endswith("_shulker_box")


def is_banner_block(short_name: str) -> bool:
    return short_name.endswith(("_banner", "_wall_banner"))


def is_bed_block(short_name: str) -> bool:
    return short_name.endswith("_bed")


def is_skull_block(short_name: str) -> bool:
    return short_name.endswith(("_head", "_skull", "_wall_head", "_wall_skull"))


def get_procedural_elements(
    block_id: str,
    props: dict[str, str],
    fallback_texture: str = "",
    resolved_model: Optional[dict] = None
) -> Optional[list[dict]]:
    """
    Resolve and construct procedural 3D elements for blocks that rely on
    pure-code rendering rather than static JSON model elements.
    Returns None if the block is not a recognized procedural model.
    """
    short_name = block_id.split(":", 1)[-1]

    # 1. Chests
    if is_chest_block(short_name):
        return build_chest_elements(short_name, props)

    # 2. Shulker Boxes
    if is_shulker_block(short_name):
        return build_shulker_box_elements(short_name, props)

    # 3. Banners
    if is_banner_block(short_name):
        return build_banner_elements(short_name, props)

    # 4. Beds
    if is_bed_block(short_name):
        return build_bed_elements(short_name, props)

    # 5. Skulls / Heads
    if is_skull_block(short_name):
        return build_skull_elements(short_name, props)

    # 6. Conduit
    if short_name == "conduit":
        return build_conduit_elements(short_name, props)

    # 7. Decorated Pot
    if short_name == "decorated_pot":
        return build_decorated_pot_elements(short_name, props)

    # 8. Bell
    if short_name == "bell":
        return build_bell_elements(short_name, props)

    # 9. End Portal / Gateway
    if short_name in ("end_portal", "end_gateway"):
        return build_end_portal_elements(short_name, props)

    return None
