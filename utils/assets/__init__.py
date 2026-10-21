"""
MoziToolKit Utils: Asset Management & Processing Subsystem.

Contains host-level asset helpers including Modrinth pack discovery/downloads,
cache directory resolvers, and execution guards.
"""

from __future__ import annotations

from .cache_utils import (
    clear_cache,
    get_cache_dir,
    get_cache_stats,
    open_cache_folder,
)
from .guard import (
    can_execute_asset_pipeline,
    check_asset_cache_status,
    ensure_pipeline_assets_ready_sync,
    has_valid_vanilla_pack,
    prepare_asset_context,
    run_task_with_asset_guard,
)
from .modrinth import (
    RECOMMENDED_CTM_PACKS,
    default_cache_dir,
    download_modrinth_file,
    fetch_modrinth_pack,
    get_project_versions,
    search_modrinth_packs,
)

__all__ = [
    # Cache utils
    "get_cache_dir",
    "get_cache_stats",
    "clear_cache",
    "open_cache_folder",
    # Guards
    "has_valid_vanilla_pack",
    "can_execute_asset_pipeline",
    "check_asset_cache_status",
    "prepare_asset_context",
    "ensure_pipeline_assets_ready_sync",
    "run_task_with_asset_guard",
    # Modrinth
    "RECOMMENDED_CTM_PACKS",
    "default_cache_dir",
    "search_modrinth_packs",
    "get_project_versions",
    "download_modrinth_file",
    "fetch_modrinth_pack",
]
