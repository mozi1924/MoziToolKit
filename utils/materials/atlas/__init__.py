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

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

if HAS_BPY:
    from .builder import (
        build_atlas_material,
        build_atlas_chunk_materials,
    )
    from .pipeline import (
        AtlasReplacementEngine,
    )
else:
    build_atlas_material = None
    build_atlas_chunk_materials = None
    AtlasReplacementEngine = None

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
