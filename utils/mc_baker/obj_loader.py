"""
OBJ Model Loader & Registry for Minecraft Block Entity models.
Loads 1:1 author-crafted models from jmc2obj (GPL v2) and authoritative Block Entity models
(Chests, Shulker Boxes, End Portal Frame, End Portal, End Gateway, Banners, Heads, Bells, Pots, Conduits, Hanging Signs)
with dynamic texture substitution and transformations conforming to upstream jmc2obj.
"""

from __future__ import annotations
import math
from pathlib import Path
from typing import Optional, Any, Tuple, Union, Sequence, Callable, Dict, List

from .types import BakedModel, BakedElement, BakedFace, MC_DIRECTIONS
from .primitives import (
    Vec3, Vec2,
    rotate_y_point,
    rotate_point_by_facing,
    get_entity_facing_angle_y,
    get_block_facing_angle_y,
    calculate_normal,
    normal_to_mc_direction,
    compute_box_face_uvs,
    build_cuboid_element,
    build_plane_element,
)

MODELS_DIR = Path(__file__).parent / "assets" / "models"

# Compatibility aliases
jmc_rotate_y = rotate_y_point


def transform_obj_point(
    p: Vec3,
    scale: Vec3 = (1.0, 1.0, 1.0),
    rot_y: float = 0.0,
    offset: Vec3 = (0.0, 0.0, 0.0),
) -> Vec3:
    """Apply scale, Y-rotation, and translation to a point in OBJ space."""
    x, y, z = p
    sx, sy, sz = scale
    # 1. Scale
    x, y, z = x * sx, y * sy, z * sz
    # 2. Rotate around Y (conforming to jmc2obj Transform.rotation)
    if rot_y != 0.0:
        x, y, z = rotate_y_point((x, y, z), rot_y)
    # 3. Translate
    tx, ty, tz = offset
    return (x + tx, y + ty, z + tz)


class OBJModelCache:
    """In-memory cache for parsed OBJ files."""
    def __init__(self):
        self._cache: dict[str, dict[str, list[dict[str, Any]]]] = {}

    def load(self, model_filename: str) -> dict[str, list[dict[str, Any]]]:
        if model_filename in self._cache:
            return self._cache[model_filename]

        filepath = MODELS_DIR / model_filename
        if not filepath.is_file():
            return {}

        lines = filepath.read_text(encoding="utf-8").splitlines()
        objects: dict[str, list[dict[str, Any]]] = {}
        curr_obj = "default"
        curr_mtl = ""

        verts: list[Vec3] = []
        uvs: list[Vec2] = []
        normals: list[Vec3] = []

        for line in lines:
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue
            parts = line_str.split()
            tag = parts[0]

            if tag in ("o", "g"):
                curr_obj = parts[1] if len(parts) > 1 else "unnamed"
                if curr_obj not in objects:
                    objects[curr_obj] = []
            elif tag == "v":
                verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif tag == "vt":
                uvs.append((float(parts[1]), float(parts[2])))
            elif tag == "vn":
                normals.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif tag == "usemtl":
                curr_mtl = parts[1]
            elif tag == "f":
                if curr_obj not in objects:
                    objects[curr_obj] = []
                f_verts: list[Vec3] = []
                f_uvs: list[Vec2] = []
                f_norms: list[Vec3] = []
                for tok in parts[1:]:
                    sub = tok.split("/")
                    vi = int(sub[0]) - 1
                    ti = int(sub[1]) - 1 if len(sub) > 1 and sub[1] else -1
                    ni = int(sub[2]) - 1 if len(sub) > 2 and sub[2] else -1

                    f_verts.append(verts[vi])
                    f_uvs.append(uvs[ti] if ti >= 0 else (0.0, 0.0))
                    if 0 <= ni < len(normals):
                        f_norms.append(normals[ni])

                objects[curr_obj].append({
                    "verts": f_verts,
                    "uvs": f_uvs,
                    "normals": f_norms,
                    "mtl": curr_mtl,
                })

        self._cache[model_filename] = objects
        return objects


_OBJ_CACHE = OBJModelCache()


