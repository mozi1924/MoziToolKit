"""
Contextual UI hints for the material / reconstruction ownership boundary.

Kept in a small helper so the Voxel & Mesh panel and the custom MoziToolKit
menus explain disabled actions consistently.
"""

from __future__ import annotations

from typing import Any

from ..i18n import tr
from ..utils.mesh.ownership import (
    ORIGIN_EXTERNAL,
    ORIGIN_POINT_CLOUD,
    classify_origin,
)


def draw_mesh_origin_hint(layout: Any, context: Any, compact: bool = False) -> None:
    """
    Draw an ownership hint when the active object is MTK-generated.

    External meshes intentionally draw nothing: Replace Material is available
    and no explanation is needed.
    """
    obj = getattr(context, "active_object", None)
    if obj is None:
        return

    origin = classify_origin(obj)
    if origin == ORIGIN_EXTERNAL:
        return

    if origin == ORIGIN_POINT_CLOUD:
        if compact:
            layout.label(text=tr("Voxel Cloud — use Rebuild Voxel Mesh"), icon="INFO")
        else:
            layout.label(
                text=tr("Voxel Cloud: use Rebuild Voxel Mesh to regenerate the surface."),
                icon="INFO",
            )
        return

    if compact:
        layout.label(
            text=tr("MTK mesh — use Rebuild Voxel Mesh (edit the Voxel Cloud)"),
            icon="INFO",
        )
        return

    column = layout.column(align=True)
    try:
        column.alert = True
    except Exception:
        pass
    column.label(
        text=tr("MTK mesh: geometry is derived from the voxel source."),
        icon="INFO",
    )
    column.label(
        text=tr("Edit the Voxel Cloud, then Rebuild. Direct mesh edits will be overwritten."),
    )
    column.label(
        text=tr("Replace Material is only available for external imported meshes."),
    )


__all__ = ["draw_mesh_origin_hint"]
