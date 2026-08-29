"""
Data types, enums, and structures for the Unified Face Culling System.
"""

from __future__ import annotations
from enum import Enum, auto
from typing import NamedTuple, Optional, Tuple, Dict, Any


class CullCategory(Enum):
    """Categorization of blocks for Minecraft face culling behavior."""
    SOLID_OPAQUE = auto()       # Standard full solid cubes (stone, dirt, planks, cobble, etc.)
    GLASS_TRANSLUCENT = auto()  # Glass, Stained Glass, Ice, Slime, Honey, Tinted Glass, Powder Snow
    CUTOUT_LEAVES = auto()      # Leaves (Oak, Birch, etc.), Mangrove Roots
    PARTIAL_SHAPE = auto()      # Non-full blocks (Slabs, Stairs, Trapdoors, Snow, Farmland, Path)
    FLUID = auto()              # Water, Lava, Flowing fluids
    NON_OCCLUDING = auto()      # Flowers, Torches, Saplings, Rails, Web, Signs (cullface=None)
    AIR = auto()                # Air blocks (minecraft:air, cave_air, void_air)


class LeavesCullMode(Enum):
    """Culling modes for cutout foliage / leaves blocks."""
    FANCY = "FANCY"             # Vanilla Fancy: both adjacent leaves faces rendered (internal volume visible)
    SINGLE_FACE = "SINGLE_FACE" # Optimized: exactly one face rendered between touching leaves (no z-fighting)
    FAST = "FAST"               # Vanilla Fast: mutual culling between touching leaves (opaque outer shell)
    NONE = "NONE"               # No leaves culling at all (renders all faces)


class GlassCullMode(Enum):
    """Culling modes for glass and stained glass blocks."""
    SAME_BLOCK = "SAME_BLOCK"   # Strictly same block type culls (e.g. red glass against red glass only)
    GROUP = "GROUP"             # Any glass culls against any glass (plain + all 16 stained colors)
    NONE = "NONE"               # No glass culling (renders internal partition faces)


class FaceOcclusionRect(NamedTuple):
    """Axis-aligned 2D bounding rectangle [0..1] representing face occlusion coverage."""
    min_u: float
    min_v: float
    max_u: float
    max_v: float

    @property
    def is_full(self) -> bool:
        """Return True if this rectangle covers the full 1.0 x 1.0 face."""
        eps = 1e-4
        return (
            self.min_u <= eps
            and self.min_v <= eps
            and self.max_u >= 1.0 - eps
            and self.max_v >= 1.0 - eps
        )

    @property
    def is_empty(self) -> bool:
        """Return True if this rectangle has zero area."""
        eps = 1e-4
        return (self.max_u - self.min_u) <= eps or (self.max_v - self.min_v) <= eps


# Standard predefined 2D face occlusion rects
FULL_FACE_RECT = FaceOcclusionRect(0.0, 0.0, 1.0, 1.0)
EMPTY_FACE_RECT = FaceOcclusionRect(0.0, 0.0, 0.0, 0.0)

# Bitmask indices for 6 canonical Minecraft directions
DIR_MASK_EAST  = 1 << 0  # +X
DIR_MASK_WEST  = 1 << 1  # -X
DIR_MASK_UP    = 1 << 2  # +Y
DIR_MASK_DOWN  = 1 << 3  # -Y
DIR_MASK_SOUTH = 1 << 4  # +Z
DIR_MASK_NORTH = 1 << 5  # -Z

DIR_TO_MASK: dict[str, int] = {
    "east": DIR_MASK_EAST,
    "west": DIR_MASK_WEST,
    "up": DIR_MASK_UP,
    "top": DIR_MASK_UP,
    "down": DIR_MASK_DOWN,
    "bottom": DIR_MASK_DOWN,
    "south": DIR_MASK_SOUTH,
    "north": DIR_MASK_NORTH,
}

OPPOSITE_DIR: dict[str, str] = {
    "east": "west",
    "west": "east",
    "up": "down",
    "down": "up",
    "top": "bottom",
    "bottom": "top",
    "south": "north",
    "north": "south",
}


class BlockCullMeta:
    """Precomputed and cached culling metadata for a single unique BlockState string."""
    __slots__ = (
        'state_str', 'block_name', 'category', 'is_full_cube',
        'is_opaque', 'is_air', 'is_fluid', 'cull_group',
        'face_shapes', 'full_face_mask', 'empty_face_mask',
        'props', 'is_waterlogged', '_has_baked_model'
    )

    def __init__(
        self,
        state_str: str,
        block_name: str,
        category: CullCategory,
        is_full_cube: bool,
        is_opaque: bool,
        is_air: bool,
        is_fluid: bool,
        cull_group: str,
        face_shapes: dict[str, tuple[FaceOcclusionRect, ...]],
        full_face_mask: int,
        empty_face_mask: int,
        props: Optional[dict[str, str]] = None,
        is_waterlogged: bool = False,
        has_baked_model: bool = False,
    ):
        self.state_str = state_str
        self.block_name = block_name
        self.category = category
        self.is_full_cube = is_full_cube
        self.is_opaque = is_opaque
        self.is_air = is_air
        self.is_fluid = is_fluid
        self.cull_group = cull_group
        self.face_shapes = face_shapes
        self.full_face_mask = full_face_mask
        self.empty_face_mask = empty_face_mask
        self.props = props or {}
        self.is_waterlogged = is_waterlogged
        self._has_baked_model = has_baked_model


    def has_full_face(self, direction: str) -> bool:
        mask = DIR_TO_MASK.get(direction, 0)
        return (self.full_face_mask & mask) != 0

    def has_empty_face(self, direction: str) -> bool:
        mask = DIR_TO_MASK.get(direction, 0)
        return (self.empty_face_mask & mask) != 0
