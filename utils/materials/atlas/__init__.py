"""
Texture Atlas packing, layout math, generation, and chunk node tree building.
"""

from .packer import (
    PackedRect,
    MaxRectsBinPack,
    pack_category_textures,
)

from .layout import (
    face_index_from_normal,
    static_cell,
    chunk_cell,
    atlas_uv_from_local,
    atlas_uv_from_rect,
    local_uv_from_atlas,
    local_uv_from_rect,
    find_texture_id_from_atlas_uv,
    remap_uv_to_local,
    remap_local_to_target_uv,
    remap_uv_coordinate,
)

from .generator import AtlasGenerator

from .builder import (
    build_atlas_material,
    build_atlas_chunk_materials,
)

from .pipeline import (
    AtlasReplacementEngine,
)

from .addressing import (
    AtlasAddressResolver,
    ResolvedAtlasAddress,
)

__all__ = [
    "PackedRect",
    "MaxRectsBinPack",
    "pack_category_textures",
    "face_index_from_normal",
    "static_cell",
    "chunk_cell",
    "atlas_uv_from_local",
    "atlas_uv_from_rect",
    "local_uv_from_atlas",
    "local_uv_from_rect",
    "find_texture_id_from_atlas_uv",
    "remap_uv_to_local",
    "remap_local_to_target_uv",
    "remap_uv_coordinate",
    "AtlasGenerator",
    "build_atlas_material",
    "build_atlas_chunk_materials",
    "AtlasReplacementEngine",
    "AtlasAddressResolver",
    "ResolvedAtlasAddress",
]
