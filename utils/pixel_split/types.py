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
class SplitConfig:
    """Configuration options for the adaptive pixel split operation."""
    auto_resolution: bool = True
    manual_resolution: Tuple[int, int] = (64, 64)
    pixels_per_face: int = 1  # 1 means 1 face = 1 pixel grid cell
    dissolve_pre_split: bool = True
    selection_scope: str = "ALL"  # 'ALL', 'SELECTED', or 'LINKED'
