from dataclasses import dataclass


@dataclass
class ExtrudeRepairConfig:
    """Configuration options for the auto extrude UV and crease repair operation."""

    repair_uv: bool = True
    add_crease: bool = False
    crease_val: float = 1.0
    only_collapsed: bool = False
    uv_mode: str = "INWARD"  # 'INWARD' or 'OUTWARD'
