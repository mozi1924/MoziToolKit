"""Attribute contract and constants for MoziToolKit Live Sync and Direct Mesh Generation."""

from __future__ import annotations
from typing import Final

CONTRACT_VERSION: Final = 5
FACES: Final = ("east", "west", "top", "bottom", "south", "north")

# Direction vectors in Minecraft space (East=+X, West=-X, Up=+Y, Down=-Y, South=+Z, North=-Z)
MC_DIR_OFFSETS: Final[dict[str, tuple[int, int, int]]] = {
    "east": (1, 0, 0),
    "west": (-1, 0, 0),
    "up": (0, 1, 0),
    "top": (0, 1, 0),
    "down": (0, -1, 0),
    "bottom": (0, -1, 0),
    "south": (0, 0, 1),
    "north": (0, 0, -1),
}

DIR_TO_INDEX: Final[dict[str, int]] = {
    "east": 0,
    "west": 1,
    "up": 2,
    "top": 2,
    "down": 3,
    "bottom": 3,
    "south": 4,
    "north": 5,
}

# Native Direct Mesh Face Attribute Convention
MTK_BLOCK_X: Final = "mtk_block_x"
MTK_BLOCK_Y: Final = "mtk_block_y"
MTK_BLOCK_Z: Final = "mtk_block_z"
MTK_FACE_DIR: Final = "mtk_face_dir"
MTK_MATERIAL_ID: Final = "mtk_material_id"
MTK_IS_OPAQUE: Final = "mtk_is_opaque"
MTK_EMISSIVE: Final = "mtk_emissive"
MTK_ATLAS_WIDTH: Final = "mtk_atlas_width"
MTK_ATLAS_HEIGHT: Final = "mtk_atlas_height"
MTK_TILE_SIZE: Final = "mtk_tile_size"
MTK_TILES_PER_ROW: Final = "mtk_tiles_per_row"
MTK_ANIM_ATLAS_WIDTH: Final = "mtk_anim_atlas_width"
MTK_ANIM_ATLAS_HEIGHT: Final = "mtk_anim_atlas_height"
MTK_ANIM_FRAME_WIDTH: Final = "mtk_anim_frame_width"
MTK_ANIM_FRAME_HEIGHT: Final = "mtk_anim_frame_height"
MTK_BIOME_TINT_COLOR: Final = "mtk_biome_tint_color"
MTK_BIOME_TINT_DATA: Final = "mtk_biome_tint_data"
MTK_UV_TILING_TRANSFORM: Final = "mtk_uv_tiling_transform"
MTK_UV_ROTATION: Final = "mtk_uv_rotation"
MTK_ATLAS_CHUNK_ID: Final = "mtk_atlas_chunk_id"
MTK_ATLAS_TEXTURE_ID: Final = "mtk_atlas_texture_id"
MTK_SOURCE_TEXTURE_KEY: Final = "mtk_source_texture_key"
MTK_SOURCE_ORIGIN: Final = "mtk_source_origin"
MTK_ANIM_TIMING: Final = "mtk_anim_timing"
MTK_ANIM_FRAME_SIZE: Final = "mtk_anim_frame_size"
UV_MAP: Final = "UVMap"

# Standard Atlas Dimension Defaults
DEFAULT_ATLAS_WIDTH: Final = 1024.0
DEFAULT_ATLAS_HEIGHT: Final = 1024.0
DEFAULT_TILE_SIZE: Final = 16.0
DEFAULT_TILES_PER_ROW: Final = 64
DEFAULT_ANIM_ATLAS_WIDTH: Final = 896.0
DEFAULT_ANIM_ATLAS_HEIGHT: Final = 1024.0
DEFAULT_ANIM_FRAME_WIDTH: Final = 16.0
DEFAULT_ANIM_FRAME_HEIGHT: Final = 16.0

# Canonical Object and Mesh Names
DEFAULT_WORLD_OBJECT_NAME: Final = "Yefira_World"
DEFAULT_WORLD_MESH_NAME: Final = "Yefira_World_Mesh"

# Binary Live Sync Wire Protocol Constants
PROTOCOL_MAGIC: Final = b"MC"
PROTOCOL_VERSION: Final = 0x01


class PacketType:
    SELECTION_INFO: Final = 0x01
    FULL_SNAPSHOT: Final = 0x02
    DELTA_UPDATE: Final = 0x03
    SECTION_MANIFEST: Final = 0x05
    SECTION_SNAPSHOT: Final = 0x06
    REPAIR_REQUEST: Final = 0x81
    SYNC_CONFIG: Final = 0x82


HEADER_FORMAT: Final = "<2sBB"
HEADER_SIZE: Final = 4

SELECTION_INFO_FORMAT: Final = "<iiiiii"
SELECTION_INFO_SIZE: Final = 24

DELTA_HEADER_FORMAT: Final = "<IiiiH"
DELTA_HEADER_SIZE: Final = 18

DELTA_CHANGE_PREFIX_FORMAT: Final = "<HHHH"
DELTA_CHANGE_PREFIX_SIZE: Final = 8

MANIFEST_HEADER_FORMAT: Final = "<IH"
MANIFEST_HEADER_SIZE: Final = 6

MANIFEST_ENTRY_FORMAT: Final = "<iiiI"
MANIFEST_ENTRY_SIZE: Final = 16

SECTION_SNAPSHOT_HEADER_FORMAT: Final = "<iiiiiiiiiH"
SECTION_SNAPSHOT_HEADER_SIZE: Final = 38

CONTRACT_ATTRIBUTE_KEY: Final = "yefira:attribute_contract"


def get_attribute_contract_version(mesh) -> Optional[int]:
    """Retrieve the attribute contract version integer from a mesh custom property, or None."""
    if mesh is None:
        return None
    val = mesh.get(CONTRACT_ATTRIBUTE_KEY)
    if val is not None:
        try:
            return int(val)
        except (ValueError, TypeError):
            return None
    return None


def is_contract_compatible(mesh, min_version: int = CONTRACT_VERSION) -> bool:
    """Return True if mesh contract version is compatible with expected contract version."""
    ver = get_attribute_contract_version(mesh)
    if ver is None:
        return True
    return ver >= min_version

