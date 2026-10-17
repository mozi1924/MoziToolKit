"""
Mesh origin classification and voxel-source discovery.

This module is the single source of truth for the material / reconstruction
boundary:

* ``EXTERNAL`` meshes are user or third-party imports. They are the only valid
  targets for **Replace Material**.
* Every surface mesh created by MoziToolKit is stamped with
  ``mtk:geometry_origin`` at creation time. Its geometry and materials are
  derived from a voxel source and must be regenerated with **Rebuild Mesh**.

Classification deliberately ignores material provenance attributes such as
``mtk_source_texture_key``. Replace Material writes those onto external meshes
too, so using them for ownership would be circular (an external mesh would
become "MTK-generated" after its first replacement).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("MoziToolKit.Mesh.Ownership")

#: Object custom property storing the construction origin.
ORIGIN_PROP = "mtk:geometry_origin"

ORIGIN_EXTERNAL = "EXTERNAL"
ORIGIN_SAVE = "SAVE"
ORIGIN_SYNC_WORLD = "SYNC_WORLD"
ORIGIN_SYNC_SECTION = "SYNC_SECTION"
ORIGIN_VOXEL = "VOXEL"
ORIGIN_POINT_CLOUD = "POINT_CLOUD"

ALL_ORIGINS = frozenset(
    {
        ORIGIN_EXTERNAL,
        ORIGIN_SAVE,
        ORIGIN_SYNC_WORLD,
        ORIGIN_SYNC_SECTION,
        ORIGIN_VOXEL,
        ORIGIN_POINT_CLOUD,
    }
)

# ---------------------------------------------------------------------------
# Blender object helpers (kept dependency-free so this module is importable in
# headless test environments).
# ---------------------------------------------------------------------------


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


def _safe_set(obj: Any, key: str, value: Any) -> None:
    if obj is None:
        return
    try:
        obj[key] = value
        return
    except Exception:
        pass
    try:
        setattr(obj, key, value)
    except Exception:
        pass


def _as_bool(value: Any) -> bool:
    """Coerce Blender custom properties to bool without trusting Mock objects."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _object_type(obj: Any) -> str:
    value = getattr(obj, "type", "")
    return value if isinstance(value, str) else ""


def _object_name(obj: Any) -> str:
    value = getattr(obj, "name", "")
    return value if isinstance(value, str) else ""


def _children(obj: Any) -> list:
    try:
        children = getattr(obj, "children", None)
        return list(children) if children else []
    except Exception:
        return []


def _bpy_objects() -> Any:
    try:
        import bpy  # local import: keep this module importable outside Blender
    except ImportError:
        return None
    try:
        return bpy.data.objects
    except Exception:
        return None


def _lookup_mesh(name: Any) -> Optional[Any]:
    if not isinstance(name, str) or not name:
        return None
    objects = _bpy_objects()
    if objects is None:
        return None
    try:
        candidate = objects.get(name)
    except Exception:
        return None
    if candidate is None or _object_type(candidate) != "MESH":
        return None
    return candidate


# ---------------------------------------------------------------------------
# Origin classification
# ---------------------------------------------------------------------------


def is_point_cloud(obj: Any) -> bool:
    """Return True when *obj* is a MoziToolKit voxel point-cloud mesh."""
    if obj is None or _object_type(obj) != "MESH":
        return False
    if _as_bool(_safe_get(obj, "mtk_is_voxel_cloud")):
        return True
    return _object_name(obj).endswith("_VoxelCloud")


def stamp_geometry_origin(obj: Any, origin: str, overwrite: bool = False) -> None:
    """
    Write the construction origin onto *obj*.

    Call this at mesh creation time only. Replace/Rebuild must never change it;
    only an explicit "detach to external" action should overwrite it.
    """
    if obj is None:
        return
    if origin not in ALL_ORIGINS:
        logger.warning("Ignoring unknown mesh origin %r for %r", origin, _object_name(obj))
        return

    if not overwrite:
        existing = _safe_get(obj, ORIGIN_PROP)
        if isinstance(existing, str) and existing in ALL_ORIGINS:
            return

    _safe_set(obj, ORIGIN_PROP, origin)


