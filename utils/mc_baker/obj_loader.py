"""
OBJ Model Loader & Registry for Minecraft Block Entity models.
Loads 1:1 author-crafted models from jmc2obj (GPL v2) with dynamic texture substitution
and BlockState facing/rotation transformations.
"""

from __future__ import annotations
import math
from pathlib import Path
from typing import Optional, Any, Tuple

from .types import BakedModel, BakedElement, BakedFace, MC_DIRECTIONS

MODELS_DIR = Path(__file__).parent / "assets" / "models"

Vec3 = Tuple[float, float, float]
Vec2 = Tuple[float, float]


def rotate_y(p: Vec3, deg: float) -> Vec3:
    """Rotate a point (x, y, z) around origin (0, 0, 0) by deg degrees in Minecraft coordinate space."""
    if deg == 0.0:
        return p
    rad = math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    x, y, z = p
    # In Minecraft coordinate space: +X=East, +Y=Up, +Z=South
    # Rotating clockwise (South -> East -> North -> West):
    return (x * c + z * s, y, -x * s + z * c)


def calculate_normal(p0: Vec3, p1: Vec3, p2: Vec3) -> Vec3:
    """Calculate normalized face normal from 3 vertices."""
    v1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
    v2 = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
    nx = v1[1] * v2[2] - v1[2] * v2[1]
    ny = v1[2] * v2[0] - v1[0] * v2[2]
    nz = v1[0] * v2[1] - v1[1] * v2[0]
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length > 1e-6:
        return (nx / length, ny / length, nz / length)
    return (0.0, 1.0, 0.0)


def normal_to_mc_direction(normal: Vec3) -> str:
    """Map a 3D normal vector to the closest standard Minecraft face direction name."""
    nx, ny, nz = normal
    abs_x, abs_y, abs_z = abs(nx), abs(ny), abs(nz)
    if abs_y >= abs_x and abs_y >= abs_z:
        return "up" if ny > 0 else "down"
    elif abs_x >= abs_z:
        return "east" if nx > 0 else "west"
    else:
        return "south" if nz > 0 else "north"


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
                    if ni >= 0 and ni < len(normals):
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


def get_entity_facing_angle_y(facing: str) -> float:
    """Return Y-rotation angle in degrees for entity models whose unrotated front is South."""
    facing_map = {
        "south": 0.0,
        "north": 180.0,
        "east": 90.0,
        "west": 270.0,
    }
    return facing_map.get(facing.lower(), 0.0)


def get_block_facing_angle_y(facing: str) -> float:
    """Return Y-rotation angle in degrees for block models whose default unrotated front is North."""
    facing_map = {
        "north": 0.0,
        "east": 90.0,
        "south": 180.0,
        "west": 270.0,
    }
    return facing_map.get(facing.lower(), 0.0)


def build_baked_model_from_obj(
    block_state: str,
    obj_filename: str,
    sub_object: Optional[str] = None,
    material_override: Optional[str] = None,
    material_map: Optional[dict[str, str]] = None,
    rot_y: float = 0.0,
) -> Optional[BakedModel]:
    """
    Construct a canonical BakedModel from an author-crafted OBJ model file.
    Applies exact Y-rotation and maps UV coordinates to standard BakedFace data.
    """
    obj_data = _OBJ_CACHE.load(obj_filename)
    if not obj_data:
        return None

    if sub_object:
        faces_list = obj_data.get(sub_object, [])
    else:
        faces_list = [f for obj_faces in obj_data.values() for f in obj_faces]

    if not faces_list:
        return None

    elements: list[BakedElement] = []
    face_objects: list[BakedFace] = []

    for i, f_data in enumerate(faces_list):
        raw_verts = f_data["verts"]
        raw_uvs = f_data["uvs"]
        orig_mtl = f_data.get("mtl", "")

        # 1. Resolve Texture ID
        if material_override:
            tex_id = material_override
        elif material_map and orig_mtl in material_map:
            tex_id = material_map[orig_mtl]
        elif orig_mtl:
            tex_id = f"minecraft:{orig_mtl}" if ":" not in orig_mtl else orig_mtl
        else:
            tex_id = "minecraft:block/dirt"

        # 2. Transform Vertices by rot_y and convert from centered [-0.5, 0.5] to block space [0..1]
        rotated_mc_verts = []
        for v in raw_verts:
            vr = rotate_y(v, rot_y)
            # Centered [-0.5, 0.5] -> [0.0, 1.0]
            rotated_mc_verts.append((vr[0] + 0.5, vr[1] + 0.5, vr[2] + 0.5))

        # 3. Calculate Normal & Direction
        if len(rotated_mc_verts) >= 3:
            norm = calculate_normal(rotated_mc_verts[0], rotated_mc_verts[1], rotated_mc_verts[2])
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
            vertices=tuple(rotated_mc_verts),
            uvs=tuple(mc_uvs),
        )
        face_objects.append(baked_face)

        # Build element container
        xs = [v[0] for v in rotated_mc_verts]
        ys = [v[1] for v in rotated_mc_verts]
        zs = [v[2] for v in rotated_mc_verts]
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


