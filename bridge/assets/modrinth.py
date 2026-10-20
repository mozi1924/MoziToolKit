"""
Bridge compatibility module for Modrinth pack operations.

DEPRECATED: Modrinth pack operations are host-level utility functions.
Use `utils.assets.modrinth` directly instead.
"""

from __future__ import annotations

try:
    from ...utils.assets.modrinth import (
        MODRINTH_API_BASE,
        RECOMMENDED_CTM_PACKS,
        USER_AGENT,
        default_cache_dir,
        download_modrinth_file,
        fetch_modrinth_pack,
        get_project_versions,
        search_modrinth_packs,
    )
except (ImportError, ValueError):
    from utils.assets.modrinth import (
        MODRINTH_API_BASE,
        RECOMMENDED_CTM_PACKS,
        USER_AGENT,
        default_cache_dir,
        download_modrinth_file,
        fetch_modrinth_pack,
        get_project_versions,
        search_modrinth_packs,
    )

__all__ = [
    "MODRINTH_API_BASE",
    "RECOMMENDED_CTM_PACKS",
    "USER_AGENT",
    "default_cache_dir",
    "download_modrinth_file",
    "fetch_modrinth_pack",
    "get_project_versions",
    "search_modrinth_packs",
]
