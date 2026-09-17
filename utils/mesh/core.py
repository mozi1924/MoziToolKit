"""
Mesh manipulation helpers, selection scopes, bmesh context managers, and edge geometry tools.
"""

from __future__ import annotations

import math
from contextlib import contextmanager

try:
    import bmesh
    import bpy
except ImportError:
    bmesh = None
    bpy = None


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
    if not context:
        return False
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
    Supports both Edit mode (bmesh.from_edit_mesh) and Object mode (bmesh.new / from_mesh / to_mesh).
    Automatically calls select_flush_mode() if flush_selection is True,
    and updates mesh upon exit.
    """
    obj = target_obj or context.active_object
    me = obj.data
    is_edit_mode = (obj.mode == "EDIT")
    if is_edit_mode:
        bm = bmesh.from_edit_mesh(me)
    else:
        bm = bmesh.new()
        bm.from_mesh(me)

    try:
        yield obj, bm
    finally:
        if is_edit_mode:
            if flush_selection:
                bm.select_flush_mode()
            if auto_update:
                bmesh.update_edit_mesh(me)
        else:
            if auto_update:
                bm.to_mesh(me)
                me.update()
            bm.free()


def apply_selection(elements, target_elements, action: str = "SET"):
    """Apply selection action ('SET', 'ADD', 'SUBTRACT') to BMesh elements."""
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


def is_hard_edge(edge, sharp_angle_rad: float = math.radians(30.0)) -> bool:
    """Check if a BMesh edge is considered a hard/sharp edge.

    True if:
    - It is a boundary / open boundary edge (<= 1 link face)
    - It is explicitly marked sharp or not smooth
    - The dihedral angle between its 2 adjacent faces exceeds sharp_angle_rad
    """
    if edge.is_boundary or not edge.smooth or edge.seam:
        return True
    if len(edge.link_faces) == 2:
        try:
            if edge.calc_face_angle(0) > sharp_angle_rad:
                return True
        except Exception:
            pass
    return False
