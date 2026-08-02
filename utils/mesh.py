import math
from contextlib import contextmanager
import bmesh
import bpy


SELECTION_ACTION_ITEMS = [
    ("SET", "Replace", "Replace current selection"),
    ("ADD", "Add", "Add to current selection"),
    ("SUBTRACT", "Subtract", "Remove from current selection"),
]

SELECTION_SCOPE_ITEMS = [
    ("ALL", "All Faces", "Process all faces in the mesh"),
    ("SELECTED", "Selected Only", "Process only currently selected faces"),
    ("LINKED", "Connected Mesh", "Process connected mesh faces of current selection"),
]

SELECT_MODES = {
    "VERT": (True, False, False),
    "EDGE": (False, True, False),
    "FACE": (False, False, True),
    "VERT_EDGE": (True, True, False),
    "EDGE_FACE": (False, True, True),
    "VERT_FACE": (True, False, True),
    "ALL": (True, True, True),
}


def poll_edit_mesh(context) -> bool:
    """Check if active object is a Mesh in Edit Mode."""
    obj = context.active_object
    return bool(obj and obj.type == "MESH" and context.mode == "EDIT_MESH")


def poll_mesh_object(context) -> bool:
    """Check if there is at least one Mesh object selected or active in Object or Edit Mode."""
    if not context:
        return False
    selected = context.selected_objects or ([context.active_object] if context.active_object else [])
    return any(obj and obj.type == "MESH" for obj in selected)


def set_select_mode(context, mode: str):
    """Set mesh selection mode ('VERT', 'EDGE', 'FACE', etc.)."""
    mode_upper = mode.upper()
    if mode_upper in SELECT_MODES:
        context.tool_settings.mesh_select_mode = SELECT_MODES[mode_upper]
    else:
        raise ValueError(f"Unknown select mode: {mode}. Must be one of {list(SELECT_MODES.keys())}")


@contextmanager
def bmesh_context(context, target_obj=None, auto_update: bool = True, flush_selection: bool = False):
    """Context manager for BMesh edit operations.

    Yields (target_object, bm).
    Automatically calls select_flush_mode() if flush_selection is True,
    and update_edit_mesh() if auto_update is True upon exit.
    """
    obj = target_obj or context.active_object
    me = obj.data
    bm = bmesh.from_edit_mesh(me)
    try:
        yield obj, bm
    finally:
        if flush_selection:
            bm.select_flush_mode()
        if auto_update:
            bmesh.update_edit_mesh(me)



def apply_selection(elements, target_elements, action: str = "SET"):
    """Apply selection action ('SET', 'ADD', 'SUBTRACT') to BMesh elements.

    :param elements: Iterable of BMesh elements (verts, edges, or faces).
    :param target_elements: Iterable or set of BMesh elements to target.
    :param action: 'SET', 'ADD', or 'SUBTRACT'.
    """
    target_set = set(target_elements) if not isinstance(target_elements, set) else target_elements

    if action == "SET":
        for elem in elements:
            elem.select = elem in target_set
    elif action == "ADD":
        for elem in target_set:
            elem.select = True
    elif action == "SUBTRACT":
        for elem in target_set:
            elem.select = False
    else:
        raise ValueError(f"Invalid selection action: {action}. Expected 'SET', 'ADD', or 'SUBTRACT'.")


def get_connected_faces(bm, seed_faces):
    """Find all connected faces (linked mesh island) starting from seed_faces."""
    visited = set()
    stack = list(seed_faces)
    while stack:
        face = stack.pop()
        if face in visited or not face.is_valid:
            continue
        visited.add(face)
        for edge in face.edges:
            for linked_face in edge.link_faces:
                if linked_face not in visited:
                    stack.append(linked_face)
    return visited


def get_target_faces(bm, scope: str = "ALL"):
    """Get faces from BMesh according to selection scope ('ALL', 'SELECTED', or 'LINKED')."""
    if scope == "SELECTED":
        selected = [f for f in bm.faces if f.select and f.is_valid]
        if selected:
            return selected
        return [f for f in bm.faces if f.is_valid]
    elif scope == "LINKED":
        selected = [f for f in bm.faces if f.select and f.is_valid]
        if selected:
            return list(get_connected_faces(bm, selected))
        return [f for f in bm.faces if f.is_valid]
    else:  # "ALL"
        return [f for f in bm.faces if f.is_valid]


import mathutils


def calculate_face_uv_area(face, uv_layer) -> float:
    """Calculate 2D signed area of a face in UV space using Shoelace formula."""
    loops = face.loops
    if len(loops) < 3:
        return 0.0
    area = 0.0
    n = len(loops)
    for i in range(n):
        uv1 = loops[i][uv_layer].uv
        uv2 = loops[(i + 1) % n][uv_layer].uv
        area += (uv1.x * uv2.y - uv2.x * uv1.y)
    return 0.5 * abs(area)