def resolve_chest_material(short_name: str, chest_type: str) -> str:
    """Resolve authoritative Minecraft entity texture ID for chest variant and type."""
    name = short_name.removeprefix("waxed_")
    if name == "trapped_chest":
        stem = "minecraft:entity/chest/trapped"
    elif name == "ender_chest":
        return "minecraft:entity/chest/ender"
    elif name == "copper_chest":
        stem = "minecraft:entity/chest/copper"
    elif name == "exposed_copper_chest":
        stem = "minecraft:entity/chest/copper_exposed"
    elif name == "weathered_copper_chest":
        stem = "minecraft:entity/chest/copper_weathered"
    elif name == "oxidized_copper_chest":
        stem = "minecraft:entity/chest/copper_oxidized"
    else:
        stem = "minecraft:entity/chest/normal"

    if chest_type == "left":
        return f"{stem}_left"
    elif chest_type == "right":
        return f"{stem}_right"
    return stem


def build_baked_model_from_obj(
    block_state: str,
    obj_filename: str,
    sub_objects: Optional[Union[str, Sequence[str]]] = None,
    material_override: Optional[str] = None,
    material_map: Optional[dict[str, str]] = None,
    scale: Vec3 = (1.0, 1.0, 1.0),
    rot_y: float = 0.0,
    rot_facing: Optional[str] = None,
    offset: Vec3 = (0.0, 0.0, 0.0),
) -> Optional[BakedModel]:
    """
    Construct a canonical BakedModel from an author-crafted OBJ model file.
    Applies exact scaling, Y-rotation/directional facing, and translation offsets conforming to upstream jmc2obj.
    """
    obj_data = _OBJ_CACHE.load(obj_filename)
    if not obj_data:
        return None

    if sub_objects:
        if isinstance(sub_objects, str):
            sub_objects = [sub_objects]
        faces_list = [f for name in sub_objects if name in obj_data for f in obj_data[name]]
    else:
        faces_list = [f for obj_faces in obj_data.values() for f in obj_faces]

    if not faces_list:
        return None

    elements: list[BakedElement] = []
    face_objects: list[BakedFace] = []

    for f_data in faces_list:
        raw_verts = f_data["verts"]
        raw_uvs = f_data["uvs"]
        orig_mtl = f_data.get("mtl", "")

        # 1. Resolve Texture ID
        if material_override:
            tex_id = material_override
        elif material_map and orig_mtl in material_map:
            tex_id = material_map[orig_mtl]
        elif orig_mtl and orig_mtl != "None":
            tex_id = f"minecraft:{orig_mtl}" if ":" not in orig_mtl else orig_mtl
        else:
            tex_id = "minecraft:block/dirt"

        # 2. Transform Vertices: Scale -> Rotate Y -> Facing Rotate -> Offset -> Convert to MC block space [0..1]
        transformed_mc_verts = []
        for v in raw_verts:
            vt = transform_obj_point(v, scale=scale, rot_y=rot_y, offset=offset)
            if rot_facing:
                vt = rotate_point_by_facing(vt, rot_facing)
            # Centered [-0.5, 0.5] + offset -> [0.0, 1.0]
            transformed_mc_verts.append((vt[0] + 0.5, vt[1] + 0.5, vt[2] + 0.5))

        # 3. Calculate Normal & Direction
        if len(transformed_mc_verts) >= 3:
            norm = calculate_normal(transformed_mc_verts[0], transformed_mc_verts[1], transformed_mc_verts[2])
            face_dir = normal_to_mc_direction(norm)
        else:
            face_dir = "up"

        # 4. Map UVs: OBJ vt has v=1.0 at top. Store as (u, 1.0 - v_obj) so mesh_generator's
        # (u, 1.0 - v) outputs the exact original obj UV (u, v_obj).
        mc_uvs = []
        for u, v in raw_uvs:
            mc_uvs.append((u, 1.0 - v))

        min_u = min(u for u, _ in mc_uvs) if mc_uvs else 0.0
        max_u = max(u for u, _ in mc_uvs) if mc_uvs else 1.0
        min_v = min(v for _, v in mc_uvs) if mc_uvs else 0.0
        max_v = max(v for _, v in mc_uvs) if mc_uvs else 1.0

        baked_face = BakedFace(
            direction=face_dir,
            texture=tex_id,
            uv_bounds=(min_u, min_v, max_u, max_v),
            vertices=tuple(transformed_mc_verts),
            uvs=tuple(mc_uvs),
        )
        face_objects.append(baked_face)

        # Build element container
        xs = [v[0] for v in transformed_mc_verts]
        ys = [v[1] for v in transformed_mc_verts]
        zs = [v[2] for v in transformed_mc_verts]
        from_pos = (min(xs) * 16.0, min(ys) * 16.0, min(zs) * 16.0)
        to_pos = (max(xs) * 16.0, max(ys) * 16.0, max(zs) * 16.0)

        elem = BakedElement(
            from_pos=from_pos,
            to_pos=to_pos,
            faces={face_dir: baked_face}
        )
        elements.append(elem)

    # Standard 6-face summary
    six_faces = []
    for d in MC_DIRECTIONS:
        match = next((f for f in face_objects if f.direction == d), None)
        if match:
            six_faces.append(match)
        elif face_objects:
            six_faces.append(face_objects[0])
        else:
            six_faces.append(BakedFace(direction=d, texture="minecraft:block/dirt"))

    return BakedModel(
        block_state=block_state,
        elements=elements,
        faces=six_faces,
        is_cube=False,
        is_opaque=False,
    )


