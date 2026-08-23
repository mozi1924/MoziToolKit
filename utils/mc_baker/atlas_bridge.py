"""
Atlas Bridge for connecting BakedModel results to MoziToolKit Atlas Materials.
Maps standard texture resource identifiers to Atlas tiles, material IDs, and shader attributes.
"""

from __future__ import annotations
from typing import Any, Optional, NamedTuple
from .types import BakedModel, BakedFace


class ResolvedAtlasFace(NamedTuple):
    direction: str
    texture: str
    material_id: int
    tile_col: int
    tile_row: int
    uv_rot: float
    uv_bounds: tuple[float, float, float, float]
    tint_index: int


class AtlasBridge:
    def __init__(self, atlas_mapping: Optional[dict[str, Any]] = None):
        self.atlas_mapping = atlas_mapping or {}

    def set_mapping(self, atlas_mapping: dict[str, Any]):
        self.atlas_mapping = atlas_mapping

    def resolve_face(self, face: BakedFace) -> ResolvedAtlasFace:
        """
        Map a single BakedFace to MoziToolKit Atlas tile coordinates and material ID.
        """
        tex_name = face.texture
        short_name = tex_name.split(":", 1)[-1].removeprefix("block/")

        textures_map = self.atlas_mapping.get("textures", {})
        tile_info = None

        # Look up in textures mapping with fallback aliases
        for candidate in (tex_name, short_name, f"minecraft:{short_name}", f"minecraft:block/{short_name}"):
            if candidate in textures_map:
                tile_info = textures_map[candidate]
                break

        if isinstance(tile_info, dict):
            tile_col = int(tile_info.get("col", 0))
            tile_row = int(tile_info.get("row", 0))
            mat_id = int(tile_info.get("material_id", 0))
        elif isinstance(tile_info, (list, tuple)) and len(tile_info) >= 2:
            tile_col = int(tile_info[0])
            tile_row = int(tile_info[1])
            mat_id = int(tile_info[2]) if len(tile_info) > 2 else 0
        else:
            tile_col, tile_row, mat_id = 0, 0, 0

        return ResolvedAtlasFace(
            direction=face.direction,
            texture=face.texture,
            material_id=mat_id,
            tile_col=tile_col,
            tile_row=tile_row,
            uv_rot=face.uv_rot,
            uv_bounds=face.uv_bounds,
            tint_index=face.tint_index,
        )

    def resolve_model_faces(self, baked_model: BakedModel) -> list[ResolvedAtlasFace]:
        """
        Resolve all 6 standard faces of a BakedModel to Atlas properties.
        Returns list of 6 ResolvedAtlasFace objects (East, West, Up, Down, South, North).
        """
        return [self.resolve_face(face) for face in baked_model.faces]
