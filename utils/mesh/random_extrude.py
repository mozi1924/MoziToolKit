"""
Random Extrude Core Utility Module for MoziToolKit.

Orchestrates BMesh face extrusion, normal updates, noise height generation,
and side-face UV/crease repair accelerated via Rust libmtk Data In, Data Out architecture.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Sequence, Set, Tuple

try:
    import bmesh
    import bpy
    import mathutils
    HAS_BPY = True
except ImportError:
    bmesh = None
    bpy = None
    mathutils = None
    HAS_BPY = False

try:
    from ...bridge.extrude import (
        generate_random_extrude_heights,
        process_flat_mesh_extrude_repair,
    )
except (ImportError, ValueError):
    from bridge.extrude import (
        generate_random_extrude_heights,
        process_flat_mesh_extrude_repair,
    )

logger = logging.getLogger("MoziToolKit.Utils.Mesh.RandomExtrude")


def get_face_pixel_step(
    face,
    obj=None,
    context=None,
    uv_layer=None,
    default_res: Tuple[int, int] = (16, 16),
) -> Tuple[float, float]:
    """Retrieve anisotropic 2D UV step (step_u, step_v) for 1 pixel on a face's texture.

    Supports:
    - ATLAS_UNIFIED (Local UVs corresponding to tile_size)
    - ATLAS_CHUNK (Baked Atlas UVs or Local UVs)
    - STANDALONE_BAKED (Animated strips with baked UVs)
    - STANDALONE / GENERIC (Non-square or square single textures)
    """
    active_obj = obj or (bpy.context.active_object if bpy and hasattr(bpy, "context") else None)

    if active_obj is not None:
        try:
            if hasattr(face, "material_index") and face.material_index < len(active_obj.material_slots):
                mat = active_obj.material_slots[face.material_index].material
                if mat and getattr(mat, "node_tree", None):
                    decoder_node = next(
                        (
                            n for n in mat.node_tree.nodes
                            if (n.type == "GROUP" and n.node_tree and "Atlas_UV_Decoder" in n.node_tree.name)
                            or n.name == "MC Atlas UV Decoder"
                        ),
                        None
                    )
                    if decoder_node and "Tile Size" in decoder_node.inputs:
                        ts = int(round(decoder_node.inputs["Tile Size"].default_value))
                        if ts > 0:
                            return (1.0 / ts, 1.0 / ts)

                    for n in mat.node_tree.nodes:
                        if n.type == "TEX_IMAGE" and n.image and n.image.size[0] > 0 and n.image.size[1] > 0:
                            raw_w, raw_h = int(n.image.size[0]), int(n.image.size[1])
                            if raw_h > raw_w and raw_h % raw_w == 0:
                                return (1.0 / max(1, raw_w), 1.0 / max(1, raw_w))
                            return (1.0 / max(1, raw_w), 1.0 / max(1, raw_h))
        except Exception:
            pass

    return (1.0 / float(default_res[0]), 1.0 / float(default_res[1]))


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

    # 1. Extract Data In buffers & Call Rust backend
    smart_faces_list = list(smart_side_face_indices) if smart_side_face_indices else None

    positions_flat = [coord for v in bm.verts for coord in (v.co.x, v.co.y, v.co.z)]
    loop_vertices = [v.index for f in bm.faces for v in f.verts]
    loop_uvs = []
    face_loop_starts = []
    face_loop_totals = []
    face_materials = []
    pixel_steps = []
    offset = 0

    for f in bm.faces:
        tot = len(f.verts)
        face_loop_starts.append(offset)
        face_loop_totals.append(tot)
        offset += tot
        face_materials.append(f.material_index)
        if uv_layer:
            for l in f.loops:
                uv = l[uv_layer].uv
                loop_uvs.extend((uv.x, uv.y))
            step_u, step_v = get_face_pixel_step(f, obj=obj, context=context, uv_layer=uv_layer)
            pixel_steps.append([step_u, step_v])
        else:
            loop_uvs.extend([0.0, 0.0] * tot)
            pixel_steps.append([1.0 / 64.0, 1.0 / 64.0])

    import time
    t0_rep = time.perf_counter()
    modified_uvs, modified_mats, modified_creases, repaired_count = process_flat_mesh_extrude_repair(
        positions=positions_flat,
        loop_vertices=loop_vertices,
        loop_uvs=loop_uvs,
        face_loop_starts=face_loop_starts,
        face_loop_totals=face_loop_totals,
        face_materials=face_materials,
        selected_faces=selected_faces,
        pixel_steps=pixel_steps,
        uv_mode=uv_mode,
        repair_uv=repair_uv,
        add_crease=add_crease,
        crease_val=crease_val,
        only_collapsed=only_collapsed,
        smart_side_faces=smart_faces_list,
    )
    rep_ms = (time.perf_counter() - t0_rep) * 1000.0

    from ..diagnostics import record_operation_profile

    record_operation_profile(
        "Extrude Repair",
        None,
        host_stages=[
            {"name": "process_flat_mesh_extrude_repair", "duration_ms": rep_ms, "items_count": repaired_count}
        ],
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
    if not HAS_BPY or bmesh is None:
        raise RuntimeError("bpy and bmesh are required for process_random_extrude_mesh_batch")

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
        for v in f.verts:
            v.select = True
        for e in f.edges:
            e.select = True
        f.normal_update()
        N = f.normal.copy()
        if N.length_squared < 1e-12:
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


# Canonical aliases
repair_extruded_side_faces = repair_mesh_extruded_side_faces_batch
process_random_extrude = process_random_extrude_mesh_batch

__all__ = [
    "get_face_pixel_step",
    "repair_mesh_extruded_side_faces_batch",
    "process_random_extrude_mesh_batch",
    "repair_extruded_side_faces",
    "process_random_extrude",
]