# ---------------------------------------------------------------------------
# Dedicated Shulker Box, Conduit & Portal Model Builders (Authoritative geometry)
# ---------------------------------------------------------------------------

def rotate_shulker_vertex(v: Vec3, facing: str) -> Vec3:
    """Compatibility wrapper for vertex rotation by facing."""
    return rotate_point_by_facing(v, facing)


def build_shulker_box_model(block_state: str, short_name: str, props: dict[str, str]) -> BakedModel:
    """
    Construct a pixel-perfect Shulker Box model (Lid & Base) from authoritative OBJ geometry
    with 1:1 64x64 entity texture UVs.
    Supports all 16 colors + undyed across all 6 directional facings.
    """
    color = short_name.removesuffix("_shulker_box")
    if color == "shulker_box" or not color:
        tex_id = "minecraft:entity/shulker/shulker"
    else:
        tex_id = f"minecraft:entity/shulker/shulker_{color}"

    facing = props.get("facing", "up").lower()

    baked = build_baked_model_from_obj(
        block_state=block_state,
        obj_filename="shulker_box.obj",
        material_override=tex_id,
        rot_facing=facing,
    )
    if baked is not None:
        return baked

    return BakedModel(
        block_state=block_state,
        elements=[],
        faces=[BakedFace(direction=d, texture=tex_id) for d in MC_DIRECTIONS],
        is_cube=False,
        is_opaque=False,
    )


def build_conduit_model(block_state: str) -> BakedModel:
    """Construct the Conduit 6x6x6 centered cube model with 32x16 texture UVs."""
    tex_id = "minecraft:entity/conduit/base"
    conduit_uvs = compute_box_face_uvs(0, 0, 6, 6, 6, tex_w=32, tex_h=16)
    elem, faces_list = build_cuboid_element(
        bounds_min=(-3/16, -3/16, -3/16),
        bounds_max=(3/16, 3/16, 3/16),
        texture=tex_id,
        uvs_by_face=conduit_uvs,
    )
    return BakedModel(
        block_state=block_state,
        elements=[elem],
        faces=faces_list,
        is_cube=False,
        is_opaque=False,
        is_emissive=True,
    )


def build_end_portal_model(block_state: str) -> BakedModel:
    """
    Construct End Portal (horizontal starry portal plane at Y=0.75 / 12/16)
    conforming to jmc2obj PortalHoriz.java with double-sided top and bottom faces.
    """
    tex_id = "minecraft:entity/end_portal"
    top_v = (0.0, 0.75, 1.0)
    top_v1 = (1.0, 0.75, 1.0)
    top_v2 = (1.0, 0.75, 0.0)
    top_v3 = (0.0, 0.75, 0.0)
    elem, faces_list = build_plane_element(
        top_v, top_v1, top_v2, top_v3,
        texture=tex_id,
        uvs=((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)),
        double_sided=True,
    )
    six_faces = [faces_list[0], faces_list[1], faces_list[0], faces_list[0], faces_list[0], faces_list[0]]
    return BakedModel(
        block_state=block_state,
        elements=[elem],
        faces=six_faces,
        is_cube=False,
        is_opaque=False,
        is_emissive=True,
    )


