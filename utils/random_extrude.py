"""
Random Extrude Core Utility Module for MoziToolKit
"""

from typing import Tuple
import bmesh
import mathutils

from .extrude_repair import repair_extruded_side_faces


def process_random_extrude(
    bm: bmesh.types.BMesh,
    min_height: float = 0.0,
    max_height: float = 0.01,
    seed: int = 0,
    noise_mode: str = "RANDOM",
    noise_scale: float = 1.0,
    repair_uv: bool = True,
    uv_mode: str = "SMART",
    add_crease: bool = False,
    crease_val: float = 1.0,
) -> Tuple[int, int]:
    """
    Extrude selected faces individually along their face normals with random heights,
    and optionally repair extruded side face UVs and edge creases.

    :param bm: Active BMesh instance in edit mode.
    :param min_height: Minimum extrude distance.
    :param max_height: Maximum extrude distance.
    :param seed: Random seed for pseudo-random number generator or noise offset.
    :param noise_mode: Generator mode ("RANDOM", "PERLIN", "CELL").
    :param noise_scale: Noise frequency scale for 3D Perlin/Cell noise.
    :param repair_uv: Whether to repair UV overlap on extruded side faces.
    :param uv_mode: Side face UV mode ("SMART", "INWARD", "OUTWARD").
    :param add_crease: Whether to set edge crease on extruded faces.
    :param crease_val: Crease weight value (0.0 to 1.0).
    :return: Tuple of (extruded_faces_count, repaired_side_faces_count)
    """
    bm.faces.ensure_lookup_table()
    bm.faces.index_update()
    bm.normal_update()

    selected_faces = [f for f in bm.faces if f.select and f.is_valid]
    if not selected_faces:
        return 0, 0

    if min_height > max_height:
        min_height, max_height = max_height, min_height

    # Unselect all faces before extrusion so top faces can be uniquely selected afterwards
    for f in bm.faces:
        f.select = False

    ret = bmesh.ops.extrude_discrete_faces(bm, faces=selected_faces)
    extruded_faces = ret.get("faces", [])
    if not extruded_faces:
        return 0, 0

    if noise_mode == "RANDOM":
        mathutils.noise.seed_set(seed)

    for i, f in enumerate(extruded_faces):
        f.select = True
        f.normal_update()
        N = f.normal.copy()
        if N.length_squared < 1e-12:
            N = mathutils.Vector((0.0, 0.0, 1.0))
        else:
            N.normalize()

        if noise_mode == "RANDOM":
            rand_val = mathutils.noise.random()
        elif noise_mode in ("PERLIN", "CELL"):
            seed_vec = mathutils.Vector((seed * 13.1, seed * 17.3, seed * 19.7))
            sample_pos = (f.calc_center_median() + seed_vec) * noise_scale
            if noise_mode == "PERLIN":
                raw_val = mathutils.noise.noise(sample_pos)
            else:
                raw_val = mathutils.noise.cell(sample_pos)
            rand_val = max(0.0, min(1.0, (raw_val + 1.0) * 0.5))
        else:
            rand_val = 0.5

        h = min_height + rand_val * (max_height - min_height)

        for v in f.verts:
            v.co += N * h

    bm.normal_update()

    repaired_count = 0
    if repair_uv or add_crease:
        repaired_count = repair_extruded_side_faces(
            bm,
            repair_uv=repair_uv,
            add_crease=add_crease,
            crease_val=crease_val,
            uv_mode=uv_mode,
        )

    return len(extruded_faces), repaired_count
