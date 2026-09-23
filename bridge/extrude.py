"""
MoziToolKit Extrude & UV Repair Bridge Module.

Accelerated extruded side UV geometric reconstruction and 3D noise generation
backed strictly by Rust libmtk (libmtk_py) using a Data In, Data Out architecture.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple, Dict, Set

try:
    import bmesh
    import bpy
except ImportError:
    bmesh = None
    bpy = None

try:
    import libmtk_py as mtk_py
except ImportError:
    try:
        import mtk_py
    except ImportError:
        mtk_py = None

if mtk_py is None:
    raise ImportError(
        "libmtk_py native extension is missing. Please install the compiled extension wheel."
    )

try:
    from ..utils.extrude_repair.uv_analyzer import get_face_pixel_step
except (ImportError, ValueError):
    try:
        from utils.extrude_repair.uv_analyzer import get_face_pixel_step
    except ImportError:
        def get_face_pixel_step(f, **kwargs):
            return (1.0 / 64.0, 1.0 / 64.0)


def repair_extruded_side_uv(
    uv_base_a: Tuple[float, float],
    uv_base_b: Tuple[float, float],
    top_normal: Tuple[float, float, float],
    extrude_vec: Tuple[float, float, float],
    mode: str = "SMART",
    step_u: float = 1.0 / 16.0,
    step_v: float = 1.0 / 16.0,
    top_uv_bounds: Optional[Tuple[float, float, float, float]] = None,
    adjacent_uv_strip: Optional[Sequence[Tuple[float, float]]] = None,
) -> List[Tuple[float, float]]:
    """Reconstruct 4 UV corner coordinates for an extruded side quad polygon."""
    adj = list(adjacent_uv_strip) if adjacent_uv_strip is not None else None
    return mtk_py.repair_extruded_side_uv(
        tuple(uv_base_a),
        tuple(uv_base_b),
        tuple(top_normal),
        tuple(extrude_vec),
        mode,
        step_u,
        step_v,
        top_uv_bounds,
        adj,
    )


def generate_random_extrude_heights(
    centers: Sequence[Tuple[float, float, float]],
    noise_type: str = "RANDOM",
    min_height: float = 0.0,
    max_height: float = 1.0,
    noise_scale: float = 1.0,
    seed: int = 1234,
    discrete_steps: Optional[int] = None,
) -> List[float]:
    """Generate 3D noise-based random extrusion displacement heights."""
    pts = [tuple(c) for c in centers]
    return mtk_py.generate_random_extrude_heights(
        pts, noise_type, min_height, max_height, noise_scale, seed, discrete_steps
    )


def repair_mesh_extruded_side_faces_batch(
    bm,
    obj=None,
    context=None,
    repair_uv: bool = True,
    add_crease: bool = False,
    crease_val: float = 1.0,
    only_collapsed: bool = False,
    uv_mode: str = "SMART",
    smart_side_face_indices: Optional[Set[int]] = None,
) -> int:
    """Batch Data In, Data Out pipeline for extrude side UV repair and crease assignment."""
    if not repair_uv and not add_crease:
        return 0

    bm.faces.ensure_lookup_table()
    bm.faces.index_update()
    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    bm.edges.ensure_lookup_table()
    bm.edges.index_update()

    selected_faces = [f.index for f in bm.faces if f.select and f.is_valid]
    if not selected_faces:
        return 0

    uv_layer = bm.loops.layers.uv.verify() if repair_uv else None

    # 1. Extract Data In buffers
    positions = [[v.co.x, v.co.y, v.co.z] for v in bm.verts]
    face_vertices = [[v.index for v in f.verts] for f in bm.faces]
    
    face_uvs = []
    pixel_steps = []
    face_materials = []

    for f in bm.faces:
        face_materials.append(f.material_index)
        if uv_layer:
            face_uvs.append([[l[uv_layer].uv.x, l[uv_layer].uv.y] for l in f.loops])
            step_u, step_v = get_face_pixel_step(f, obj=obj, context=context, uv_layer=uv_layer)
            pixel_steps.append([step_u, step_v])
        else:
            face_uvs.append([[0.0, 0.0] for _ in f.verts])
            pixel_steps.append([1.0 / 64.0, 1.0 / 64.0])

    # 2. Call Rust backend in single FFI batch
    modified_uvs, modified_mats, modified_creases, repaired_count = mtk_py.process_mesh_extrude_repair(
        positions=positions,
        face_vertices=face_vertices,
        face_uvs=face_uvs,
        face_materials=face_materials,
        selected_faces=selected_faces,
        pixel_steps=pixel_steps,
        uv_mode=uv_mode,
        repair_uv=repair_uv,
        add_crease=add_crease,
        crease_val=crease_val,
        only_collapsed=only_collapsed,
    )

    # 3. Apply Data Out updates back to BMesh
    if uv_layer and modified_uvs:
        for face_idx, new_uvs in modified_uvs:
            if face_idx < len(bm.faces):
                f = bm.faces[face_idx]
                if smart_side_face_indices is not None:
                    smart_side_face_indices.add(face_idx)
                for loop, (u, v) in zip(f.loops, new_uvs):
                    loop[uv_layer].uv.x = u
                    loop[uv_layer].uv.y = v

    if modified_mats:
        for face_idx, mat_idx in modified_mats:
            if face_idx < len(bm.faces):
                bm.faces[face_idx].material_index = mat_idx

    if add_crease and modified_creases:
        crease_layer = bm.edges.layers.float.get("crease_edge") or bm.edges.layers.float.new("crease_edge")
        
        # Build quick vertex pair to edge lookup
        vert_pair_to_edge = {}
        for e in bm.edges:
            v1, v2 = e.verts[0].index, e.verts[1].index
            k = (v1, v2) if v1 < v2 else (v2, v1)
            vert_pair_to_edge[k] = e

        for (v1, v2), c_val in modified_creases:
            k = (v1, v2) if v1 < v2 else (v2, v1)
            if k in vert_pair_to_edge:
                vert_pair_to_edge[k][crease_layer] = c_val

    return repaired_count


def process_random_extrude_mesh_batch(
    bm,
    min_height: float = 0.0,
    max_height: float = 0.1,
    seed: int = 0,
    noise_mode: str = "RANDOM",
    noise_scale: float = 1.0,
    repair_uv: bool = True,
    uv_mode: str = "SMART",
    add_crease: bool = False,
    crease_val: float = 1.0,
    obj=None,
    context=None,
) -> Tuple[int, int]:
    """Batch Data In, Data Out random discrete extrusion and UV repair."""
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

    centers = [(f.calc_center_median().x, f.calc_center_median().y, f.calc_center_median().z) for f in extruded_faces]

    # Generate heights via Rust
    heights = generate_random_extrude_heights(
        centers,
        noise_type=noise_mode,
        min_height=min_height,
        max_height=max_height,
        noise_scale=noise_scale,
        seed=seed,
    )

    for f, h in zip(extruded_faces, heights):
        f.select = True
        f.normal_update()
        N = f.normal.copy()
        if N.length_squared < 1e-12:
            import mathutils
            N = mathutils.Vector((0.0, 0.0, 1.0))
        else:
            N.normalize()

        for v in f.verts:
            v.co += N * h

    bm.normal_update()

    # Repair in batch using Data In Data Out
    repaired_count = repair_mesh_extruded_side_faces_batch(
        bm,
        obj=obj,
        context=context,
        repair_uv=repair_uv,
        add_crease=add_crease,
        crease_val=crease_val,
        only_collapsed=False,
        uv_mode=uv_mode,
    )

    return len(extruded_faces), repaired_count