def build_end_gateway_model(block_state: str) -> BakedModel:
    """
    Construct End Gateway (FULL 1x1x1 solid block surrounded by bedrock)
    with starry portal texture across all 6 faces.
    """
    tex_id = "minecraft:entity/end_portal"
    cube_uvs = {d: ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)) for d in MC_DIRECTIONS}
    elem, faces_list = build_cuboid_element(
        bounds_min=(-0.5, -0.5, -0.5),
        bounds_max=(0.5, 0.5, 0.5),
        texture=tex_id,
        uvs_by_face=cube_uvs,
    )
    return BakedModel(
        block_state=block_state,
        elements=[elem],
        faces=faces_list,
        is_cube=True,
        is_opaque=True,
        is_emissive=True,
    )


def build_bell_model(
    block_state: str,
    props: dict[str, str],
    support_elements: Optional[list[BakedElement]] = None,
    support_faces: Optional[list[BakedFace]] = None,
    rot_y: Optional[float] = None,
) -> BakedModel:
    """
    Construct a hybrid Minecraft Bell model combining the JSON-modeled support frame
    (floor stone posts, ceiling bracket, wall bracket, or between walls bar) with
    the 1:1 author-crafted golden bell body from bell.obj.
    """
    attachment = props.get("attachment", "floor").lower()
    facing = props.get("facing", "north").lower()

    if rot_y is None:
        if attachment in ("single_wall", "double_wall"):
            rot_y = {"east": 0.0, "south": 90.0, "west": 180.0, "north": 270.0}.get(facing, 0.0)
        else:
            rot_y = {"north": 0.0, "east": 90.0, "south": 180.0, "west": 270.0}.get(facing, 0.0)

    bell_body_model = build_baked_model_from_obj(
        block_state=block_state,
        obj_filename="bell.obj",
        material_map={
            "block/bell_top": "minecraft:block/bell_top",
            "block/bell_side": "minecraft:block/bell_side",
            "block/bell_bottom": "minecraft:block/bell_bottom",
        },
        rot_y=rot_y,
    )

    combined_elements = list(support_elements or []) + list(bell_body_model.elements)
    combined_faces = list(support_faces or []) + list(bell_body_model.faces)

    return BakedModel(
        block_state=block_state,
        elements=combined_elements,
        faces=combined_faces,
        is_cube=False,
        is_opaque=False,
        is_emissive=False,
    )


# ---------------------------------------------------------------------------
# Specialized Model Provider Registry & Dispatcher
# ---------------------------------------------------------------------------

ModelBuilderFn = Callable[[str, str, dict[str, str]], Optional[BakedModel]]


class SpecialModelRegistry:
    """
    Declarative registry for specialized Block Entity model builders.
    Decouples individual block model logic from a monolithic dispatcher function.
    """
    def __init__(self):
        self._exact_match_providers: Dict[str, ModelBuilderFn] = {}
        self._predicate_providers: List[Tuple[Callable[[str, dict[str, str]], bool], ModelBuilderFn]] = []

    def register_exact(self, short_name: str, builder_fn: ModelBuilderFn):
        self._exact_match_providers[short_name] = builder_fn

    def register_predicate(self, predicate: Callable[[str, dict[str, str]], bool], builder_fn: ModelBuilderFn):
        self._predicate_providers.append((predicate, builder_fn))

    def resolve(self, block_id: str, props: dict[str, str], fallback_texture: str = "") -> Optional[BakedModel]:
        short_name = block_id.split(":", 1)[-1]
        state_str = f"{block_id}[{','.join(f'{k}={v}' for k, v in sorted(props.items()))}]" if props else block_id

        # 1. Exact match
        if short_name in self._exact_match_providers:
            return self._exact_match_providers[short_name](state_str, short_name, props)

        # 2. Predicate match
        for predicate, builder in self._predicate_providers:
            if predicate(short_name, props):
                return builder(state_str, short_name, props)

        return None


# --- Individual Providers ---

def _build_chest_model(state_str: str, short_name: str, props: dict[str, str]) -> Optional[BakedModel]:
    chest_type = props.get("type", "single").lower()
    sub_obj = "chest"
    if chest_type == "left":
        sub_obj = "chest_left"
    elif chest_type == "right":
        sub_obj = "chest_right"

    facing = props.get("facing", "north").lower()
    rot_y = get_entity_facing_angle_y(facing)
    mat_id = resolve_chest_material(short_name, chest_type)

    return build_baked_model_from_obj(
        block_state=state_str,
        obj_filename="chest.obj",
        sub_objects=sub_obj,
        material_override=mat_id,
        rot_y=rot_y,
    )


