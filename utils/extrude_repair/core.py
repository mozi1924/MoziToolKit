import math
import mathutils
import bpy
from .types import ExtrudeRepairConfig
from .uv_analyzer import is_face_uv_collapsed, get_active_texture_pixel_step
from ..mesh import is_hard_edge


def _resolve_smart_uv_mode(top_face, v_top_a, v_top_b, v_base_a, v_base_b) -> str:
    """Select the UV direction from the signed distance of the extrusion."""
    extrusion = ((v_top_a.co - v_base_a.co) + (v_top_b.co - v_base_b.co)) * 0.5
    normal = top_face.normal
    # Along the face normal is a protrusion: use source-face pixels.  Against
    # it is an indentation: use the UV pixels of the adjacent faces.
    if normal.length_squared > 1e-12 and extrusion.dot(normal) < -1e-6:
        return "OUTWARD"
    return "INWARD"


def _get_adjacent_face_uv_strip(
    side_face, base_a, base_b, selected_faces_set, uv_layer
):
    """Return UVs for the side edge and the direction into its adjacent face.

    After a region extrusion, the bottom edge of each newly-created side face
    is still shared with the original, unselected neighbouring face.  Its UV
    loops are therefore the only reliable source of the neighbour's texture
    pixel (UV seams mean the side face's own loops cannot be used for this).
    """
    base_edge = next(
        (
            edge
            for edge in side_face.edges
            if base_a in edge.verts and base_b in edge.verts
        ),
        None,
    )
    if base_edge is None:
        return None

    adjacent_face = next(
        (
            face
            for face in base_edge.link_faces
            if face != side_face and face.is_valid and face not in selected_faces_set
        ),
        None,
    )
    if adjacent_face is None:
        return None

    adjacent_uvs = {loop.vert: loop[uv_layer].uv.copy() for loop in adjacent_face.loops}
    if base_a not in adjacent_uvs or base_b not in adjacent_uvs:
        return None

    uv_a = adjacent_uvs[base_a]
    uv_b = adjacent_uvs[base_b]
    uv_edge = uv_b - uv_a
    if uv_edge.length_squared < 1e-12:
        return None

    # Pick the perpendicular direction that enters the neighbouring face's
    # UV island, so the generated strip samples that face rather than the
    # transparent space outside its island.
    adjacent_uv_center = sum(
        (loop[uv_layer].uv for loop in adjacent_face.loops),
        mathutils.Vector((0.0, 0.0)),
    ) / len(adjacent_face.loops)
    uv_edge_mid = (uv_a + uv_b) * 0.5
    uv_inward_dir = mathutils.Vector((-uv_edge.y, uv_edge.x)).normalized()
    if uv_inward_dir.dot(adjacent_uv_center - uv_edge_mid) < 0.0:
        uv_inward_dir = -uv_inward_dir

    return uv_a, uv_b, uv_inward_dir


def _normalize_sharp_angle(sharp_angle: float) -> float:
    """Return an angle in radians, accepting legacy saved degree values.

    Blender ANGLE properties are stored as radians.  Older versions of this
    tool declared the property as an angle but used a degree default and then
    converted it again here.  Values above pi can only come from that legacy
    representation, so convert them once for backwards-compatible scenes.
    """
    sharp_angle = max(0.0, sharp_angle)
    return math.radians(sharp_angle) if sharp_angle > math.pi else sharp_angle


def _repair_hard_edge_creases(edges, crease_layer, crease_val, sharp_angle_rad) -> bool:
    """Apply crease to every hard edge in *edges* and clear it otherwise."""
    repaired = False
    for edge in edges:
        target_val = crease_val if is_hard_edge(edge, sharp_angle_rad) else 0.0
        if abs(edge[crease_layer] - target_val) > 1e-6:
            edge[crease_layer] = target_val
            repaired = True
    return repaired


