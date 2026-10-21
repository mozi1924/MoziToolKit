"""
MoziToolKit Dev Profile Tracker (compatibility alias).

The tracker itself lives in :mod:`utils.diagnostics` so the bridge layer and
release builds can record profiles without importing the dev package. This
module only keeps the historical import path used by the dev UI and tests.
"""

try:
    from ..utils.diagnostics import (
        append_stage_to_last_profile,
        clear_last_profile,
        get_last_profile,
        record_operation_profile,
    )
except (ImportError, ValueError):
    from utils.diagnostics import (
        append_stage_to_last_profile,
        clear_last_profile,
        get_last_profile,
        record_operation_profile,
    )

__all__ = [
    "record_operation_profile",
    "append_stage_to_last_profile",
    "get_last_profile",
    "clear_last_profile",
]