def _build_end_portal_frame_model(state_str: str, short_name: str, props: dict[str, str]) -> Optional[BakedModel]:
    has_eye = props.get("eye", "false").lower() == "true"
    sub_objects = ["base", "eye"] if has_eye else ["base"]
    facing = props.get("facing", "north").lower()
    rot_y = get_block_facing_angle_y(facing)
    return build_baked_model_from_obj(
        block_state=state_str,
        obj_filename="endportal_frame.obj",
        sub_objects=sub_objects,
        material_map={
            "block/end_portal_frame_eye": "minecraft:block/end_portal_frame_eye",
            "block/end_portal_frame_side": "minecraft:block/end_portal_frame_side",
            "block/end_portal_frame_top": "minecraft:block/end_portal_frame_top",
            "block/end_stone": "minecraft:block/end_stone",
        },
        rot_y=rot_y,
    )


def _build_decorated_pot_model(state_str: str, short_name: str, props: dict[str, str]) -> Optional[BakedModel]:
    return build_baked_model_from_obj(
        block_state=state_str,
        obj_filename="decorated_pot.obj",
        material_map={
            "entity/decorated_pot/decorated_pot_base": "minecraft:entity/decorated_pot/decorated_pot_base",
            "entity/decorated_pot/decorated_pot_side": "minecraft:entity/decorated_pot/decorated_pot_side",
        },
        rot_y=0.0,
    )


def _build_banner_model(state_str: str, short_name: str, props: dict[str, str]) -> Optional[BakedModel]:
    is_wall = "_wall_banner" in short_name
    obj_file = "banner_wall.obj" if is_wall else "banner_standing.obj"
    scale = (0.5, 0.5, 0.5)

    if is_wall:
        facing = props.get("facing", "north").lower()
        wall_transforms = {
            "north": (-90.0, (0.0, -1.51, 0.514)),
            "east": (0.0, (-0.514, -1.51, 0.0)),
            "south": (90.0, (0.0, -1.51, -0.52)),
            "west": (180.0, (0.52, -1.51, 0.0)),
        }
        rot_y, offset = wall_transforms.get(facing, (-90.0, (0.0, -1.51, 0.514)))
    else:
        rot_idx = int(props.get("rotation", "0")) if "rotation" in props else 0
        rot_y = (90.0 + (360.0 / 16.0) * rot_idx)
        offset = (0.0, -0.48, 0.0)

    return build_baked_model_from_obj(
        block_state=state_str,
        obj_filename=obj_file,
        material_override="minecraft:entity/banner/banner_base",
        scale=scale,
        rot_y=rot_y,
        offset=offset,
    )


def _build_skull_head_model(state_str: str, short_name: str, props: dict[str, str]) -> Optional[BakedModel]:
    is_wall = "_wall_" in short_name
    is_dragon = "dragon" in short_name

    if is_dragon:
        obj_file = "dragon_wall_head.obj" if is_wall else "dragon_head.obj"
        if is_wall:
            facing = props.get("facing", "north").lower()
            rot_y = {"north": 180.0, "south": 0.0, "west": 90.0, "east": 270.0}.get(facing, 180.0)
        else:
            rot_idx = int(props.get("rotation", "0")) if "rotation" in props else 0
            rot_y = (180.0 + rot_idx * 22.5) % 360.0
        offset = (0.0, 0.0, 0.0)
        scale = (1.0, 1.0, 1.0)
        mat = "minecraft:entity/enderdragon/dragon"
    else:
        head_type = short_name.replace("_wall_", "_").removesuffix("_skull").removesuffix("_head")
        is_mob_half_tex = head_type in ("skeleton", "wither_skeleton", "creeper")
        if head_type == "piglin":
            obj_file = "piglin_head.obj"
        elif is_mob_half_tex:
            obj_file = "mob_head.obj"
        else:
            obj_file = "player_head.obj"
        scale = (1.0, 1.0, 1.0)
        if is_wall:
            facing = props.get("facing", "north").lower()
            wall_configs = {
                "north": (0.0, (0.0, 0.0, 0.25)),
                "south": (180.0, (0.0, 0.0, -0.25)),
                "west": (-90.0, (0.25, 0.0, 0.0)),
                "east": (90.0, (-0.25, 0.0, 0.0)),
            }
            rot_y, offset = wall_configs.get(facing, (0.0, (0.0, 0.0, 0.25)))
        else:
            rot_idx = int(props.get("rotation", "0")) if "rotation" in props else 0
            rot_y = rot_idx * 22.5
            offset = (0.0, -0.25, 0.0)

        if head_type == "skeleton":
            mat = "minecraft:entity/skeleton/skeleton"
        elif head_type == "wither_skeleton":
            mat = "minecraft:entity/skeleton/wither_skeleton"
        elif head_type == "zombie":
            mat = "minecraft:entity/zombie/zombie"
        elif head_type == "creeper":
            mat = "minecraft:entity/creeper/creeper"
        elif head_type == "piglin":
            mat = "minecraft:entity/piglin/piglin"
        else:
            mat = "minecraft:entity/player/wide/steve"

    return build_baked_model_from_obj(
        block_state=state_str,
        obj_filename=obj_file,
        material_override=mat,
        scale=scale,
        rot_y=rot_y,
        offset=offset,
    )


