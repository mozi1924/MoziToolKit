"""
Atlas Bridge for connecting BakedModel results to MoziToolKit Atlas Materials.
Maps standard texture resource identifiers to Atlas tiles, material IDs, and shader attributes.
Powered by LibMTK high-performance pure-Rust backend.
"""

from __future__ import annotations
from typing import Any, Optional, NamedTuple
import libmtk_py as mtk

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
    chunk_id: int = 0
    texture_id: int = 0
    calc_uv_fn: Any = None
    source_texture_key: str = ""
    local_uvs: Optional[list[list[float]]] = None
    atlas_uvs: Optional[list[list[float]]] = None


class AtlasBridge:
    """Bridge for resolving BakedModel faces to Atlas tiles and UV coordinates."""
    def __init__(self, atlas_or_mapping: Optional[Any] = None):
        self._rust_bridge: Optional[mtk.AtlasBridge] = None
        self._atlas: Optional[mtk.BakedAtlas] = None
        self.atlas_mapping: dict[str, Any] = {}
        self.resolver = None

        if atlas_or_mapping is not None:
            self.set_mapping(atlas_or_mapping)

    def set_mapping(self, atlas_or_mapping: Any):
        if isinstance(atlas_or_mapping, mtk.BakedAtlas):
            self._atlas = atlas_or_mapping
            self._rust_bridge = mtk.AtlasBridge(atlas_or_mapping)
            self.atlas_mapping = {}
        elif hasattr(atlas_or_mapping, "inner") and isinstance(getattr(atlas_or_mapping, "inner"), mtk.BakedAtlas):
            self._atlas = atlas_or_mapping.inner
            self._rust_bridge = mtk.AtlasBridge(atlas_or_mapping.inner)
            self.atlas_mapping = {}
        else:
            self.atlas_mapping = atlas_or_mapping or {}
            self._atlas = None
            self._rust_bridge = None
            try:
                from ..materials.atlas.addressing import AtlasAddressResolver
                self.resolver = AtlasAddressResolver(self.atlas_mapping)
            except Exception:
                self.resolver = None

    def resolve_face(self, face: Any) -> ResolvedAtlasFace:
        """Map a single BakedFace to Atlas properties."""
        if self._rust_bridge is not None and hasattr(face, "inner"):
            res = self._rust_bridge.resolve_face(face)
            return ResolvedAtlasFace(
                direction=res.direction,
                texture=res.texture,
                material_id=res.material_id,
                tile_col=res.tile_col,
                tile_row=res.tile_row,
                uv_rot=res.uv_rot,
                uv_bounds=tuple(res.uv_bounds),
                tint_index=res.tint_index,
                chunk_id=res.chunk_id,
                texture_id=res.texture_id,
                local_uvs=res.local_uvs,
                atlas_uvs=res.atlas_uvs,
            )

        if self.resolver is not None:
            resolved = self.resolver.resolve_baked_face(face)
            loc = resolved.location
            tile_col = int(loc.get("tile_column", loc.get("col", 0)))
            tile_row = int(loc.get("tile_row", loc.get("row", 0)))
            mat_id = int(loc.get("material_id", resolved.chunk_id))
            return ResolvedAtlasFace(
                direction=getattr(face, "direction", "up"),
                texture=getattr(face, "texture", ""),
                material_id=mat_id,
                tile_col=tile_col,
                tile_row=tile_row,
                uv_rot=getattr(face, "uv_rot", 0.0),
                uv_bounds=getattr(face, "uv_bounds", (0.0, 0.0, 1.0, 1.0)),
                tint_index=getattr(face, "tint_index", -1),
                chunk_id=resolved.chunk_id,
                texture_id=resolved.texture_id,
                calc_uv_fn=resolved.calc_uv_fn,
                source_texture_key=resolved.source_texture_key,
            )

        return ResolvedAtlasFace(
            direction=getattr(face, "direction", "up"),
            texture=getattr(face, "texture", ""),
            material_id=0,
            tile_col=0,
            tile_row=0,
            uv_rot=getattr(face, "uv_rot", 0.0),
            uv_bounds=getattr(face, "uv_bounds", (0.0, 0.0, 1.0, 1.0)),
            tint_index=getattr(face, "tint_index", -1),
        )

    def resolve_model_faces(self, baked_model: Any) -> list[ResolvedAtlasFace]:
        """Resolve all standard faces of a BakedModel to Atlas properties."""
        if self._atlas is not None and hasattr(baked_model, "resolve_with_atlas"):
            resolved = baked_model.resolve_with_atlas(self._atlas)
            return [
                ResolvedAtlasFace(
                    direction=f.direction,
                    texture=f.texture,
                    material_id=f.material_id,
                    tile_col=f.tile_col,
                    tile_row=f.tile_row,
                    uv_rot=f.uv_rot,
                    uv_bounds=tuple(f.uv_bounds),
                    tint_index=f.tint_index,
                    chunk_id=f.chunk_id,
                    texture_id=f.texture_id,
                    local_uvs=f.local_uvs,
                    atlas_uvs=f.atlas_uvs,
                )
                for f in resolved.faces
            ]

        faces = getattr(baked_model, "faces", [])
        return [self.resolve_face(face) for face in faces]
