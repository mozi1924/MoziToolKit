"""
OBJ Model Loader & Registry for Minecraft Block Entity models.
Loads 1:1 author-crafted models from jmc2obj (GPL v2) and authoritative Block Entity models
(Chests, Shulker Boxes, End Portal Frame, End Portal, End Gateway, Banners, Heads, Bells, Pots, Conduits, Hanging Signs)
with dynamic texture substitution and transformations conforming to upstream jmc2obj.
"""

from __future__ import annotations
import math
from pathlib import Path
from typing import Optional, Any, Tuple, Union, Sequence

from .types import BakedModel, BakedElement, BakedFace, MC_DIRECTIONS

MODELS_DIR = Path(__file__).parent / "assets" / "models"

Vec3 = Tuple[float, float, float]
Vec2 = Tuple[float, float]


def jmc_rotate_y(v: Vec3, deg: float) -> Vec3:
    """
    Rotate a point (x, y, z) around origin (0, 0, 0) by deg degrees matching jmc2obj Transform.rotation(0, deg, 0).
    Formula: x' = x*cos(b) - z*sin(b), z' = x*sin(b) + z*cos(b).
    """
    if deg == 0.0:
        return v
    rad = math.radians(deg)
    c = math.cos(rad)
    s = math.sin(rad)
    x, y, z = v
    nx = x * c - z * s
    nz = x * s + z * c
    return (nx, y, nz)


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
        x, y, z = jmc_rotate_y((x, y, z), rot_y)
    # 3. Translate
    tx, ty, tz = offset
    return (x + tx, y + ty, z + tz)


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
    """
    Return Y-rotation angle in degrees for entity models whose unrotated front is South (+Z).
    South: 0, North: 180, East: 270 (-90), West: 90.
    """
    facing_map = {
        "south": 0.0,
        "north": 180.0,
        "east": 270.0,
        "west": 90.0,
    }
    return facing_map.get(facing.lower(), 0.0)