def _build_hanging_sign_model(state_str: str, short_name: str, props: dict[str, str]) -> Optional[BakedModel]:
    wood_type = short_name.replace("_wall_hanging_sign", "").replace("_hanging_sign", "")
    tex_path = f"minecraft:entity/signs/hanging/{wood_type}" if wood_type else "minecraft:entity/signs/hanging/oak"

    if "_wall_" in short_name:
        facing = props.get("facing", "north").lower()
        rot_y = {"north": 180.0, "west": 90.0, "south": 0.0, "east": -90.0}.get(facing, 180.0)
        sub_objs = ["sign", "chains", "top_bar"]
    else:
        rot_idx = int(props.get("rotation", "0")) if props.get("rotation", "").isdigit() else 0
        rot_y = rot_idx * 22.5
        attached = props.get("attached", "false").lower() == "true"
        sub_objs = ["sign", "chains_attached" if attached else "chains"]

    return build_baked_model_from_obj(
        block_state=state_str,
        obj_filename="hanging_sign.obj",
        sub_objects=sub_objs,
        material_override=tex_path,
        rot_y=rot_y,
    )


def _create_default_special_registry() -> SpecialModelRegistry:
    reg = SpecialModelRegistry()

    # Exact matches
    reg.register_exact("conduit", lambda s, n, p: build_conduit_model(s))
    reg.register_exact("end_portal", lambda s, n, p: build_end_portal_model(s))
    reg.register_exact("end_gateway", lambda s, n, p: build_end_gateway_model(s))
    reg.register_exact("end_portal_frame", _build_end_portal_frame_model)
    reg.register_exact("decorated_pot", _build_decorated_pot_model)

    # Chests
    chest_names = {
        "chest", "trapped_chest", "ender_chest",
        "copper_chest", "exposed_copper_chest", "weathered_copper_chest", "oxidized_copper_chest"
    }
    reg.register_predicate(
        lambda n, p: n.removeprefix("waxed_") in chest_names,
        _build_chest_model
    )

    # Shulker Boxes
    reg.register_predicate(
        lambda n, p: n.endswith("shulker_box"),
        lambda s, n, p: build_shulker_box_model(s, n, p)
    )

    # Banners
    reg.register_predicate(
        lambda n, p: n.endswith(("_banner", "_wall_banner")),
        _build_banner_model
    )

    # Skulls / Heads
    reg.register_predicate(
        lambda n, p: n.endswith(("_head", "_skull", "_wall_head", "_wall_skull")),
        _build_skull_head_model
    )

    # Hanging Signs
    reg.register_predicate(
        lambda n, p: "hanging_sign" in n,
        _build_hanging_sign_model
    )

    return reg


_DEFAULT_REGISTRY = _create_default_special_registry()


def resolve_obj_model_for_state(
    block_id: str,
    props: dict[str, str],
    fallback_texture: str = ""
) -> Optional[BakedModel]:
    """
    Primary dispatcher resolving known Block Entity / special model blocks to their 1:1 models.
    Delegates to the SpecialModelRegistry.
    """
    return _DEFAULT_REGISTRY.resolve(block_id, props, fallback_texture)
