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