def get_block_facing_angle_y(facing: str) -> float:
    """
    Return Y-rotation angle in degrees for block models whose default unrotated front is North (-Z).
    North: 0, East: 90, South: 180, West: 270.
    """
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
    sub_objects: Optional[Union[str, Sequence[str]]] = None,
    material_override: Optional[str] = None,
    material_map: Optional[dict[str, str]] = None,
    scale: Vec3 = (1.0, 1.0, 1.0),
    rot_y: float = 0.0,
    offset: Vec3 = (0.0, 0.0, 0.0),
) -> Optional[BakedModel]:
    """
    Construct a canonical BakedModel from an author-crafted OBJ model file.
    Applies exact scaling, Y-rotation, and translation offsets conforming to upstream jmc2obj.
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

        # 2. Transform Vertices: Scale -> Rotate Y -> Offset -> Convert to MC block space [0..1]
        transformed_mc_verts = []
        for v in raw_verts:
            vt = transform_obj_point(v, scale=scale, rot_y=rot_y, offset=offset)
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
    """Rotate a vertex around block center (0, 0, 0) for the 6 Minecraft Shulker Box facings."""
    x, y, z = v
    facing_lower = facing.lower()
    if facing_lower == "up":
        return (x, y, z)
    elif facing_lower == "down":
        return (x, -y, -z)
    elif facing_lower == "north":
        return (x, z, -y)
    elif facing_lower == "south":
        return (x, -z, y)
    elif facing_lower == "west":
        return (-y, x, z)
    elif facing_lower == "east":
        return (y, -x, z)
    return (x, y, z)


def build_shulker_box_model(block_state: str, short_name: str, props: dict[str, str]) -> BakedModel:
    """
    Construct a pixel-perfect Shulker Box model (Lid & Base) with authoritative 64x64 entity texture UVs.
    Supports all 16 colors + undyed across all 6 directional facings.
    """
    color = short_name.removesuffix("_shulker_box")
    if color == "shulker_box" or not color:
        tex_id = "minecraft:entity/shulker/shulker"
    else:
        tex_id = f"minecraft:entity/shulker/shulker_{color}"

    facing = props.get("facing", "up").lower()

    # Base & Lid parts in canonical "up" facing centered [-0.5, 0.5]:
    # Base: from [-0.5, -0.5, -0.5] to [0.5, 0.0, 0.5] (16x8x16, Y in [0, 8])
    # Lid:  from [-0.5, 0.0, -0.5]  to [0.5, 0.5, 0.5] (16x8x16, Y in [8, 16])
    parts = [
        # --- Base ---
        {
            "bounds": ((-0.5, -0.5, -0.5), (0.5, 0.0, 0.5)),
            "faces": {
                "up": (
                    [(-0.5, 0.0, 0.5), (0.5, 0.0, 0.5), (0.5, 0.0, -0.5), (-0.5, 0.0, -0.5)], # SW, SE, NE, NW
                    ((16/64, 44/64), (32/64, 44/64), (32/64, 28/64), (16/64, 28/64))
                ),
                "down": (
                    [(-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, -0.5, 0.5), (-0.5, -0.5, 0.5)], # NW, NE, SE, SW
                    ((32/64, 28/64), (48/64, 28/64), (48/64, 44/64), (32/64, 44/64))
                ),
                "north": (
                    [(0.5, -0.5, -0.5), (-0.5, -0.5, -0.5), (-0.5, 0.0, -0.5), (0.5, 0.0, -0.5)], # BR, BL, TL, TR
                    ((32/64, 52/64), (16/64, 52/64), (16/64, 44/64), (32/64, 44/64))
                ),
                "south": (
                    [(-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.5, 0.0, 0.5), (-0.5, 0.0, 0.5)], # BL, BR, TR, TL
                    ((48/64, 52/64), (64/64, 52/64), (64/64, 44/64), (48/64, 44/64))
                ),
                "west": (
                    [(-0.5, -0.5, -0.5), (-0.5, -0.5, 0.5), (-0.5, 0.0, 0.5), (-0.5, 0.0, -0.5)], # BL, BR, TR, TL
                    ((0/64, 52/64), (16/64, 52/64), (16/64, 44/64), (0/64, 44/64))
                ),
                "east": (
                    [(0.5, -0.5, 0.5), (0.5, -0.5, -0.5), (0.5, 0.0, -0.5), (0.5, 0.0, 0.5)], # BL, BR, TR, TL
                    ((32/64, 52/64), (48/64, 52/64), (48/64, 44/64), (32/64, 44/64))
                ),
            }
        },
        # --- Lid ---
        {
            "bounds": ((-0.5, 0.0, -0.5), (0.5, 0.5, 0.5)),
            "faces": {
                "up": (
                    [(-0.5, 0.5, 0.5), (0.5, 0.5, 0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5)], # SW, SE, NE, NW
                    ((16/64, 16/64), (32/64, 16/64), (32/64, 0/64), (16/64, 0/64))
                ),
                "down": (
                    [(-0.5, 0.0, -0.5), (0.5, 0.0, -0.5), (0.5, 0.0, 0.5), (-0.5, 0.0, 0.5)], # NW, NE, SE, SW
                    ((32/64, 0/64), (48/64, 0/64), (48/64, 16/64), (32/64, 16/64))
                ),
                "north": (
                    [(0.5, 0.0, -0.5), (-0.5, 0.0, -0.5), (-0.5, 0.5, -0.5), (0.5, 0.5, -0.5)], # BR, BL, TL, TR
                    ((32/64, 24/64), (16/64, 24/64), (16/64, 16/64), (32/64, 16/64))
                ),
                "south": (
                    [(-0.5, 0.0, 0.5), (0.5, 0.0, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5)], # BL, BR, TR, TL
                    ((48/64, 24/64), (64/64, 24/64), (64/64, 16/64), (48/64, 16/64))
                ),
                "west": (
                    [(-0.5, 0.0, -0.5), (-0.5, 0.0, 0.5), (-0.5, 0.5, 0.5), (-0.5, 0.5, -0.5)], # BL, BR, TR, TL
                    ((0/64, 24/64), (16/64, 24/64), (16/64, 16/64), (0/64, 16/64))
                ),
                "east": (
                    [(0.5, 0.0, 0.5), (0.5, 0.0, -0.5), (0.5, 0.5, -0.5), (0.5, 0.5, 0.5)], # BL, BR, TR, TL
                    ((32/64, 24/64), (48/64, 24/64), (48/64, 16/64), (32/64, 16/64))
                ),
            }
        }
    ]

    elements: list[BakedElement] = []
    face_objects: list[BakedFace] = []

    for part in parts:
        elem_faces: dict[str, BakedFace] = {}
        for d, (raw_v, raw_uvs) in part["faces"].items():
            # Rotate vertices according to facing
            rot_mc_verts = []
            for v in raw_v:
                vr = rotate_shulker_vertex(v, facing)
                rot_mc_verts.append((vr[0] + 0.5, vr[1] + 0.5, vr[2] + 0.5))

            norm = calculate_normal(rot_mc_verts[0], rot_mc_verts[1], rot_mc_verts[2])
            calc_dir = normal_to_mc_direction(norm)

            min_u = min(u for u, _ in raw_uvs)
            max_u = max(u for u, _ in raw_uvs)
            min_v = min(v for _, v in raw_uvs)
            max_v = max(v for _, v in raw_uvs)

            bf = BakedFace(
                direction=calc_dir,
                texture=tex_id,
                uv_bounds=(min_u, min_v, max_u, max_v),
                vertices=tuple(rot_mc_verts),
                uvs=raw_uvs,
            )
            elem_faces[calc_dir] = bf
            face_objects.append(bf)

        xs = [v[0] for f in elem_faces.values() for v in f.vertices]
        ys = [v[1] for f in elem_faces.values() for v in f.vertices]
        zs = [v[2] for f in elem_faces.values() for v in f.vertices]
        elements.append(BakedElement(
            from_pos=(min(xs) * 16.0, min(ys) * 16.0, min(zs) * 16.0),
            to_pos=(max(xs) * 16.0, max(ys) * 16.0, max(zs) * 16.0),
            faces=elem_faces
        ))

    six_faces = []
    for d in MC_DIRECTIONS:
        match = next((f for f in face_objects if f.direction == d), None)
        six_faces.append(match if match else face_objects[0])

    return BakedModel(
        block_state=block_state,
        elements=elements,
        faces=six_faces,
        is_cube=True,
        is_opaque=True,
    )


def build_conduit_model(block_state: str) -> BakedModel:
    """Construct the Conduit 6x6x6 centered cube model with 32x16 texture UVs."""
    tex_id = "minecraft:entity/conduit/base"
    x0, y0, z0 = 5/16, 5/16, 5/16
    x1, y1, z1 = 11/16, 11/16, 11/16

    face_defs = {
        "up": (
            [(x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)],
            ((6/32, 6/16), (12/32, 6/16), (12/32, 0/16), (6/32, 0/16))
        ),
        "down": (
            [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
            ((12/32, 0/16), (18/32, 0/16), (18/32, 6/16), (12/32, 6/16))
        ),
        "north": (
            [(x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0)],
            ((12/32, 12/16), (6/32, 12/16), (6/32, 6/16), (12/32, 6/16))
        ),
        "south": (
            [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
            ((18/32, 12/16), (24/32, 12/16), (24/32, 6/16), (18/32, 6/16))
        ),
        "west": (
            [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)],
            ((0/32, 12/16), (6/32, 12/16), (6/32, 6/16), (0/32, 6/16))
        ),
        "east": (
            [(x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1)],
            ((12/32, 12/16), (18/32, 12/16), (18/32, 6/16), (12/32, 6/16))
        ),
    }

    elem_faces = {}
    face_objects = []
    for d, (raw_v, raw_uvs) in face_defs.items():
        min_u = min(u for u, _ in raw_uvs)
        max_u = max(u for u, _ in raw_uvs)
        min_v = min(v for _, v in raw_uvs)
        max_v = max(v for _, v in raw_uvs)
        bf = BakedFace(
            direction=d,
            texture=tex_id,
            uv_bounds=(min_u, min_v, max_u, max_v),
            vertices=tuple(raw_v),
            uvs=raw_uvs,
        )
        elem_faces[d] = bf
        face_objects.append(bf)

    elem = BakedElement(from_pos=(5.0, 5.0, 5.0), to_pos=(11.0, 11.0, 11.0), faces=elem_faces)
    return BakedModel(
        block_state=block_state,
        elements=[elem],
        faces=face_objects,
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
    # Top face at Y=0.75, normal pointing UP
    top_v = [(0.0, 0.75, 1.0), (1.0, 0.75, 1.0), (1.0, 0.75, 0.0), (0.0, 0.75, 0.0)]
    top_uvs = ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0))
    bf_top = BakedFace(
        direction="up",
        texture=tex_id,
        uv_bounds=(0.0, 0.0, 1.0, 1.0),
        vertices=tuple(top_v),
        uvs=top_uvs,
    )

    # Bottom face at Y=0.75, normal pointing DOWN (conforming to PortalHoriz.java)
    bot_v = [(1.0, 0.75, 1.0), (0.0, 0.75, 1.0), (0.0, 0.75, 0.0), (1.0, 0.75, 0.0)]
    bot_uvs = ((1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0))
    bf_bot = BakedFace(
        direction="down",
        texture=tex_id,
        uv_bounds=(0.0, 0.0, 1.0, 1.0),
        vertices=tuple(bot_v),
        uvs=bot_uvs,
    )

    elem = BakedElement(from_pos=(0.0, 12.0, 0.0), to_pos=(16.0, 12.0, 16.0), faces={"up": bf_top, "down": bf_bot})
    six_faces = [bf_top, bf_bot, bf_top, bf_top, bf_top, bf_top]
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
    face_defs = {
        "up": (
            [(0.0, 1.0, 1.0), (1.0, 1.0, 1.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
            ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0))
        ),
        "down": (
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 0.0, 1.0)],
            ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
        ),
        "north": (
            [(1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)],
            ((1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0))
        ),
        "south": (
            [(0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0)],
            ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0))
        ),
        "west": (
            [(0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 1.0), (0.0, 1.0, 0.0)],
            ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0))
        ),
        "east": (
            [(1.0, 0.0, 1.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (1.0, 1.0, 1.0)],
            ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0))
        ),
    }

    elem_faces = {}
    face_objects = []
    for d, (raw_v, raw_uvs) in face_defs.items():
        bf = BakedFace(
            direction=d,
            texture=tex_id,
            uv_bounds=(0.0, 0.0, 1.0, 1.0),
            vertices=tuple(raw_v),
            uvs=raw_uvs,
        )
        elem_faces[d] = bf
        face_objects.append(bf)

    elem = BakedElement(from_pos=(0.0, 0.0, 0.0), to_pos=(16.0, 16.0, 16.0), faces=elem_faces)
    return BakedModel(
        block_state=block_state,
        elements=[elem],
        faces=face_objects,
        is_cube=True,
        is_opaque=True,
        is_emissive=True,
    )


# ---------------------------------------------------------------------------
# Primary Dispatcher
# ---------------------------------------------------------------------------

def resolve_obj_model_for_state(
    block_id: str,
    props: dict[str, str],
    fallback_texture: str = ""
) -> Optional[BakedModel]:
    """
    Dispatcher that resolves known Block Entity / special model blocks to their 1:1 OBJ models.
    Applies exact transforms conforming to upstream jmc2obj.
    """
    short_name = block_id.split(":", 1)[-1]
    name_no_wax = short_name.removeprefix("waxed_")
    state_str = f"{block_id}[{','.join(f'{k}={v}' for k, v in sorted(props.items()))}]" if props else block_id

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
            block_state=state_str,
            obj_filename="chest.obj",
            sub_objects=sub_obj,
            material_override=mat_id,
            rot_y=rot_y,
        )

    # 2. Shulker Boxes (all 16 colors + undyed)
    if short_name == "shulker_box" or short_name.endswith("_shulker_box"):
        return build_shulker_box_model(state_str, short_name, props)

    # 3. End Portal Frame (with / without eye of ender)
    if short_name == "end_portal_frame":
        has_eye = props.get("eye", "false").lower() == "true"
        sub_objs = ["base", "eye"] if has_eye else ["base"]
        facing = props.get("facing", "north").lower()
        rot_y = get_block_facing_angle_y(facing)

        return build_baked_model_from_obj(
            block_state=state_str,
            obj_filename="endportal_frame.obj",
            sub_objects=sub_objs,
            material_map={
                "block/end_portal_frame_eye": "minecraft:block/end_portal_frame_eye",
                "block/end_portal_frame_side": "minecraft:block/end_portal_frame_side",
                "block/end_portal_frame_top": "minecraft:block/end_portal_frame_top",
                "block/end_stone": "minecraft:block/end_stone",
            },
            rot_y=rot_y,
        )

    # 4. End Portal (horizontal portal plane at Y=0.75)
    if short_name == "end_portal":
        return build_end_portal_model(state_str)

    # 5. End Gateway (FULL 1x1x1 solid block)
    if short_name == "end_gateway":
        return build_end_gateway_model(state_str)

    # 6. Conduit
    if short_name == "conduit":
        return build_conduit_model(state_str)

    # 7. Bell
    if short_name == "bell":
        facing = props.get("facing", "north").lower()
        rot_y = get_block_facing_angle_y(facing)
        return build_baked_model_from_obj(
            block_state=state_str,
            obj_filename="bell.obj",
            material_map={
                "block/bell_top": "minecraft:block/bell_top",
                "block/bell_side": "minecraft:block/bell_side",
                "block/bell_bottom": "minecraft:block/bell_bottom",
            },
            rot_y=rot_y,
        )

    # 8. Decorated Pot
    if short_name == "decorated_pot":
        return build_baked_model_from_obj(
            block_state=state_str,
            obj_filename="decorated_pot.obj",
            material_map={
                "entity/decorated_pot/decorated_pot_base": "minecraft:entity/decorated_pot/decorated_pot_base",
                "entity/decorated_pot/decorated_pot_side": "minecraft:entity/decorated_pot/decorated_pot_side",
            },
            rot_y=0.0,
        )

    # 9. Banners (Conforming to jmc2obj Banner.java)
    if short_name.endswith(("_banner", "_wall_banner")):
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
            # jmc2obj Banner.java: rotation = 90 + (360/16)*dataRot
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

    # 10. Skulls and Heads (Conforming to jmc2obj Head.java)
    if short_name.endswith(("_head", "_skull", "_wall_head", "_wall_skull")):
        is_wall = "_wall_" in short_name
        is_dragon = "dragon" in short_name

        if is_dragon:
            obj_file = "dragon_wall_head.obj" if is_wall else "dragon_head.obj"
            if is_wall:
                facing = props.get("facing", "north").lower()
                rot_y = {"north": 180.0, "south": 0.0, "west": 90.0, "east": 270.0}.get(facing, 180.0)
            else:
                rot_idx = int(props.get("rotation", "0")) if "rotation" in props else 0
                rot_y = (180.0 - rot_idx * 22.5) % 360.0
            offset = (0.0, 0.0, 0.0)
            scale = (1.0, 1.0, 1.0)
            mat = "minecraft:entity/enderdragon/dragon"
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

    # 11. Hanging Signs (Conforming to jmc2obj SignHanging.java / SignHangingWall.java)
    if "hanging_sign" in short_name:
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

    return None
