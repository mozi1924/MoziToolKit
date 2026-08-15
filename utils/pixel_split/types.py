from dataclasses import dataclass
from typing import Tuple
from ..uv import UVBounds


@dataclass
class TargetGrid:
    """Target pixel subdivision grid dimensions for a face."""
    cols: int  # Number of horizontal pixel subdivisions
    rows: int  # Number of vertical pixel subdivisions
    tex_w: int  # Full texture width
    tex_h: int  # Full texture height


@dataclass
class FacePixelInfo:
    """Detailed resolution and mapping information detected for a face."""
    effective_resolution: Tuple[int, int]  # (width, height) in pixels for local UV [0, 1] frame
    raw_image_resolution: Tuple[int, int]  # (width, height) of underlying texture datablock
    material_mode: str = "GENERIC"  # 'STANDALONE', 'ATLAS_CHUNK', 'ATLAS_UNIFIED', 'GENERIC'
    is_animated: bool = False
    total_frames: int = 1
    frame_width: int = 16
    frame_height: int = 16
    uv_mode: str = "LOCAL"  # 'LOCAL' or 'ATLAS_BAKED'


@dataclass
class SplitConfig:
    """Configuration options for the adaptive pixel split operation."""
    auto_resolution: bool = True
    manual_resolution: Tuple[int, int] = (64, 64)
    pixels_per_face: int = 1  # 1 means 1 face = 1 pixel grid cell
    selection_scope: str = "ALL"  # 'ALL', 'SELECTED', or 'LINKED'
    max_subdivisions: int = 1024  # Max subdivisions per face dimension to prevent memory explosion