def repair_extruded_side_faces(
    bm,
    repair_uv: bool = True,
    add_crease: bool = False,
    crease_val: float = 1.0,
    only_collapsed: bool = False,
    uv_mode: str = "INWARD",
    smart_side_face_indices=None,
    sharp_angle: float = math.radians(30.0),
) -> int:
    """Repair UV overlapping and add Mean Crease to side faces created during face extrusion.

    :param bm: BMesh instance in edit mode.
    :param repair_uv: Whether to project and fix UVs on extruded side faces.
    :param add_crease: Whether to add Mean Crease to side edges.
    :param crease_val: Crease weight value (0.0 to 1.0).
    :param only_collapsed: If True, only repair collapsed side faces or active extruded side faces.
    :param uv_mode: 'SMART' (derive from extrusion direction), 'INWARD'
        (shrink side UVs into the selected face pixel), or 'OUTWARD' (use the
        pixel from each adjacent, unselected face when one exists).
    :param smart_side_face_indices: Mutable set of side-face indices belonging
        to the current interactive smart extrusion. New faces are added only
        when their UVs are collapsed, then remain tracked for direction changes.
    :param sharp_angle: Angle threshold in radians to identify sharp/hard
        edges. Legacy values greater than pi are interpreted as degrees.
    :return: Number of repaired side faces.
    """
    bm.faces.ensure_lookup_table()
    bm.faces.index_update()
    bm.edges.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    bm.normal_update()

    uv_layer = bm.loops.layers.uv.verify()
    crease_layer = bm.edges.layers.float.get("crease_edge") or bm.edges.layers.float.new("crease_edge")

    p_step = get_active_texture_pixel_step()

    selected_faces = [f for f in bm.faces if f.select and f.is_valid]
    if not selected_faces:
        return 0

    selected_faces_set = set(selected_faces)
    repaired_count = 0
    sharp_angle_rad = _normalize_sharp_angle(sharp_angle)

    for top_face in selected_faces:
        ref_vert_uv = {l.vert: l[uv_layer].uv.copy() for l in top_face.loops}
        # A selection may wrap around a 3D corner and span several separate
        # UV islands.  Its aggregate UV centre has no meaningful "inside" or
        # "outside" for an individual boundary edge, so derive that direction
        # from this source face's own UV island instead.
        top_face_uv_center = sum(
            ref_vert_uv.values(), mathutils.Vector((0.0, 0.0))
        ) / len(ref_vert_uv)

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

                    # Fixed narrow strip extension length (10% of pixel step p_step) for thin edge strip UVs
                    h_uv = (p_step * 0.1) if p_step > 0 else min(0.0015, l_uv * 0.1)

                    # Calculate the source face's outward direction.  This
                    # must be per-face rather than per-selection: selections
                    # spanning a cube corner usually have separate UV islands.
                    edge_uv_mid = (uv_a + uv_b) * 0.5
                    v_out = edge_uv_mid - top_face_uv_center
                    if u_edge.length > 1e-6:
                        perp = mathutils.Vector((-u_edge.y, u_edge.x))
                        if perp.dot(v_out) < 0:
                            perp = -perp
                        uv_outward_dir = perp.normalized()
                    else:
                        uv_outward_dir = mathutils.Vector((1.0, 0.0))

                    is_active_extrusion = (
                        v_top_a.select
                        and v_top_b.select
                        and (not v_base_a.select)
                        and (not v_base_b.select)
                    )
                    if only_collapsed:
                        is_collapsed = is_face_uv_collapsed(side_face, uv_layer)
                        if uv_mode == "SMART":
                            # A newly extruded side starts with collapsed UVs.
                            # Once found, retain only that side for the rest of
                            # this extrusion so a direction reversal can update
                            # it without treating an arbitrary selected face as
                            # a fresh extrusion.
                            if smart_side_face_indices is None:
                                if not is_collapsed:
                                    continue
                            elif side_face.index not in smart_side_face_indices:
                                if not is_collapsed:
                                    continue
                                smart_side_face_indices.add(side_face.index)
                            if not is_active_extrusion:
                                continue
                        elif not is_collapsed:
                            continue
                        elif not is_active_extrusion:
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

                uv_repaired = False
                if repair_uv:
                    resolved_uv_mode = (
                        _resolve_smart_uv_mode(
                            top_face, v_top_a, v_top_b, v_base_a, v_base_b
                        )
                        if uv_mode == "SMART"
                        else uv_mode
                    )

                    adjacent_uv_strip = (
                        _get_adjacent_face_uv_strip(
                            side_face,
                            v_base_a,
                            v_base_b,
                            selected_faces_set,
                            uv_layer,
                        )
                        if resolved_uv_mode == "OUTWARD"
                        else None
                    )
                    if adjacent_uv_strip:
                        # Outward extrusion: colour each side from the face
                        # immediately outside that boundary edge.
                        uv_base_a_val, uv_base_b_val, uv_dir = adjacent_uv_strip
                    else:
                        # Inward extrusion (and open boundaries without a
                        # neighbour) retains the selected face's existing
                        # behaviour and pixel-boundary alignment.
                        uv_base_a_val = uv_a.copy()
                        uv_base_b_val = uv_b.copy()

                        if p_step > 0:
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

                        uv_dir = (
                            -uv_outward_dir
                            if resolved_uv_mode == "INWARD"
                            else uv_outward_dir
                        )

                    uv_top_a_val = uv_base_a_val + uv_dir * h_uv
                    uv_top_b_val = uv_base_b_val + uv_dir * h_uv

                    expected_uvs = {
                        v_top_a: uv_top_a_val,
                        v_top_b: uv_top_b_val,
                        v_base_a: uv_base_a_val,
                        v_base_b: uv_base_b_val,
                    }
                    uv_repaired = any(
                        (l[uv_layer].uv - expected_uvs[l.vert]).length_squared > 1e-12
                        for l in side_face.loops
                    )
                    if uv_repaired:
                        for l in side_face.loops:
                            l[uv_layer].uv = expected_uvs[l.vert].copy()

                crease_repaired = False
                if add_crease:
                    # The cap can contain hard edges shared by two selected
                    # faces when an extrusion wraps around a model corner.
                    # Those edges are not part of any generated side face,
                    # so repairing only side-face edges misses them and
                    # subdivision rounds the corner.
                    crease_repaired = _repair_hard_edge_creases(
                        top_face.edges,
                        crease_layer,
                        crease_val,
                        sharp_angle_rad,
                    )
                    crease_repaired = _repair_hard_edge_creases(
                        side_face.edges,
                        crease_layer,
                        crease_val,
                        sharp_angle_rad,
                    ) or crease_repaired

                if uv_repaired or crease_repaired:
                    repaired_count += 1

    return repaired_count
