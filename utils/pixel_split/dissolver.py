import bmesh
from typing import List, Set, Dict


def find_coplanar_face_groups(bm, faces: List[bmesh.types.BMFace], normal_threshold: float = 0.999) -> List[List[bmesh.types.BMFace]]:
    """Group connected faces that share the same normal orientation and material index."""
    face_set = set(faces)
    visited: Set[bmesh.types.BMFace] = set()
    groups: List[List[bmesh.types.BMFace]] = []

    for start_face in faces:
        if start_face in visited:
            continue

        # Start flood fill for coplanar group
        group = []
        queue = [start_face]
        visited.add(start_face)

        norm = start_face.normal.copy()
        mat_idx = start_face.material_index

        while queue:
            curr = queue.pop(0)
            group.append(curr)

            # Check neighbors across edges
            for edge in curr.edges:
                for nbr in edge.link_faces:
                    if nbr in face_set and nbr not in visited:
                        if nbr.material_index == mat_idx and curr.normal.dot(nbr.normal) >= normal_threshold:
                            visited.add(nbr)
                            queue.append(nbr)

        groups.append(group)

    return groups


def dissolve_pre_split_edges(bm, faces: List[bmesh.types.BMFace]) -> List[bmesh.types.BMFace]:
    """Dissolve internal edges of coplanar face groups to recover base quad faces.

    Returns the list of remaining/merged faces after dissolve.
    """
    groups = find_coplanar_face_groups(bm, faces)
    edges_to_dissolve: Set[bmesh.types.BMEdge] = set()

    for group in groups:
        group_set = set(group)
        for face in group:
            for edge in face.edges:
                # An edge is internal if ALL linked faces belong to the same group
                if all(linked in group_set for linked in edge.link_faces) and len(edge.link_faces) > 1:
                    edges_to_dissolve.add(edge)

    if edges_to_dissolve:
        # Dissolve edges and clean up unused vertices
        bmesh.ops.dissolve_edges(bm, edges=list(edges_to_dissolve), use_verts=True, use_face_split=False)

        # Dissolve 2-valence collinear vertices along boundaries
        collinear_verts = []
        for v in bm.verts:
            if v.is_valid and len(v.link_edges) == 2:
                e1, e2 = v.link_edges
                v1 = e1.other_vert(v)
                v2 = e2.other_vert(v)
                dir1 = (v1.co - v.co).normalized()
                dir2 = (v2.co - v.co).normalized()
                if dir1.dot(dir2) <= -0.999:
                    collinear_verts.append(v)

        if collinear_verts:
            bmesh.ops.dissolve_verts(bm, verts=collinear_verts, use_face_split=False)

        bm.faces.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()


    # Return valid remaining faces from original selection area
    return [f for f in bm.faces if f.is_valid]
