"""
High-Performance Unified Face Culling Engine (FaceCuller).
Provides sub-microsecond face visibility evaluation for Live Sync and MC Baker.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple, Sequence
import logging

from .types import (
    BlockCullMeta,
    CullCategory,
    LeavesCullMode,
    GlassCullMode,
    FaceOcclusionRect,
    FULL_FACE_RECT,
    EMPTY_FACE_RECT,
    DIR_TO_MASK,
    OPPOSITE_DIR,
    DIR_MASK_EAST,
    DIR_MASK_WEST,
    DIR_MASK_UP,
    DIR_MASK_DOWN,
    DIR_MASK_SOUTH,
    DIR_MASK_NORTH,
)
from .shapes import (
    is_face_completely_occluded,
    extract_face_occlusion_from_elements,
)
from .rules import should_skip_rendering

logger = logging.getLogger("MoziToolKit.Culling")

ALL_6_DIRS = ("east", "west", "up", "down", "south", "north")
FULL_6_DIRS_MASK = (
    DIR_MASK_EAST | DIR_MASK_WEST | DIR_MASK_UP
    | DIR_MASK_DOWN | DIR_MASK_SOUTH | DIR_MASK_NORTH
)


# Known block name classification sets
_AIR_NAMES = frozenset({
    "air", "minecraft:air", "cave_air", "minecraft:cave_air",
    "void_air", "minecraft:void_air", "structure_void", "minecraft:structure_void",
    "bubble_column", "minecraft:bubble_column",
})

_FLUID_NAMES = frozenset({
    "water", "minecraft:water", "flowing_water", "minecraft:flowing_water",
    "lava", "minecraft:lava", "flowing_lava", "minecraft:flowing_lava"
})

_LEAVES_NAMES = frozenset({
    "oak_leaves", "minecraft:oak_leaves",
    "spruce_leaves", "minecraft:spruce_leaves",
    "birch_leaves", "minecraft:birch_leaves",
    "jungle_leaves", "minecraft:jungle_leaves",
    "acacia_leaves", "minecraft:acacia_leaves",
    "dark_oak_leaves", "minecraft:dark_oak_leaves",
    "mangrove_leaves", "minecraft:mangrove_leaves",
    "cherry_leaves", "minecraft:cherry_leaves",
    "azalea_leaves", "minecraft:azalea_leaves",
    "flowering_azalea_leaves", "minecraft:flowering_azalea_leaves",
    "pale_oak_leaves", "minecraft:pale_oak_leaves",
})

_GLASS_NAMES = frozenset({
    "glass", "minecraft:glass",
    "tinted_glass", "minecraft:tinted_glass",
    "white_stained_glass", "minecraft:white_stained_glass",
    "orange_stained_glass", "minecraft:orange_stained_glass",
    "magenta_stained_glass", "minecraft:magenta_stained_glass",
    "light_blue_stained_glass", "minecraft:light_blue_stained_glass",
    "yellow_stained_glass", "minecraft:yellow_stained_glass",
    "lime_stained_glass", "minecraft:lime_stained_glass",
    "pink_stained_glass", "minecraft:pink_stained_glass",
    "gray_stained_glass", "minecraft:gray_stained_glass",
    "light_gray_stained_glass", "minecraft:light_gray_stained_glass",
    "cyan_stained_glass", "minecraft:cyan_stained_glass",
    "purple_stained_glass", "minecraft:purple_stained_glass",
    "blue_stained_glass", "minecraft:blue_stained_glass",
    "brown_stained_glass", "minecraft:brown_stained_glass",
    "green_stained_glass", "minecraft:green_stained_glass",
    "red_stained_glass", "minecraft:red_stained_glass",
    "black_stained_glass", "minecraft:black_stained_glass",
    "ice", "minecraft:ice",
    "packed_ice", "minecraft:packed_ice",
    "blue_ice", "minecraft:blue_ice",
    "frosted_ice", "minecraft:frosted_ice",
    "slime_block", "minecraft:slime_block",
    "honey_block", "minecraft:honey_block",
    "powder_snow", "minecraft:powder_snow",
})

_NON_OCCLUDING_NAMES = frozenset({
    "torch", "wall_torch", "soul_torch", "soul_wall_torch",
    "redstone_torch", "redstone_wall_torch", "lantern", "soul_lantern",
    "short_grass", "tall_grass", "fern", "large_fern", "dandelion", "poppy",
    "blue_orchid", "allium", "azure_bluet", "red_tulip", "orange_tulip",
    "white_tulip", "pink_tulip", "oxeye_daisy", "cornflower", "lily_of_the_valley",
    "wither_rose", "sunflower", "lilac", "rose_bush", "peony", "dead_bush",
    "sapling", "wheat", "carrots", "potatoes", "beetroots", "sweet_berry_bush",
    "ladder", "lever", "tripwire_hook", "tripwire", "vine", "scaffolding",
    "barrier", "light", "structure_void", "bubble_column", "minecraft:bubble_column",
})

_PARTIAL_SHAPE_SUFFIXES = (
    "_fence", "_fence_gate", "_wall", "_pane", "_bars", "_trapdoor", "_door",
    "_carpet", "_bed", "_sign", "_hanging_sign", "_head", "_skull", "_banner",
    "_candle", "_pot", "_rod", "_coral", "_fan", "_chain",
)

_PARTIAL_SHAPE_EXACT_NAMES = frozenset({
    "iron_bars", "glass_pane", "chest", "trapped_chest", "ender_chest", "bell",
    "anvil", "chipped_anvil", "damaged_anvil", "cauldron", "water_cauldron",
    "lava_cauldron", "powder_snow_cauldron", "hopper", "brewing_stand",
    "flower_pot", "conduit", "beacon", "decorated_pot", "end_portal_frame",
    "end_portal", "end_gateway", "chain", "iron_chain", "copper_chain",
    "exposed_copper_chain", "weathered_copper_chain", "oxidized_copper_chain",
    "lever", "tripwire_hook", "tripwire", "repeater", "comparator",
    "daylight_detector", "lightning_rod", "end_rod", "dragon_egg",
    "scaffolding", "pointed_dripstone", "amethyst_cluster", "small_amethyst_bud",
    "medium_amethyst_bud", "large_amethyst_bud", "calibrated_sculk_sensor",
    "sculk_sensor", "sculk_shrieker", "sculk_vein", "snow", "ladder",
    "grindstone", "stonecutter", "lectern", "sniffer_egg"
})


def is_non_full_or_partial_block(name_low: str) -> bool:
    """Return True if the block is a non-full block (fence, pane, wall, carpet, etc.)."""
    if name_low in _PARTIAL_SHAPE_EXACT_NAMES or name_low in _NON_OCCLUDING_NAMES:
        return True
    if name_low.endswith(_PARTIAL_SHAPE_SUFFIXES):
        return True
    if any(w in name_low for w in ("flower", "sapling", "torch", "lantern", "pane", "fence", "wall", "carpet", "trapdoor", "door")):
        return True
    return False


def _parse_block_name_and_props(state_str: str) -> tuple[str, dict[str, str]]:
    """Fast extraction of raw block name and properties."""
    if not state_str:
        return ("air", {})
    state_str = state_str.strip()
    if state_str.startswith("{"):
        try:
            import json
            j = json.loads(state_str)
            raw_state = j.get("state", j.get("name", "air"))
            if "[" in raw_state and raw_state.endswith("]"):
                base, prop_part = raw_state[:-1].split("[", 1)
                name = base.split(":", 1)[-1]
                props = {}
                for item in prop_part.split(","):
                    if "=" in item:
                        k, v = item.split("=", 1)
                        props[k.strip()] = v.strip()
                return (name, props)
            name = raw_state.split(":", 1)[-1]
            props = j.get("properties", j.get("props", {}))
            return (name, props)
        except Exception:

            return ("air", {})

    if "[" in state_str and state_str.endswith("]"):
        base, prop_part = state_str[:-1].split("[", 1)
        name = base.split(":", 1)[-1]
        props = {}
        for item in prop_part.split(","):
            if "=" in item:
                k, v = item.split("=", 1)
                props[k.strip()] = v.strip()
        return (name, props)

    name = state_str.split(":", 1)[-1]
    return (name, {})


class FaceCuller:
    """Central face culling engine with pre-computed metadata caching."""

    def __init__(
        self,
        leaves_cull_mode: LeavesCullMode = LeavesCullMode.FAST,
        glass_cull_mode: GlassCullMode = GlassCullMode.GROUP,
    ):
        self.leaves_cull_mode = leaves_cull_mode
        self.glass_cull_mode = glass_cull_mode
        self._meta_cache: dict[str, BlockCullMeta] = {}


    def clear_cache(self) -> None:
        """Clear cached block culling metadata."""
        self._meta_cache.clear()

    def get_meta(
        self,
        state_str: str,
        baked_model: Optional[Any] = None,
        is_opaque_hint: Optional[bool] = None,
    ) -> BlockCullMeta:
        """Retrieve or compute BlockCullMeta for a given block state."""
        meta = self._meta_cache.get(state_str)
        if meta is not None:
            # If we now have an authoritative baked_model but the cached meta was built without one, refresh it
            if baked_model is not None and getattr(meta, "_has_baked_model", False) is False:
                pass
            else:
                return meta


        name, props = _parse_block_name_and_props(state_str)
        name_low = name.lower()

        is_waterlogged = props.get("waterlogged", "false") == "true" or name_low in ("seagrass", "tall_seagrass", "kelp", "kelp_plant")
        is_air = (not state_str) or name_low in _AIR_NAMES or name_low.endswith("air")
        is_fluid = not is_air and (name_low in _FLUID_NAMES or "water" in name_low or "lava" in name_low)
        is_leaves = not is_air and (name_low in _LEAVES_NAMES or name_low.endswith("_leaves") or name_low == "mangrove_roots")
        
        # Panes (glass_pane, stained_glass_pane, iron_bars) are non-full thin shapes, NOT full glass cubes
        is_pane = name_low.endswith(("_pane", "_bars")) or name_low in ("glass_pane", "iron_bars")
        is_glass = not is_air and not is_pane and (name_low in _GLASS_NAMES or ("stained_glass" in name_low and not is_pane) or (name_low.endswith("glass") and not is_pane) or name_low.endswith("ice"))
        is_non_occluding = not is_air and (name_low in _NON_OCCLUDING_NAMES or name_low.endswith(("_flower", "_sapling", "_torch", "_lantern", "_plant", "_bush")))
        is_non_full = not is_air and (is_pane or is_non_full_or_partial_block(name_low))

        # Determine Category
        if is_air:
            category = CullCategory.AIR
            is_full_cube = False
            is_opaque = False
            cull_group = "air"
            face_shapes = {d: () for d in ALL_6_DIRS}
            full_face_mask = 0
            empty_face_mask = FULL_6_DIRS_MASK
        elif is_fluid:
            category = CullCategory.FLUID
            is_full_cube = False
            is_opaque = False
            cull_group = "water" if "water" in name_low else "lava"
            face_shapes = {d: () for d in ALL_6_DIRS}
            full_face_mask = 0
            empty_face_mask = FULL_6_DIRS_MASK
        elif is_glass:
            category = CullCategory.GLASS_TRANSLUCENT
            is_full_cube = True
            is_opaque = False
            cull_group = "glass" if ("glass" in name_low) else name_low
            # Glass does NOT occlude other blocks (face occlusion shape is empty for solid neighbors)
            face_shapes = {d: () for d in ALL_6_DIRS}
            full_face_mask = 0
            empty_face_mask = FULL_6_DIRS_MASK
        elif is_leaves:
            category = CullCategory.CUTOUT_LEAVES
            is_full_cube = True
            is_opaque = False
            cull_group = "leaves"
            # Leaves do NOT occlude solid blocks (cutout transparency)
            face_shapes = {d: () for d in ALL_6_DIRS}
            full_face_mask = 0
            empty_face_mask = FULL_6_DIRS_MASK
        elif is_non_occluding:
            category = CullCategory.NON_OCCLUDING
            is_full_cube = False
            is_opaque = False
            cull_group = "non_occluding"
            face_shapes = {d: () for d in ALL_6_DIRS}
            full_face_mask = 0
            empty_face_mask = FULL_6_DIRS_MASK
        elif baked_model is not None:
            # Analyze baked model geometry
            is_full_cube = getattr(baked_model, "is_cube", False)
            # Guard against fallback cuboids on non-full block types (slabs, stairs, fences, panes, etc.)
            if is_non_full and not (name_low.endswith("_slab") and props.get("type") == "double"):
                is_full_cube = False

            is_opaque = (is_opaque_hint if is_opaque_hint is not None else is_full_cube) and not is_non_full

            if is_full_cube and is_opaque:
                category = CullCategory.SOLID_OPAQUE
                cull_group = "solid"
                face_shapes = {d: (FULL_FACE_RECT,) for d in ALL_6_DIRS}
                full_face_mask = FULL_6_DIRS_MASK
                empty_face_mask = 0
            elif is_non_full and not (name_low.endswith("_slab") or name_low.endswith("_stairs")):
                category = CullCategory.PARTIAL_SHAPE
                cull_group = "partial"
                face_shapes = {d: () for d in ALL_6_DIRS}
                full_face_mask = 0
                empty_face_mask = FULL_6_DIRS_MASK
            else:
                category = CullCategory.PARTIAL_SHAPE
                cull_group = "partial"
                # Derive face occlusion from element bounding boxes
                elem_boxes = []
                for elem in getattr(baked_model, "elements", ()):
                    verts = [v for f in elem.faces.values() for v in f.vertices]
                    if verts:
                        x0 = min(v[0] for v in verts)
                        y0 = min(v[1] for v in verts)
                        z0 = min(v[2] for v in verts)
                        x1 = max(v[0] for v in verts)
                        y1 = max(v[1] for v in verts)
                        z1 = max(v[2] for v in verts)
                        elem_boxes.append(((x0, y0, z0), (x1, y1, z1)))

                face_shapes = {}
                full_face_mask = 0
                empty_face_mask = 0
                for d in ALL_6_DIRS:
                    shapes = extract_face_occlusion_from_elements(elem_boxes, d)
                    face_shapes[d] = shapes
                    mask = DIR_TO_MASK.get(d, 0)
                    if any(s.is_full for s in shapes):
                        full_face_mask |= mask
                    elif not shapes:
                        empty_face_mask |= mask
        else:
            # Fallback default: classify common block types
            if name_low.endswith("_slab"):
                category = CullCategory.PARTIAL_SHAPE
                is_full_cube = False
                is_opaque = True
                cull_group = "slab"
                slab_type = props.get("type", "bottom")
                if slab_type == "double":
                    category = CullCategory.SOLID_OPAQUE
                    is_full_cube = True
                    face_shapes = {d: (FULL_FACE_RECT,) for d in ALL_6_DIRS}
                    full_face_mask = FULL_6_DIRS_MASK
                    empty_face_mask = 0
                elif slab_type == "top":
                    face_shapes = {
                        "up": (FULL_FACE_RECT,),
                        "down": (),
                        "north": (FaceOcclusionRect(0.0, 0.5, 1.0, 1.0),),
                        "south": (FaceOcclusionRect(0.0, 0.5, 1.0, 1.0),),
                        "east": (FaceOcclusionRect(0.0, 0.5, 1.0, 1.0),),
                        "west": (FaceOcclusionRect(0.0, 0.5, 1.0, 1.0),),
                    }
                    full_face_mask = DIR_MASK_UP
                    empty_face_mask = DIR_MASK_DOWN
                else:  # bottom
                    face_shapes = {
                        "up": (),
                        "down": (FULL_FACE_RECT,),
                        "north": (FaceOcclusionRect(0.0, 0.0, 1.0, 0.5),),
                        "south": (FaceOcclusionRect(0.0, 0.0, 1.0, 0.5),),
                        "east": (FaceOcclusionRect(0.0, 0.0, 1.0, 0.5),),
                        "west": (FaceOcclusionRect(0.0, 0.0, 1.0, 0.5),),
                    }
                    full_face_mask = DIR_MASK_DOWN
                    empty_face_mask = DIR_MASK_UP
            elif name_low.endswith("_stairs"):
                category = CullCategory.PARTIAL_SHAPE
                is_full_cube = False
                is_opaque = True
                cull_group = "stairs"
                half = props.get("half", "bottom")
                full_mask = DIR_MASK_UP if half == "top" else DIR_MASK_DOWN
                face_shapes = {d: (FULL_FACE_RECT,) if (DIR_TO_MASK[d] & full_mask) else () for d in ALL_6_DIRS}
                full_face_mask = full_mask
                empty_face_mask = 0
            elif is_non_full or is_pane:
                # Non-full blocks (fences, walls, panes, bars, trapdoors, doors, carpets, chests, pots, etc.)
                category = CullCategory.PARTIAL_SHAPE
                is_full_cube = False
                is_opaque = False
                cull_group = "partial"
                face_shapes = {d: () for d in ALL_6_DIRS}
                full_face_mask = 0
                empty_face_mask = FULL_6_DIRS_MASK
            else:
                # Standard full solid cube
                category = CullCategory.SOLID_OPAQUE
                is_full_cube = True
                is_opaque = is_opaque_hint if is_opaque_hint is not None else True
                cull_group = "solid"
                face_shapes = {d: (FULL_FACE_RECT,) for d in ALL_6_DIRS}
                full_face_mask = FULL_6_DIRS_MASK
                empty_face_mask = 0

        meta = BlockCullMeta(
            state_str=state_str,
            block_name=name,
            category=category,
            is_full_cube=is_full_cube,
            is_opaque=is_opaque,
            is_air=is_air,
            is_fluid=is_fluid,
            cull_group=cull_group,
            face_shapes=face_shapes,
            full_face_mask=full_face_mask,
            empty_face_mask=empty_face_mask,
            props=props,
            is_waterlogged=is_waterlogged,
            has_baked_model=bool(baked_model is not None),
        )


        if len(self._meta_cache) >= 8192:
            self._meta_cache.pop(next(iter(self._meta_cache)), None)
        self._meta_cache[state_str] = meta

        return meta

    def should_render_face(
        self,
        state_meta: BlockCullMeta,
        neighbor_meta: Optional[BlockCullMeta],
        direction: str,
        quad_face_shape: Optional[Sequence[FaceOcclusionRect]] = None,
        block_pos: Optional[Tuple[int, int, int]] = None,
        neighbor_pos: Optional[Tuple[int, int, int]] = None,
    ) -> bool:
        """
        Exact canonical face visibility test aligned with Minecraft's Block.shouldRenderFace.
        
        direction: The direction of the face on state_meta (e.g. 'east', 'up', 'north').
        neighbor_meta: The neighbor block situated at (block_pos + direction).
        Returns True if the face SHOULD be rendered, False if culled.
        """
        if state_meta.is_air:
            return False

        if neighbor_meta is None or neighbor_meta.is_air:
            return True

        opp_dir = OPPOSITE_DIR.get(direction, direction)

        # 1. Neighbor full solid face check (neighborFaceShape == Shapes.block())
        if neighbor_meta.has_full_face(opp_dir):
            return False

        # 2. Custom skipRendering check (glass, leaves, fluid, snow, roots)
        if should_skip_rendering(
            state_meta=state_meta,
            neighbor_meta=neighbor_meta,
            direction=direction,
            leaves_mode=self.leaves_cull_mode,
            glass_mode=self.glass_cull_mode,
            block_pos=block_pos,
            neighbor_pos=neighbor_pos,
        ):
            return False

        # 3. Neighbor empty face check (neighborFaceShape == Shapes.empty())
        if neighbor_meta.has_empty_face(opp_dir):
            return True

        # 4. State empty face check (stateFaceShape == Shapes.empty())
        if state_meta.has_empty_face(direction):
            return True

        # 5. 2D Boolean shape occlusion check (Shapes.joinIsNotEmpty BooleanOp.ONLY_FIRST)
        target_shapes = (
            quad_face_shape
            if quad_face_shape is not None
            else state_meta.face_shapes.get(direction, (FULL_FACE_RECT,))
        )
        neighbor_shapes = neighbor_meta.face_shapes.get(opp_dir, ())

        # If target shape is completely covered by neighbor occluder shape, cull it!
        if is_face_completely_occluded(target_shapes, neighbor_shapes):
            return False

        return True


_GLOBAL_FACE_CULLER: Optional[FaceCuller] = None


def get_shared_face_culler(
    leaves_cull_mode: LeavesCullMode = LeavesCullMode.FAST,
    glass_cull_mode: GlassCullMode = GlassCullMode.GROUP,
) -> FaceCuller:
    """Retrieve global singleton FaceCuller instance."""
    global _GLOBAL_FACE_CULLER
    if _GLOBAL_FACE_CULLER is None:
        _GLOBAL_FACE_CULLER = FaceCuller(
            leaves_cull_mode=leaves_cull_mode,
            glass_cull_mode=glass_cull_mode,
        )
    else:
        _GLOBAL_FACE_CULLER.leaves_cull_mode = leaves_cull_mode
        _GLOBAL_FACE_CULLER.glass_cull_mode = glass_cull_mode
    return _GLOBAL_FACE_CULLER


def get_visible_face_directions(
    x: int,
    y: int,
    z: int,
    state_str: str,
    block_map: dict[tuple[int, int, int], str],
    culler: Optional[FaceCuller] = None,
) -> list[str]:
    """
    Public utility to compute all visible face directions for a single voxel block.
    Can be used by static mesh rebuilders, voxel meshing tools, and preview operators.
    """
    if not state_str:
        return []
    culler = culler or get_shared_face_culler()
    meta = culler.get_meta(state_str)
    if meta.is_air:
        return []

    visible_dirs = []
    offsets = {
        "east": (1, 0, 0),
        "west": (-1, 0, 0),
        "up": (0, 1, 0),
        "down": (0, -1, 0),
        "south": (0, 0, 1),
        "north": (0, 0, -1),
    }

    for direction, (dx, dy, dz) in offsets.items():
        n_pos = (x + dx, y + dy, z + dz)
        n_state = block_map.get(n_pos)
        n_meta = culler.get_meta(n_state) if n_state else None
        if culler.should_render_face(
            state_meta=meta,
            neighbor_meta=n_meta,
            direction=direction,
            block_pos=(x, y, z),
            neighbor_pos=n_pos,
        ):
            visible_dirs.append(direction)

    return visible_dirs