def resolve_obj_model_for_state(
    block_id: str,
    props: dict[str, str],
    fallback_texture: str = ""
) -> Optional[BakedModel]:
    """
    Dispatcher that resolves known Block Entity / special model blocks to their 1:1 OBJ models.
    Returns None if the block should use standard JSON models.
    """
    short_name = block_id.split(":", 1)[-1]
    name_no_wax = short_name.removeprefix("waxed_")

    # 1. Chests
    if name_no_wax in (
        "chest", "trapped_chest", "ender_chest",
        "copper_chest", "exposed_copper_chest", "weathered_copper_chest", "oxidized_copper_chest"
    ):
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
            block_state=f"{block_id}[{','.join(f'{k}={v}' for k, v in sorted(props.items()))}]" if props else block_id,
            obj_filename="chest.obj",
            sub_object=sub_obj,
            material_override=mat_id,
            rot_y=rot_y,
        )

    # 2. Bell
    if short_name == "bell":
        facing = props.get("facing", "north").lower()
        rot_y = get_block_facing_angle_y(facing)
        return build_baked_model_from_obj(
            block_state=f"{block_id}[{','.join(f'{k}={v}' for k, v in sorted(props.items()))}]" if props else block_id,
            obj_filename="bell.obj",
            material_override="minecraft:entity/bell/bell_body",
            rot_y=rot_y,
        )

    # 3. Decorated Pot
    if short_name == "decorated_pot":
        return build_baked_model_from_obj(
            block_state=block_id,
            obj_filename="decorated_pot.obj",
            material_override="minecraft:entity/decorated_pot/decorated_pot_base",
            rot_y=0.0,
        )

    # 4. Banners
    if short_name.endswith("_banner") or short_name.endswith("_wall_banner"):
        is_wall = "_wall_banner" in short_name
        obj_file = "banner_wall.obj" if is_wall else "banner_standing.obj"
        if is_wall:
            facing = props.get("facing", "north").lower()
            rot_y = get_block_facing_angle_y(facing)
        else:
            rot_idx = int(props.get("rotation", "0")) if "rotation" in props else 0
            rot_y = (180.0 - rot_idx * 22.5) % 360.0

        return build_baked_model_from_obj(
            block_state=f"{block_id}[{','.join(f'{k}={v}' for k, v in sorted(props.items()))}]" if props else block_id,
            obj_filename=obj_file,
            material_override="minecraft:entity/banner/banner_base",
            rot_y=rot_y,
        )

    # 5. Skulls and Heads
    if short_name.endswith(("_head", "_skull", "_wall_head", "_wall_skull")):
        is_wall = "_wall_" in short_name
        is_dragon = "dragon" in short_name

        if is_dragon:
            obj_file = "dragon_wall_head.obj" if is_wall else "dragon_head.obj"
        else:
            obj_file = "player_head.obj"

        if is_wall:
            facing = props.get("facing", "north").lower()
            rot_y = get_block_facing_angle_y(facing)
        else:
            rot_idx = int(props.get("rotation", "0")) if "rotation" in props else 0
            rot_y = (180.0 - rot_idx * 22.5) % 360.0

        # Texture mapping
        head_type = short_name.replace("_wall_", "_").removesuffix("_skull").removesuffix("_head")
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
        elif head_type == "dragon":
            mat = "minecraft:entity/enderdragon/dragon"
        else:
            mat = "minecraft:entity/player/wide/steve"

        return build_baked_model_from_obj(
            block_state=f"{block_id}[{','.join(f'{k}={v}' for k, v in sorted(props.items()))}]" if props else block_id,
            obj_filename=obj_file,
            material_override=mat,
            rot_y=rot_y,
        )

    # 6. Hanging Signs
    if "hanging_sign" in short_name:
        facing = props.get("facing", props.get("rotation", "north"))
        rot_y = get_block_facing_angle_y(str(facing)) if not str(facing).isdigit() else (int(facing) * 22.5) % 360.0
        wood_type = short_name.replace("_wall_hanging_sign", "").replace("_hanging_sign", "")
        return build_baked_model_from_obj(
            block_state=f"{block_id}[{','.join(f'{k}={v}' for k, v in sorted(props.items()))}]" if props else block_id,
            obj_filename="hanging_sign.obj",
            material_override=f"minecraft:entity/signs/hanging/{wood_type}" if wood_type else "minecraft:entity/signs/hanging/oak",
            rot_y=rot_y,
        )

    return None