def is_face_uv_collapsed(face, uv_layer, area_threshold: float = 1e-6, dist_threshold: float = 1e-4) -> bool:
    """Check if face UVs are collapsed to a point, line segment, or near zero 2D area."""
    if len(face.loops) < 3:
        return True
    if calculate_face_uv_area(face, uv_layer) < area_threshold:
        return True
    uvs = [l[uv_layer].uv for l in face.loops]
    max_dist_sq = 0.0
    for i in range(len(uvs)):
        for j in range(i + 1, len(uvs)):
            dist_sq = (uvs[i] - uvs[j]).length_squared
            if dist_sq > max_dist_sq:
                max_dist_sq = dist_sq
    return max_dist_sq < (dist_threshold * dist_threshold)


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

    p_step = 1.0 / 64.0
    try:
        active_obj = bpy.context.active_object
        if active_obj and active_obj.active_material and active_obj.active_material.use_nodes:
            for node in active_obj.active_material.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image and node.image.size[0] > 0:
                    p_step = 1.0 / float(node.image.size[0])
                    break
    except Exception:
        pass

    selected_faces = [f for f in bm.faces if f.select and f.is_valid]
    if not selected_faces:
        return 0


    selected_faces_set = set(selected_faces)
    repaired_count = 0

    for top_face in selected_faces:
        ref_uv_center = mathutils.Vector((0.0, 0.0))
        for l in top_face.loops:
            ref_uv_center += l[uv_layer].uv
        ref_uv_center /= len(top_face.loops)

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

                if add_crease:
                    for se in side_face.edges:
                        se[crease_layer] = crease_val

                if repair_uv:
                    uv_a = ref_vert_uv[v_top_a]
                    uv_b = ref_vert_uv[v_top_b]

                    l_3d = (v_top_b.co - v_top_a.co).length
                    u_edge = uv_b - uv_a
                    l_uv = u_edge.length

                    h_3d = (v_base_a.co - v_top_a.co).length
                    ratio = (h_3d / l_3d) if l_3d > 1e-6 else 1.0
                    h_uv = l_uv * ratio

                    if uv_mode == "INWARD":
                        edge_uv_mid = (uv_a + uv_b) * 0.5
                        uv_outward_dir = edge_uv_mid - ref_uv_center
                        if uv_outward_dir.length > 1e-6:
                            uv_outward_dir.normalize()
                        else:
                            uv_outward_dir = mathutils.Vector((1.0, 0.0))

                        h_uv = min(h_uv, l_uv)
                        uv_dir = -uv_outward_dir
                        uv_base_a_val = uv_a.copy()
                        uv_base_b_val = uv_b.copy()
                        uv_top_a_val = uv_a + uv_dir * h_uv
                        uv_top_b_val = uv_b + uv_dir * h_uv
                    else:
                        edge_uv_mid = (uv_a + uv_b) * 0.5
                        uv_outward_dir = edge_uv_mid - ref_uv_center
                        if uv_outward_dir.length > 1e-6:
                            if abs(uv_outward_dir.x) > abs(uv_outward_dir.y):
                                uv_outward_dir = mathutils.Vector((1.0 if uv_outward_dir.x > 0 else -1.0, 0.0))
                            else:
                                uv_outward_dir = mathutils.Vector((0.0, 1.0 if uv_outward_dir.y > 0 else -1.0))
                        else:
                            uv_outward_dir = mathutils.Vector((1.0, 0.0))

                        # Mirror across pixel grid border line into adjacent pixel (keeps UV adjacent to original face)
                        def mirror_across_pixel_border(uv_pt):
                            res = uv_pt.copy()
                            if uv_outward_dir.x > 0:
                                border = math.ceil(uv_pt.x / p_step) * p_step
                                res.x = border + (border - uv_pt.x)
                            elif uv_outward_dir.x < 0:
                                border = math.floor(uv_pt.x / p_step) * p_step
                                res.x = border - (uv_pt.x - border)
                            elif uv_outward_dir.y > 0:
                                border = math.ceil(uv_pt.y / p_step) * p_step
                                res.y = border + (border - uv_pt.y)
                            elif uv_outward_dir.y < 0:
                                border = math.floor(uv_pt.y / p_step) * p_step
                                res.y = border - (uv_pt.y - border)
                            return res

                        uv_base_a_val = mirror_across_pixel_border(uv_a)
                        uv_base_b_val = mirror_across_pixel_border(uv_b)
                        uv_top_a_val = uv_base_a_val + uv_outward_dir * h_uv
                        uv_top_b_val = uv_base_b_val + uv_outward_dir * h_uv



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





