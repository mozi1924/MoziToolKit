from dataclasses import dataclass, field
from typing import Tuple, Optional


@dataclass
class UVBounds:
    """Bounding box of UV coordinates for a face or group of faces."""
    min_u: float
    max_u: float
    min_v: float
    max_v: float

    @property
    def width(self) -> float:
        return self.max_u - self.min_u

    @property
    def height(self) -> float:
        return self.max_v - self.min_v


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
    only_selected: bool = False
