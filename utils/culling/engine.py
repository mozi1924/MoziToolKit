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
    extract_quad_face_occlusion_rect,
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


def _derive_parametric_face_shapes(
    name_low: str,
    props: dict[str, str],
) -> dict[str, tuple[FaceOcclusionRect, ...]]:
    """
    Derive canonical 2D face occlusion shapes for known partial / non-full blocks
    based on block state properties when explicit detailed model elements are absent.
    """
    face_shapes: dict[str, tuple[FaceOcclusionRect, ...]] = {d: () for d in ALL_6_DIRS}

    # 1. Slabs
    if name_low.endswith("_slab"):
        slab_type = props.get("type", "bottom")
        if slab_type == "double":
            return {d: (FULL_FACE_RECT,) for d in ALL_6_DIRS}
        elif slab_type == "top":
            return {
                "up": (FULL_FACE_RECT,),
                "down": (),
                "north": (FaceOcclusionRect(0.0, 0.5, 1.0, 1.0),),
                "south": (FaceOcclusionRect(0.0, 0.5, 1.0, 1.0),),
                "east": (FaceOcclusionRect(0.0, 0.5, 1.0, 1.0),),
                "west": (FaceOcclusionRect(0.0, 0.5, 1.0, 1.0),),
            }
        else:  # bottom
            return {
                "up": (),
                "down": (FULL_FACE_RECT,),
                "north": (FaceOcclusionRect(0.0, 0.0, 1.0, 0.5),),
                "south": (FaceOcclusionRect(0.0, 0.0, 1.0, 0.5),),
                "east": (FaceOcclusionRect(0.0, 0.0, 1.0, 0.5),),
                "west": (FaceOcclusionRect(0.0, 0.0, 1.0, 0.5),),
            }

    # 2. Snow layers (minecraft:snow)
    if name_low == "snow" or name_low.endswith(":snow"):
        try:
            layers = int(props.get("layers", "1"))
        except Exception:
            layers = 1
        layers = max(1, min(8, layers))
        h = layers / 8.0  # 1 layer = 2/16 = 0.125, 8 layers = 1.0
        side_rect = FaceOcclusionRect(0.0, 0.0, 1.0, h)
        return {
            "down": (FULL_FACE_RECT,),
            "up": (FULL_FACE_RECT,) if layers == 8 else (),
            "north": (side_rect,),
            "south": (side_rect,),
            "east": (side_rect,),
            "west": (side_rect,),
        }

    # 3. Carpets (minecraft:white_carpet, etc.)
    if name_low.endswith("_carpet") or name_low == "carpet":
        h = 1.0 / 16.0
        side_rect = FaceOcclusionRect(0.0, 0.0, 1.0, h)
        return {
            "down": (FULL_FACE_RECT,),
            "up": (),
            "north": (side_rect,),
            "south": (side_rect,),
            "east": (side_rect,),
            "west": (side_rect,),
        }

    # 4. Iron bars & Glass Panes
    if name_low.endswith(("_bars", "_pane")) or name_low in ("iron_bars", "glass_pane"):
        w0, w1 = 7.0 / 16.0, 9.0 / 16.0
        post_cap = FaceOcclusionRect(w0, w0, w1, w1)
        side_cap = FaceOcclusionRect(w0, 0.0, w1, 1.0)
        return {
            "down": (post_cap,),
            "up": (post_cap,),
            "east": (side_cap,) if props.get("east") == "true" else (),
            "west": (side_cap,) if props.get("west") == "true" else (),
            "north": (side_cap,) if props.get("north") == "true" else (),
            "south": (side_cap,) if props.get("south") == "true" else (),
        }

    # 5. Wooden & Nether Brick Fences
    if name_low.endswith("_fence") or name_low == "fence":
        w0, w1 = 7.0 / 16.0, 9.0 / 16.0
        post_cap = FaceOcclusionRect(6.0 / 16.0, 6.0 / 16.0, 10.0 / 16.0, 10.0 / 16.0)
        top_bar = FaceOcclusionRect(w0, 12.0 / 16.0, w1, 15.0 / 16.0)
        bot_bar = FaceOcclusionRect(w0, 6.0 / 16.0, w1, 9.0 / 16.0)
        side_bars = (bot_bar, top_bar)
        return {
            "down": (post_cap,),
            "up": (post_cap,),
            "east": side_bars if props.get("east") == "true" else (),
            "west": side_bars if props.get("west") == "true" else (),
            "north": side_bars if props.get("north") == "true" else (),
            "south": side_bars if props.get("south") == "true" else (),
        }

    # 6. Stairs
    if name_low.endswith("_stairs"):
        half = props.get("half", "bottom")
        full_mask = DIR_MASK_UP if half == "top" else DIR_MASK_DOWN
        return {d: (FULL_FACE_RECT,) if (DIR_TO_MASK[d] & full_mask) else () for d in ALL_6_DIRS}

    return face_shapes