def classify_origin(obj: Any) -> str:
    """
    Classify an object as ``EXTERNAL`` or one of the MoziToolKit origins.

    Resolution order:

    1. explicit ``mtk:geometry_origin`` (authoritative)
    2. point-cloud marker
    3. legacy creation markers (``mtk:is_save_mesh`` etc.)
    4. container type (when an Empty root is active)
    5. naming conventions (legacy files created before origin stamping)

    Material provenance attributes are intentionally never consulted.
    """
    if obj is None:
        return ORIGIN_EXTERNAL

    explicit = _safe_get(obj, ORIGIN_PROP)
    if isinstance(explicit, str) and explicit in ALL_ORIGINS:
        return explicit

    if is_point_cloud(obj):
        return ORIGIN_POINT_CLOUD

    obj_type = _object_type(obj)
    name = _object_name(obj)

    if _as_bool(_safe_get(obj, "mtk:is_save_mesh")):
        return ORIGIN_SAVE
    save_uuid = _safe_get(obj, "mozi_save_uuid")
    if isinstance(save_uuid, str) and save_uuid:
        return ORIGIN_SAVE

    if _as_bool(_safe_get(obj, "mtk:is_section_mesh")):
        return ORIGIN_SYNC_SECTION

    if _as_bool(_safe_get(obj, "mtk:is_yefira_mesh")) or _as_bool(_safe_get(obj, "mtk:is_yefira_world")):
        return ORIGIN_SYNC_WORLD

    if obj_type == "EMPTY":
        container_type = _safe_get(obj, "mtk:container_type")
        if isinstance(container_type, str):
            if container_type.strip().upper() == "SAVE":
                return ORIGIN_SAVE
            if container_type.strip().upper() == "SYNC":
                return ORIGIN_SYNC_WORLD
        if _as_bool(_safe_get(obj, "mtk:is_container")) and _as_bool(_safe_get(obj, "mtk:is_yefira_world")):
            return ORIGIN_SYNC_WORLD

    # Naming fallbacks for legacy files created before explicit origin stamping.
    if obj_type == "MESH":
        if name.startswith("Save_") and name.endswith("_Mesh"):
            return ORIGIN_SAVE
        if name.startswith("Yefira_World"):
            return ORIGIN_SYNC_WORLD
        if name.startswith("MTK_World"):
            return ORIGIN_VOXEL
    elif obj_type == "EMPTY":
        if name.startswith("Save_"):
            return ORIGIN_SAVE
        if name.startswith("Yefira_World"):
            return ORIGIN_SYNC_WORLD

    return ORIGIN_EXTERNAL


def is_external_mesh(obj: Any) -> bool:
    """True only for external imported surface meshes (Replace Material target)."""
    return (
        obj is not None
        and _object_type(obj) == "MESH"
        and not is_point_cloud(obj)
        and classify_origin(obj) == ORIGIN_EXTERNAL
    )


# ---------------------------------------------------------------------------
# Voxel source discovery
# ---------------------------------------------------------------------------


def find_voxel_cloud(obj: Any) -> Optional[Any]:
    """
    Locate the companion voxel point cloud for *obj*.

    Checks the explicit ``mtk_voxel_cloud`` association first, then naming
    conventions, then parent/child hierarchy. Returns the cloud object or None.
    """
    if obj is None:
        return None

    if is_point_cloud(obj):
        return obj

    obj_name = _object_name(obj)

    # 1. Explicit association written by Save / Live Sync pipelines.
    candidate = _lookup_mesh(_safe_get(obj, "mtk_voxel_cloud"))
    if candidate is not None:
        return candidate

    # 2. Sibling naming convention.
    sibling_names = [f"{obj_name}_VoxelCloud"]
    if obj_name.endswith("_Mesh"):
        sibling_names.append(f"{obj_name[:-5]}_VoxelCloud")
    for sibling_name in sibling_names:
        candidate = _lookup_mesh(sibling_name)
        if candidate is not None:
            return candidate

    # 3. Parent association and sibling children.
    parent = getattr(obj, "parent", None)
    if parent is not None:
        candidate = _lookup_mesh(_safe_get(parent, "mtk_voxel_cloud"))
        if candidate is not None:
            return candidate
        for child in _children(parent):
            if is_point_cloud(child):
                return child

    # 4. Children of the object itself (root Empty or world mesh parent).
    for child in _children(obj):
        if is_point_cloud(child):
            return child

    return None


def has_voxel_source(obj: Any) -> bool:
    """True when a persistent companion voxel point cloud can be resolved."""
    return find_voxel_cloud(obj) is not None


__all__ = [
    "ORIGIN_PROP",
    "ORIGIN_EXTERNAL",
    "ORIGIN_SAVE",
    "ORIGIN_SYNC_WORLD",
    "ORIGIN_SYNC_SECTION",
    "ORIGIN_VOXEL",
    "ORIGIN_POINT_CLOUD",
    "ALL_ORIGINS",
    "is_point_cloud",
    "stamp_geometry_origin",
    "classify_origin",
    "is_external_mesh",
    "find_voxel_cloud",
    "has_voxel_source",
]
