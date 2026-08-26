"""
Atlas Bridge for connecting BakedModel results to MoziToolKit Atlas Materials.
Maps standard texture resource identifiers to Atlas tiles, material IDs, and shader attributes.
"""

from __future__ import annotations
from typing import Any, Optional, NamedTuple, TYPE_CHECKING
from .types import BakedModel, BakedFace

if TYPE_CHECKING:
    from ..materials.atlas.addressing import AtlasAddressResolver, ResolvedAtlasAddress


class ResolvedAtlasFace(NamedTuple):
    direction: str
    texture: str
    material_id: int
    tile_col: int
    tile_row: int
    uv_rot: float
    uv_bounds: tuple[float, float, float, float]
    tint_index: int
    chunk_id: int = 0
    texture_id: int = 0
    calc_uv_fn: Any = None
    source_texture_key: str = ""


class AtlasBridge:
    def __init__(self, atlas_mapping: Optional[dict[str, Any]] = None):
        from ..materials.atlas.addressing import AtlasAddressResolver
        self.atlas_mapping = atlas_mapping or {}
        self.resolver = AtlasAddressResolver(self.atlas_mapping)

    def set_mapping(self, atlas_mapping: dict[str, Any]):
        from ..materials.atlas.addressing import AtlasAddressResolver
        self.atlas_mapping = atlas_mapping or {}
        if not hasattr(self, "resolver") or self.resolver is None:
            self.resolver = AtlasAddressResolver(self.atlas_mapping)
        else:
            self.resolver.set_mapping(self.atlas_mapping)

    def resolve_face(self, face: BakedFace) -> ResolvedAtlasFace:
        """
        Map a single BakedFace to MoziToolKit Atlas tile coordinates and material ID
        using the authoritative AtlasAddressResolver.
        """
        resolved: ResolvedAtlasAddress = self.resolver.resolve_baked_face(face)
        loc = resolved.location
        tile_col = int(loc.get("tile_column", loc.get("col", 0)))
        tile_row = int(loc.get("tile_row", loc.get("row", 0)))
        mat_id = int(loc.get("material_id", resolved.chunk_id))

        return ResolvedAtlasFace(
            direction=face.direction,
            texture=face.texture,
            material_id=mat_id,
            tile_col=tile_col,
            tile_row=tile_row,
            uv_rot=face.uv_rot,
            uv_bounds=face.uv_bounds,
            tint_index=face.tint_index,
            chunk_id=resolved.chunk_id,
            texture_id=resolved.texture_id,
            calc_uv_fn=resolved.calc_uv_fn,
            source_texture_key=resolved.source_texture_key,
        )

    def resolve_model_faces(self, baked_model: BakedModel) -> list[ResolvedAtlasFace]:
        """
        Resolve all 6 standard faces of a BakedModel to Atlas properties.
        Returns list of 6 ResolvedAtlasFace objects (East, West, Up, Down, South, North).
        """
        return [self.resolve_face(face) for face in baked_model.faces]
