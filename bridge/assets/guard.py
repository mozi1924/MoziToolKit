"""
Bridge compatibility module for Asset Cache Readiness Guard & Operator Gating Subsystem.

DEPRECATED: Asset guards and execution scheduling are host-level orchestrators.
Use `utils.assets.guard` directly instead.
"""

from __future__ import annotations

try:
    from ...utils.assets.guard import (
        check_asset_cache_status,
        ensure_pipeline_assets_ready_sync,
        prepare_asset_context,
        run_task_with_asset_guard,
    )
except (ImportError, ValueError):
    from utils.assets.guard import (
        check_asset_cache_status,
        ensure_pipeline_assets_ready_sync,
        prepare_asset_context,
        run_task_with_asset_guard,
    )

__all__ = [
    "prepare_asset_context",
    "check_asset_cache_status",
    "ensure_pipeline_assets_ready_sync",
    "run_task_with_asset_guard",
]
