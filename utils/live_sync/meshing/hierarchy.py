"""
Yefira Live Sync Container and Section Mesh Hierarchy Management.
Handles root Empty containers, 16x16x16 chunk section object resolution, naming propagation, and lifecycle.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
import bpy
import bmesh

from ..constants import DEFAULT_WORLD_OBJECT_NAME

logger = logging.getLogger("MoziToolKit.MeshHierarchy")


def get_section_object_name(root_prefix: str, sx: int, sy: int, sz: int) -> str:
    """Return canonical object name for a 16x16x16 section chunk under root object."""
    return f"{root_prefix}_Section_{sx}_{sy}_{sz}"


def get_section_mesh_name(root_prefix: str, sx: int, sy: int, sz: int) -> str:
    """Return canonical mesh name for a 16x16x16 section chunk under root object."""
    return f"Mesh_{root_prefix}_Section_{sx}_{sy}_{sz}"


def is_yefira_root_object(obj: Optional[bpy.types.Object]) -> bool:
    """Identify whether a Blender object is a root Yefira live sync world container."""
    if not obj:
        return False
    if obj.get("mtk:is_yefira_world"):
        if not obj.parent or not obj.parent.get("mtk:is_yefira_world"):
            return True
    if obj.name == DEFAULT_WORLD_OBJECT_NAME or obj.name.startswith("Yefira_World"):
        return True
    if obj.type == 'EMPTY' and any(c.get("mtk:section_pos") is not None or "_Section_" in c.name for c in obj.children):
        return True
    return False


def is_yefira_child_section(obj: Optional[bpy.types.Object]) -> bool:
    """Identify whether a Blender object is a child section mesh chunk of a Yefira world."""
    if not obj or obj.type != 'MESH':
        return False
    if obj.get("mtk:section_pos") is not None:
        return True
    if "_Section_" in obj.name or obj.name.startswith("Yefira_Section_"):
        return True
    return False


def is_yefira_object(obj: Optional[bpy.types.Object]) -> bool:
    """Identify whether a Blender object is either a root container or child section of Yefira."""
    if not obj:
        return False
    if obj.get("mtk:is_yefira_world") or obj.get("mtk:section_pos") is not None:
        return True
    if is_yefira_root_object(obj) or is_yefira_child_section(obj):
        return True
    if obj.parent and is_yefira_root_object(obj.parent):
        return True
    return False


def resolve_world_root_object(obj: Optional[bpy.types.Object]) -> Optional[bpy.types.Object]:
    """Given any object (root empty, child section mesh, or descendant), resolve to the topmost Yefira World root container."""
    if not obj:
        return None
    # 1. If object has a parent, climb up to find the root container
    curr = obj
    while curr.parent:
        if is_yefira_root_object(curr.parent):
            return curr.parent
        curr = curr.parent
    if is_yefira_root_object(curr):
        return curr
    # 2. If the object itself is a child section mesh without a linked parent yet
    if is_yefira_child_section(obj):
        prefix = obj.name.split("_Section_")[0]
        root_match = bpy.data.objects.get(prefix)
        if root_match and is_yefira_root_object(root_match):
            return root_match
    # 3. If the object is an Empty or tagged as world
    if is_yefira_root_object(obj):
        return obj
    return None


def get_or_create_world_root(
    context: Optional[bpy.types.Context] = None,
    root_name: Optional[str] = None,
    target_obj: Optional[bpy.types.Object] = None,
) -> bpy.types.Object:
    """
    Acquire or instantiate the root Empty container for Yefira Live Sync world geometry.
    Always resolves child section meshes to their parent world container.
    """
    if target_obj and getattr(target_obj, "name", None) in bpy.data.objects:
        resolved = resolve_world_root_object(target_obj)
        if resolved:
            return resolved
        if is_yefira_root_object(target_obj):
            return target_obj

    if root_name and root_name in bpy.data.objects:
        obj = bpy.data.objects[root_name]
        resolved = resolve_world_root_object(obj)
        if resolved:
            return resolved
        if is_yefira_root_object(obj):
            return obj

    ctx = context or (bpy.context if hasattr(bpy, "context") else None)
    active_obj = getattr(ctx, "active_object", None) if ctx else None
    if active_obj:
        resolved = resolve_world_root_object(active_obj)
        if resolved:
            return resolved

    target_name = root_name or DEFAULT_WORLD_OBJECT_NAME
    if target_name in bpy.data.objects:
        obj = bpy.data.objects[target_name]
        resolved = resolve_world_root_object(obj)
        if resolved:
            return resolved

    # Find any existing object tagged as Yefira world (prefer empty roots)
    for obj in bpy.data.objects:
        if is_yefira_root_object(obj):
            return obj

    # Create new Empty object container (no dummy mesh)
    root_obj = bpy.data.objects.new(target_name, None)
    root_obj.empty_display_type = 'PLAIN_AXES'
    root_obj.empty_display_size = 1.0
    root_obj["mtk:is_yefira_world"] = True
    root_obj["mtk:sync_manifest"] = "{}"
    root_obj["mtk:last_name"] = root_obj.name
    root_obj.location = (0.0, 0.0, 0.0)

    col = getattr(ctx, "collection", None) if ctx else None
    if col is None and hasattr(bpy.context, "scene") and hasattr(bpy.context.scene, "collection"):
        col = bpy.context.scene.collection
    if col:
        col.objects.link(root_obj)

    return root_obj


def find_root_section_children(root_obj: bpy.types.Object) -> dict[tuple[int, int, int], bpy.types.Object]:
    """Find and map all child section objects of root_obj by their section coordinates."""
    sections: dict[tuple[int, int, int], bpy.types.Object] = {}
    if not root_obj:
        return sections
    for child in root_obj.children:
        pos = child.get("mtk:section_pos")
        if pos is not None and len(pos) == 3:
            sections[(int(pos[0]), int(pos[1]), int(pos[2]))] = child
        elif "_Section_" in child.name:
            try:
                parts = child.name.split("_Section_")[-1].split("_")
                coords = (int(parts[0]), int(parts[1]), int(parts[2]))
                sections[coords] = child
                child["mtk:section_pos"] = list(coords)
            except Exception:
                pass
    return sections


def sync_child_section_names(root_obj: bpy.types.Object) -> None:
    """Propagate root object name prefix to all child section objects and meshes when root is renamed."""
    if not root_obj:
        return
    root_prefix = root_obj.name
    root_obj["mtk:last_name"] = root_prefix
    for child in list(root_obj.children):
        pos = child.get("mtk:section_pos")
        if pos is not None and len(pos) == 3:
            sx, sy, sz = int(pos[0]), int(pos[1]), int(pos[2])
        elif "_Section_" in child.name:
            try:
                parts = child.name.split("_Section_")[-1].split("_")
                sx, sy, sz = int(parts[0]), int(parts[1]), int(parts[2])
                child["mtk:section_pos"] = [sx, sy, sz]
            except Exception:
                continue
        else:
            continue

        target_obj_name = get_section_object_name(root_prefix, sx, sy, sz)
        target_mesh_name = get_section_mesh_name(root_prefix, sx, sy, sz)
        if child.name != target_obj_name:
            child.name = target_obj_name
        if child.data and child.data.name != target_mesh_name:
            child.data.name = target_mesh_name


def _is_valid_bpy_obj(obj: Any) -> bool:
    """Check if a Blender object reference is valid and still present in bpy.data.objects."""
    if obj is None:
        return False
    try:
        obj_name = obj.name
        return bool(obj_name in bpy.data.objects and bpy.data.objects.get(obj_name) == obj)
    except (ReferenceError, Exception):
        return False


def _safe_remove_section_object(obj: Optional[bpy.types.Object], mesh: Optional[bpy.types.Mesh] = None) -> None:
    """Safely remove a section object and its mesh datablock, handling Edit Mode if active."""
    if not obj:
        return
    try:
        if mesh is None:
            try:
                mesh = getattr(obj, "data", None)
            except (ReferenceError, Exception):
                mesh = None
        try:
            if getattr(obj, "mode", None) == 'EDIT':
                if hasattr(bpy.context, "view_layer") and getattr(bpy.context.view_layer.objects, "active", None) == obj:
                    try:
                        bpy.ops.object.mode_set(mode='OBJECT')
                    except Exception:
                        pass
        except (ReferenceError, Exception):
            pass
        try:
            obj_name = getattr(obj, "name", None)
            if obj_name and obj_name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        except (ReferenceError, Exception):
            pass
        try:
            if mesh:
                m_name = getattr(mesh, "name", None)
                if m_name and m_name in bpy.data.meshes:
                    bpy.data.meshes.remove(mesh, do_unlink=True)
        except (ReferenceError, Exception):
            pass
    except Exception as e:
        logger.debug(f"Safe remove section object error: {e}")


def prune_out_of_bounds_section_objects(root_obj: Optional[bpy.types.Object], storage: Any) -> int:
    """Remove any child section mesh objects of root_obj that fall outside the active selection storage bounds."""
    if not root_obj:
        return 0
    if not storage or getattr(storage, "size_x", 0) <= 0 or getattr(storage, "size_y", 0) <= 0 or getattr(storage, "size_z", 0) <= 0:
        return 0

    min_sec_x = storage.min_x >> 4
    max_sec_x = (storage.min_x + storage.size_x - 1) >> 4
    min_sec_y = storage.min_y >> 4
    max_sec_y = (storage.min_y + storage.size_y - 1) >> 4
    min_sec_z = storage.min_z >> 4
    max_sec_z = (storage.min_z + storage.size_z - 1) >> 4

    existing_sections = find_root_section_children(root_obj)
    removed_count = 0
    for coords, child in list(existing_sections.items()):
        sx, sy, sz = coords
        if not (min_sec_x <= sx <= max_sec_x and min_sec_y <= sy <= max_sec_y and min_sec_z <= sz <= max_sec_z):
            _safe_remove_section_object(child)
            existing_sections.pop(coords, None)
            removed_count += 1
    return removed_count


def clear_all_section_objects(root_obj: Optional[bpy.types.Object]) -> int:
    """Remove all child section mesh objects under root_obj."""
    if not root_obj:
        return 0
    existing_sections = find_root_section_children(root_obj)
    removed_count = 0
    for coords, child in list(existing_sections.items()):
        _safe_remove_section_object(child)
        removed_count += 1
    return removed_count


def _get_mesh_vertex_and_face_count(mesh: Optional[bpy.types.Mesh]) -> tuple[int, int]:
    """Return (vertex_count, face_count) correctly in either Object Mode or active Edit Mode."""
    if not mesh:
        return 0, 0
    if getattr(mesh, "is_editmode", False):
        try:
            bm = bmesh.from_edit_mesh(mesh)
            return len(bm.verts), len(bm.faces)
        except Exception:
            pass
    try:
        return len(mesh.vertices), len(mesh.polygons)
    except (ReferenceError, Exception):
        return 0, 0
