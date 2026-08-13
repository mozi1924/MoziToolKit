"""Shared coordinate rules for the baked-UV and shader atlas paths."""

from __future__ import annotations

FACE_ORDER = ("+X", "-X", "+Y", "-Y", "+Z", "-Z")


def face_index_from_normal(normal) -> int:
    """Return the atlas face index for a Blender object-space face normal.

    Minecraft's vertical Y axis corresponds to Blender Z.  The fallback is
    +X, matching the shader node group and making the result deterministic for
    degenerate/smoothed faces.
    """
    if normal.x < -0.5:
        return 1
    if normal.z > 0.5:
        return 2
    if normal.z < -0.5:
        return 3
    if normal.y > 0.5:
        return 4
    if normal.y < -0.5:
        return 5
    return 0


def static_cell(material_id: int, face_index: int, material_columns: int) -> tuple[int, int]:
    """Return the atlas tile column and top-origin row for a static face."""
    material_columns = max(1, int(material_columns))
    material_id = max(0, int(material_id))
    return ((material_id % material_columns) * 6 + int(face_index),
            material_id // material_columns)


def atlas_uv_from_local(
    u: float,
    v: float,
    *,
    tile_column: int,
    tile_row: int,
    tile_size: float,
    atlas_width: float,
    atlas_height: float,
) -> tuple[float, float]:
    """Map a source texture UV directly into one top-origin atlas cell.

    This deliberately does not apply ``fract``: a quad's 0..1 UV span must
    remain continuous after it is written back to the mesh.  The shader path
    uses ``fract`` separately so procedural UVs can repeat inside one cell.
    """
    return (
        (tile_column + u) * tile_size / atlas_width,
        1.0 - (tile_row + 1.0 - v) * tile_size / atlas_height,
    )
