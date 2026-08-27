"""
Custom face skipping rules for specialized Minecraft blocks.
Directly replicates BlockBehaviour.skipRendering and its overrides in vanilla Minecraft.
"""

from __future__ import annotations
from typing import Optional, Tuple
from .types import (
    BlockCullMeta,
    CullCategory,
    LeavesCullMode,
    GlassCullMode,
    DIR_TO_MASK,
    DIR_MASK_EAST,
    DIR_MASK_UP,
    DIR_MASK_SOUTH,
)


def should_skip_rendering(
    state_meta: BlockCullMeta,
    neighbor_meta: BlockCullMeta,
    direction: str,
    leaves_mode: LeavesCullMode = LeavesCullMode.FAST,
    glass_mode: GlassCullMode = GlassCullMode.GROUP,
    block_pos: Optional[Tuple[int, int, int]] = None,
    neighbor_pos: Optional[Tuple[int, int, int]] = None,
) -> bool:

    """
    Evaluate BlockBehaviour.skipRendering(state, neighborState, direction).
    Returns True if this face should be skipped (culled), False otherwise.
    """
    if state_meta.is_air or neighbor_meta.is_air:
        return False

    cat_a = state_meta.category
    cat_b = neighbor_meta.category

    # 1. Glass & Translucent blocks (HalfTransparentBlock / TintedGlassBlock / Ice / Slime / Honey)
    if cat_a == CullCategory.GLASS_TRANSLUCENT:
        if cat_b == CullCategory.GLASS_TRANSLUCENT:
            if glass_mode == GlassCullMode.GROUP:
                # Any translucent in matching group (e.g. all glass variants, or same group)
                if state_meta.cull_group == neighbor_meta.cull_group:
                    return True
                # Stained glass of different colors: by default in GROUP mode, they cull boundary
                if state_meta.cull_group.startswith("glass") and neighbor_meta.cull_group.startswith("glass"):
                    return True
            elif glass_mode == GlassCullMode.SAME_BLOCK:
                # Vanilla HalfTransparentBlock.skipRendering: strictly same block
                if state_meta.block_name == neighbor_meta.block_name:
                    return True
        return False

    # 2. Cutout Leaves & Foliage (LeavesBlock)
    if cat_a == CullCategory.CUTOUT_LEAVES:
        if cat_b == CullCategory.CUTOUT_LEAVES:
            if leaves_mode == LeavesCullMode.FAST:
                # Fast mode: mutual culling between all leaves
                return True
            elif leaves_mode == LeavesCullMode.SINGLE_FACE:
                # Optimized Single-Face mode: keep exactly one face between touching leaves
                if block_pos is not None and neighbor_pos is not None:
                    # Deterministic canonical ordering (render face only from smaller pos coordinate)
                    return block_pos > neighbor_pos
                else:
                    # Directional tie-breaker
                    mask = DIR_TO_MASK.get(direction, 0)
                    return bool(mask & (DIR_MASK_EAST | DIR_MASK_UP | DIR_MASK_SOUTH))
            elif leaves_mode == LeavesCullMode.FANCY:
                # Fancy mode: keep both faces (vanilla cutoutLeaves=true)
                return False
            elif leaves_mode == LeavesCullMode.NONE:
                return False
        return False

    # 3. Fluids (LiquidBlock: Water / Lava)
    if cat_a == CullCategory.FLUID:
        if cat_b == CullCategory.FLUID:
            # Same fluid type (water vs water, lava vs lava) culls mutual boundary
            if state_meta.cull_group == neighbor_meta.cull_group:
                return True
        elif state_meta.cull_group == "water" and neighbor_meta.is_waterlogged:
            # Water against waterlogged block culls face
            return True
        return False

    # 4. Mangrove Roots (MangroveRootsBlock)
    if state_meta.block_name == "mangrove_roots" and neighbor_meta.block_name == "mangrove_roots":
        # Mangrove roots only cull in vertical Y axis
        if direction in ("up", "down", "top", "bottom"):
            return True

    # 5. Powder Snow (PowderSnowBlock)
    if state_meta.block_name == "powder_snow" and neighbor_meta.block_name == "powder_snow":
        return True

    return False
