"""
Single access point for host-side profiling from the bridge layer.

The implementation lives in ``utils.diagnostics``; this module only resolves the
package-relative vs top-level import mode once so bridge modules do not have to
repeat the fallback (and never import the dev-only package).
"""

from ..utils.diagnostics import (
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
