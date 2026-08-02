import math
import mathutils
import bpy
from .types import ExtrudeRepairConfig
from .uv_analyzer import is_face_uv_collapsed, get_active_texture_pixel_step


def repair_extruded_side_faces(
    bm,
    repair_uv: bool = True,
    add_crease: bool = False,
    crease_val: float = 1.0,
    only_collapsed: bool = False,
    uv_mode: str = "INWARD",
) -> int:
    """Repair UV overlapping and add Mean Crease to side faces created during face extrusion.

    :param bm: BMesh instance in edit mode.
    :param repair_uv: Whether to project and fix UVs on extruded side faces.
    :param add_crease: Whether to add Mean Crease to side edges.
    :param crease_val: Crease weight value (0.0 to 1.0).
    :param only_collapsed: If True, only repair collapsed side faces or active extruded side faces.
    :param uv_mode: 'INWARD' (use face pixel color/shrink inward) or 'OUTWARD' (extend UV box outward).
    :return: Number of repaired side faces.
    """
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.verts.ensure_lookup_table()

    uv_layer = bm.loops.layers.uv.verify()
    crease_layer = bm.edges.layers.float.get("crease_edge") or bm.edges.layers.float.new("crease_edge")

    p_step = get_active_texture_pixel_step()

    selected_faces = [f for f in bm.faces if f.select and f.is_valid]
    if not selected_faces:
        return 0

    selected_faces_set = set(selected_faces)
    repaired_count = 0

    # Calculate center of the ENTIRE selected region in UV space
    region_uv_center = mathutils.Vector((0.0, 0.0))
    total_loops = 0
    for f in selected_faces:
        for l in f.loops:
            region_uv_center += l[uv_layer].uv
            total_loops += 1
    if total_loops > 0:
        region_uv_center /= total_loops

    for top_face in selected_faces:
        ref_vert_uv = {l.vert: l[uv_layer].uv.copy() for l in top_face.loops}

        for e in top_face.edges:
            unselected_adj_faces = [f for f in e.link_faces if f not in selected_faces_set and f.is_valid]
            if not unselected_adj_faces:
                continue

            for side_face in unselected_adj_faces:
                if len(side_face.verts) != 4:
                    continue

                v_top_a = e.verts[0] if e.verts[0] in ref_vert_uv else e.verts[1]
                v_top_b = e.verts[1] if v_top_a == e.verts[0] else e.verts[0]

                if v_top_a not in ref_vert_uv or v_top_b not in ref_vert_uv:
                    continue

                base_verts = [v for v in side_face.verts if v not in (v_top_a, v_top_b)]
                if len(base_verts) != 2:
                    continue

                if only_collapsed and not is_face_uv_collapsed(side_face, uv_layer):
                    continue

                v_base_a = None
                v_base_b = None
                for se in side_face.edges:
                    if v_top_a in se.verts:
                        other = se.verts[0] if se.verts[0] != v_top_a else se.verts[1]
                        if other in base_verts:
                            v_base_a = other
                    if v_top_b in se.verts:
                        other = se.verts[0] if se.verts[0] != v_top_b else se.verts[1]
                        if other in base_verts:
                            v_base_b = other

                if not v_base_a or not v_base_b or v_base_a == v_base_b:
                    continue

                if repair_uv or only_collapsed:
                    uv_a = ref_vert_uv[v_top_a]
                    uv_b = ref_vert_uv[v_top_b]

                    l_3d = (v_top_b.co - v_top_a.co).length
                    u_edge = uv_b - uv_a
                    l_uv = u_edge.length

                    h_3d = (v_base_a.co - v_top_a.co).length
                    ratio = (h_3d / l_3d) if l_3d > 1e-6 else 1.0
                    h_uv = l_uv * ratio

                    # Calculate outward direction perpendicular to boundary edge
                    edge_uv_mid = (uv_a + uv_b) * 0.5
                    v_out = edge_uv_mid - region_uv_center
                    if u_edge.length > 1e-6:
                        perp = mathutils.Vector((-u_edge.y, u_edge.x))
                        if perp.dot(v_out) < 0:
                            perp = -perp
                        uv_outward_dir = perp.normalized()
                    else:
                        uv_outward_dir = mathutils.Vector((1.0, 0.0))

                    if only_collapsed:
                        uv_top_a_pt = None
                        uv_base_a_pt = None
                        for l in side_face.loops:
                            if l.vert == v_top_a:
                                uv_top_a_pt = l[uv_layer].uv
                            elif l.vert == v_base_a:
                                uv_base_a_pt = l[uv_layer].uv

                        height_uv_dir = (
                            abs((uv_top_a_pt - uv_base_a_pt).dot(uv_outward_dir))
                            if (uv_top_a_pt and uv_base_a_pt)
                            else 0.0
                        )
                        is_unrepaired = (height_uv_dir < 1e-4) or is_face_uv_collapsed(
                            side_face, uv_layer
                        )
                        if not is_unrepaired:
                            continue

                if add_crease:
                    for se in side_face.edges:
                        se[crease_layer] = crease_val

                if repair_uv:
                    if uv_mode == "INWARD":
                        h_uv = min(h_uv, l_uv)
                        uv_dir = -uv_outward_dir
                    else:
                        uv_dir = uv_outward_dir

                    uv_base_a_val = uv_a.copy()
                    uv_base_b_val = uv_b.copy()

                    if uv_mode == "OUTWARD" and p_step > 0:
                        if abs(uv_outward_dir.x) > 0.5:
                            if uv_outward_dir.x > 0:
                                uv_base_a_val.x = math.ceil(uv_a.x / p_step - 1e-5) * p_step
                                uv_base_b_val.x = math.ceil(uv_b.x / p_step - 1e-5) * p_step
                            else:
                                uv_base_a_val.x = math.floor(uv_a.x / p_step + 1e-5) * p_step
                                uv_base_b_val.x = math.floor(uv_b.x / p_step + 1e-5) * p_step
                        elif abs(uv_outward_dir.y) > 0.5:
                            if uv_outward_dir.y > 0:
                                uv_base_a_val.y = math.ceil(uv_a.y / p_step - 1e-5) * p_step
                                uv_base_b_val.y = math.ceil(uv_b.y / p_step - 1e-5) * p_step
                            else:
                                uv_base_a_val.y = math.floor(uv_a.y / p_step + 1e-5) * p_step
                                uv_base_b_val.y = math.floor(uv_b.y / p_step + 1e-5) * p_step

                    uv_top_a_val = uv_base_a_val + uv_dir * h_uv
                    uv_top_b_val = uv_base_b_val + uv_dir * h_uv

                    for l in side_face.loops:
                        if l.vert == v_top_a:
                            l[uv_layer].uv = uv_top_a_val.copy()
                        elif l.vert == v_top_b:
                            l[uv_layer].uv = uv_top_b_val.copy()
                        elif l.vert == v_base_a:
                            l[uv_layer].uv = uv_base_a_val.copy()
                        elif l.vert == v_base_b:
                            l[uv_layer].uv = uv_base_b_val.copy()

                repaired_count += 1

    return repaired_count
