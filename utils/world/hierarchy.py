"""
MoziToolKit Unified Hierarchy and Context Resolution Subsystem (SSOT).

Authoritative single source of truth for identifying and resolving MTK object hierarchies:
  Root Container (Empty: SYNC | SAVE | SCENE)
  ├── Primary / Child Meshes (Surface Mesh)
  └── Companion Point Cloud (Voxel Storage Mesh)

Provides unified resolution regardless of whether the user selects:
- The Empty Root Container
- A Child Surface Mesh
- The Companion Voxel Point Cloud
- A Standalone MTK Mesh
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Iterable, List, Optional, Tuple

import bpy

from ..mesh.ownership import (
    ORIGIN_EXTERNAL,
    ORIGIN_POINT_CLOUD,
    ORIGIN_SAVE,
    ORIGIN_SCENE,
    ORIGIN_SYNC_SECTION,
    ORIGIN_SYNC_WORLD,
    ORIGIN_VOXEL,
    classify_origin,
    find_voxel_cloud,
    is_point_cloud,
)

logger = logging.getLogger("MoziToolKit.World.Hierarchy")

KNOWN_CONTAINER_TYPES = frozenset({"SYNC", "SAVE", "SCENE"})


def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    try:
        getter = getattr(obj, "get", None)
        if callable(getter):
            return getter(key, default)
    except Exception:
        pass
    try:
        return getattr(obj, key, default)
    except Exception:
        return default


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def is_mtk_container(obj: Optional[Any]) -> bool:
    """Return True if the object is an MTK root container (Empty)."""
    if obj is None:
        return False
    if getattr(obj, "type", "") != "EMPTY":
        return False

    if _as_bool(_safe_get(obj, "mtk:is_container")):
        return True

    c_type = _safe_get(obj, "mtk:container_type")
    if isinstance(c_type, str) and c_type.strip().upper() in KNOWN_CONTAINER_TYPES:
        return True

    if _as_bool(_safe_get(obj, "mtk:is_yefira_world")):
        return True
    if _as_bool(_safe_get(obj, "mtk:is_scene_container")):
        return True
    if _as_bool(_safe_get(obj, "mtk:is_save_world")):
        return True
    if _safe_get(obj, "mozi_save_uuid") or _safe_get(obj, "mozi_scene_uuid"):
        return True

    name = getattr(obj, "name", "")
    if name.startswith(("Yefira_World", "Save_", "[Scene]")):
        return True

    # Check if any child is an MTK mesh
    for child in getattr(obj, "children", []):
        if is_point_cloud(child) or classify_origin(child) != ORIGIN_EXTERNAL:
            return True

    return False


def get_container_type(obj: Optional[Any]) -> Optional[str]:
    """Return the container type ('SYNC', 'SAVE', 'SCENE') or None."""
    if obj is None:
        return None
    raw_type = _safe_get(obj, "mtk:container_type")
    if isinstance(raw_type, str):
        c_type = raw_type.strip().upper()
        if c_type in KNOWN_CONTAINER_TYPES:
            return c_type

    if _as_bool(_safe_get(obj, "mtk:is_yefira_world")):
        return "SYNC"
    if _as_bool(_safe_get(obj, "mtk:is_scene_container")):
        return "SCENE"
    if _as_bool(_safe_get(obj, "mtk:is_save_world")) or _safe_get(obj, "mozi_save_uuid"):
        return "SAVE"

    name = getattr(obj, "name", "")
    if name.startswith("Yefira_World"):
        return "SYNC"
    if name.startswith("Save_"):
        return "SAVE"
    if name.startswith("[Scene]"):
        return "SCENE"

    return None


@dataclass
class HierarchyContext:
    """Canonical representation of an active MoziToolKit hierarchy."""

    root: Optional[bpy.types.Object] = None
    primary_mesh: Optional[bpy.types.Object] = None
    child_meshes: List[bpy.types.Object] = field(default_factory=list)
    point_cloud: Optional[bpy.types.Object] = None
    container_type: Optional[str] = None
    origin: str = ORIGIN_EXTERNAL
    is_container: bool = False
    is_mtk: bool = False

    @property
    def has_voxel_data(self) -> bool:
        """True if either a point cloud or in-memory session is active."""
        return self.point_cloud is not None or self.container_type == "SYNC"


def resolve_hierarchy(target: Optional[Any]) -> HierarchyContext:
    """
    Resolve the unified HierarchyContext for a given Context, Object, or selection.

    This is the Single Source of Truth across all MoziToolKit UI panels,
    context menus, and operators.
    """
    if target is None:
        return HierarchyContext()

    # 1. Context extraction
    if hasattr(target, "active_object") or hasattr(target, "selected_objects"):
        obj = getattr(target, "active_object", None)
        if obj is None:
            obj = getattr(target, "object", None)
        if obj is None:
            sel = getattr(target, "selected_objects", [])
            obj = sel[0] if sel else None
    else:
        obj = target

    if obj is None:
        return HierarchyContext()

    obj_type = getattr(obj, "type", "")

    # 2. Case A: Active object is an Empty Root Container
    if obj_type == "EMPTY" and is_mtk_container(obj):
        c_type = get_container_type(obj)
        root = obj
        child_meshes: List[bpy.types.Object] = []
        point_cloud: Optional[bpy.types.Object] = None

        for ch in getattr(root, "children", []):
            if getattr(ch, "type", "") == "MESH":
                if is_point_cloud(ch):
                    if point_cloud is None:
                        point_cloud = ch
                else:
                    child_meshes.append(ch)

        # Fallback sibling lookups if children are temporarily unparented
        if not child_meshes and hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
            for cand_name in (f"{root.name}_Mesh", f"{root.name} Mesh", root.name):
                cand = bpy.data.objects.get(cand_name)
                if cand and getattr(cand, "type", "") == "MESH" and not is_point_cloud(cand):
                    child_meshes.append(cand)
                    break

        if point_cloud is None:
            point_cloud = find_voxel_cloud(root)

        primary_mesh = child_meshes[0] if child_meshes else None
        origin = classify_origin(root)
        if origin == ORIGIN_EXTERNAL and primary_mesh is not None:
            origin = classify_origin(primary_mesh)
        if origin == ORIGIN_EXTERNAL and c_type:
            origin = (
                ORIGIN_SYNC_WORLD if c_type == "SYNC"
                else (ORIGIN_SAVE if c_type == "SAVE" else ORIGIN_SCENE)
            )

        return HierarchyContext(
            root=root,
            primary_mesh=primary_mesh,
            child_meshes=child_meshes,
            point_cloud=point_cloud,
            container_type=c_type,
            origin=origin,
            is_container=True,
            is_mtk=True,
        )

    # 3. Case B: Active object is a Companion Voxel Point Cloud
    if is_point_cloud(obj):
        point_cloud = obj
        root = getattr(obj, "parent", None)
        if root is not None and not is_mtk_container(root):
            root = None

        primary_mesh = None
        child_meshes: List[bpy.types.Object] = []

        if root is not None:
            for ch in getattr(root, "children", []):
                if getattr(ch, "type", "") == "MESH" and not is_point_cloud(ch):
                    child_meshes.append(ch)
            if child_meshes:
                primary_mesh = child_meshes[0]
        else:
            w_name = _safe_get(obj, "mtk_world_mesh")
            if w_name and hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
                primary_mesh = bpy.data.objects.get(w_name)
            if primary_mesh is None and obj.name.endswith("_VoxelCloud"):
                base = obj.name[:-11]
                for cand_name in (f"{base}_Mesh", base):
                    cand = bpy.data.objects.get(cand_name)
                    if cand and getattr(cand, "type", "") == "MESH":
                        primary_mesh = cand
                        break
            if primary_mesh:
                child_meshes = [primary_mesh]

        c_type = get_container_type(root) if root else None
        origin = ORIGIN_POINT_CLOUD

        return HierarchyContext(
            root=root,
            primary_mesh=primary_mesh,
            child_meshes=child_meshes,
            point_cloud=point_cloud,
            container_type=c_type,
            origin=origin,
            is_container=False,
            is_mtk=True,
        )

    # 4. Case C: Active object is a Surface Mesh
    if obj_type == "MESH":
        parent = getattr(obj, "parent", None)
        root = parent if is_mtk_container(parent) else None

        child_meshes: List[bpy.types.Object] = []
        point_cloud = find_voxel_cloud(obj)

        if root is not None:
            for ch in getattr(root, "children", []):
                if getattr(ch, "type", "") == "MESH" and not is_point_cloud(ch):
                    child_meshes.append(ch)
            if point_cloud is None:
                point_cloud = find_voxel_cloud(root)
        else:
            child_meshes = [obj]

        primary_mesh = obj
        c_type = get_container_type(root) if root else None
        origin = classify_origin(obj)
        if origin == ORIGIN_EXTERNAL and c_type:
            origin = (
                ORIGIN_SYNC_WORLD if c_type == "SYNC"
                else (ORIGIN_SAVE if c_type == "SAVE" else ORIGIN_SCENE)
            )

        is_mtk = (
            origin != ORIGIN_EXTERNAL
            or root is not None
            or point_cloud is not None
            or _safe_get(obj, "mtk:biome_preset") is not None
            or _safe_get(obj, "mtk:provenance_schema_version") is not None
        )

        return HierarchyContext(
            root=root,
            primary_mesh=primary_mesh,
            child_meshes=child_meshes,
            point_cloud=point_cloud,
            container_type=c_type,
            origin=origin,
            is_container=False,
            is_mtk=is_mtk,
        )

    # 5. Fallback for other objects (Curves, Cameras, unassociated Empties)
    return HierarchyContext(
        root=None,
        primary_mesh=None,
        child_meshes=[],
        point_cloud=None,
        container_type=None,
        origin=ORIGIN_EXTERNAL,
        is_container=False,
        is_mtk=False,
    )


def resolve_target_meshes(targets: Iterable[Any]) -> List[bpy.types.Object]:
    """
    Given a list or collection of selected objects, resolves and expands any MTK
    containers to their underlying surface meshes, deduplicating the result.
    """
    seen = set()
    result: List[bpy.types.Object] = []

    for obj in targets:
        if obj is None:
            continue
        ctx = resolve_hierarchy(obj)
        if ctx.child_meshes:
            for m in ctx.child_meshes:
                if m and m.name not in seen:
                    seen.add(m.name)
                    result.append(m)
        elif getattr(obj, "type", "") == "MESH" and not is_point_cloud(obj):
            if obj.name not in seen:
                seen.add(obj.name)
                result.append(obj)

    return result