class FaceCuller:
    """Central face culling engine with pre-computed metadata caching."""

    def __init__(
        self,
        leaves_cull_mode: LeavesCullMode = LeavesCullMode.SINGLE_FACE,
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
        is_double_slab = name_low.endswith("_slab") and props.get("type") == "double"
        is_non_full = not is_air and not is_double_slab and (is_pane or name_low.endswith(("_slab", "_stairs")) or is_non_full_or_partial_block(name_low))

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
            else:
                category = CullCategory.PARTIAL_SHAPE
                cull_group = "partial"

                elems = getattr(baked_model, "elements", ())
                is_dummy_fallback = False
                if is_non_full and len(elems) == 1:
                    elem = elems[0]
                    verts = [v for f in elem.faces.values() for v in f.vertices]
                    if verts:
                        x0 = min(v[0] for v in verts)
                        y0 = min(v[1] for v in verts)
                        z0 = min(v[2] for v in verts)
                        x1 = max(v[0] for v in verts)
                        y1 = max(v[1] for v in verts)
                        z1 = max(v[2] for v in verts)
                        if (
                            abs(x0) <= 1e-4 and abs(y0) <= 1e-4 and abs(z0) <= 1e-4
                            and abs(x1 - 1.0) <= 1e-4 and abs(y1 - 1.0) <= 1e-4 and abs(z1 - 1.0) <= 1e-4
                        ):
                            is_dummy_fallback = True

                if is_dummy_fallback:
                    face_shapes = _derive_parametric_face_shapes(name_low, props)
                else:
                    face_shapes = {}
                    for d in ALL_6_DIRS:
                        shapes: list[FaceOcclusionRect] = []
                        for elem in elems:
                            bf = elem.faces.get(d)
                            if bf and bf.vertices:
                                rect = extract_quad_face_occlusion_rect(bf.vertices, d)
                                if rect and not rect.is_empty:
                                    shapes.append(rect)
                        face_shapes[d] = tuple(shapes)

                full_face_mask = 0
                empty_face_mask = 0
                for d in ALL_6_DIRS:
                    shapes_dir = face_shapes[d]
                    mask = DIR_TO_MASK.get(d, 0)
                    if any(s.is_full for s in shapes_dir):
                        full_face_mask |= mask
                    elif not shapes_dir:
                        empty_face_mask |= mask
        else:
            # Fallback default: classify common block types when baked_model is None
            if is_non_full:
                category = CullCategory.PARTIAL_SHAPE
                is_full_cube = False
                is_opaque = False
                cull_group = "partial"
                face_shapes = _derive_parametric_face_shapes(name_low, props)
                full_face_mask = 0
                empty_face_mask = 0
                for d in ALL_6_DIRS:
                    shapes_dir = face_shapes[d]
                    mask = DIR_TO_MASK.get(d, 0)
                    if any(s.is_full for s in shapes_dir):
                        full_face_mask |= mask
                    elif not shapes_dir:
                        empty_face_mask |= mask
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

        # 1. Solid / glass blocks must never have their external faces culled by adjacent non-full / partial blocks
        # (fences, panes, walls, carpets, trapdoors, doors, etc. must never cull adjacent solid/glass),
        # UNLESS:
        #   (a) The neighbor is a slab or stairs with an authoritative full solid face.
        #   (b) The block is directly underneath snow (direction == 'up'), where snow completely covers the top face
        #       and both faces are culled to allow seamless vertex welding and eliminate SSS contact dark seams.
        is_snow_cover = (
            direction == "up"
            and (neighbor_meta.block_name in ("snow", "minecraft:snow") or neighbor_meta.block_name.endswith(":snow"))
            and neighbor_meta.has_full_face("down")
        )
        if (
            state_meta.category in (CullCategory.SOLID_OPAQUE, CullCategory.GLASS_TRANSLUCENT)
            and not is_snow_cover
            and (
                neighbor_meta.category == CullCategory.NON_OCCLUDING
                or (
                    neighbor_meta.category == CullCategory.PARTIAL_SHAPE
                    and not (neighbor_meta.block_name.endswith("_slab") or neighbor_meta.block_name.endswith("_stairs"))
                )
            )
        ):
            return True

        # 2. Neighbor full solid face check (neighborFaceShape == Shapes.block())
        if neighbor_meta.has_full_face(opp_dir):
            # Fluid top face (direction == 'up') is physically below the upper block boundary (< 1.0 height, e.g. 8/9 for source water).
            # A solid ceiling above (at Y >= 1.0) does NOT touch or occlude the fluid top surface.
            # Fluid top face is only skipped/culled if submerged by the same fluid or waterlogged block (handled in step 2).
            if state_meta.category == CullCategory.FLUID and direction == "up":
                pass
            else:
                return False

        # 3. Custom skipRendering check (glass, leaves, fluid, snow, roots)
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

        # 4. Neighbor empty face check (neighborFaceShape == Shapes.empty())
        if neighbor_meta.has_empty_face(opp_dir):
            return True

        # 5. State empty face check (stateFaceShape == Shapes.empty())
        if quad_face_shape is None and state_meta.has_empty_face(direction):
            return True

        # 6. 2D Boolean shape occlusion check (Shapes.joinIsNotEmpty BooleanOp.ONLY_FIRST)
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
    leaves_cull_mode: LeavesCullMode = LeavesCullMode.SINGLE_FACE,
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

