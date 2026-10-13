"""
Modrinth API helper for querying and downloading Minecraft resource packs (including CTM packs).

Adheres to Modrinth API v2 specification:
- Requires custom User-Agent header
- Uses standard library urllib.request for zero external dependencies
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("MoziToolKit.Bridge.Assets.Modrinth")

MODRINTH_API_BASE = "https://api.modrinth.com/v2"
USER_AGENT = "MoziToolKit/1.0.0 (https://github.com/mozi1924/MoziToolKit)"

# Curated high-quality CTM resource packs on Modrinth
RECOMMENDED_CTM_PACKS = [
    {
        "slug": "clean-connected-glass",
        "title": "Clean Connected Glass",
        "description": "Seamless connected textures for glass and stained glass.",
        "project_id": "dIyWZMgP",
    },
    {
        "slug": "vanilla-connected-glass",
        "title": "Vanilla Connected Glass",
        "description": "Vanilla styled connected textures for all types of glass blocks.",
        "project_id": "3Z8L5bYd",
    },
    {
        "slug": "generic-connected-glass",
        "title": "Connected Glass",
        "description": "Connected textures for glass blocks and panes.",
        "project_id": "9s9m11zE",
    },
]


def search_modrinth_packs(query: str = "connected glass", limit: int = 10) -> List[Dict[str, Any]]:
    """
    Searches Modrinth for resource packs matching `query`.
    """
    params = {
        "query": query,
        "facets": '[["project_type:resourcepack"]]',
        "limit": str(limit),
    }
    url = f"{MODRINTH_API_BASE}/search?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            hits = data.get("hits", [])
            results = []
            for hit in hits:
                results.append({
                    "project_id": hit.get("project_id", ""),
                    "slug": hit.get("slug", ""),
                    "title": hit.get("title", ""),
                    "description": hit.get("description", ""),
                    "downloads": hit.get("downloads", 0),
                    "icon_url": hit.get("icon_url"),
                })
            return results
    except Exception as e:
        logger.warning("Failed querying Modrinth search API: %s", e)
        return []


def get_project_versions(
    slug_or_id: str,
    game_version: Optional[str] = None,
    loaders: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Fetches versions for a given Modrinth project ID or slug.
    """
    params = {}
    if game_version:
        params["game_versions"] = f'["{game_version}"]'
    if loaders:
        params["loaders"] = json.dumps(loaders)

    query_str = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"{MODRINTH_API_BASE}/project/{slug_or_id}/version{query_str}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning("Failed querying Modrinth project versions for %s: %s", slug_or_id, e)
        return []


def download_modrinth_file(
    file_url: str,
    dest_path: Path,
    expected_size: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """
    Downloads a file from Modrinth CDN to `dest_path`.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(file_url, headers={"User-Agent": USER_AGENT})

    with urllib.request.urlopen(req, timeout=30) as resp:
        total_size = int(resp.headers.get("Content-Length") or (expected_size or 0))
        downloaded = 0
        chunk_size = 64 * 1024

        with open(dest_path, "wb") as out_f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out_f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total_size > 0:
                    progress_callback(downloaded, total_size)

    return dest_path


def fetch_modrinth_pack(
    slug_or_id: str = "clean-connected-glass",
    target_dir: Optional[Path] = None,
    game_version: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Optional[Path]:
    """
    Finds the latest version for a Modrinth resource pack and downloads it to target_dir.
    Returns the resolved local Path or None on failure.
    """
    versions = get_project_versions(slug_or_id, game_version=game_version)
    if not versions:
        logger.error("No versions found on Modrinth for project '%s'", slug_or_id)
        return None

    # Pick the latest version with valid files
    latest_ver = versions[0]
    files = latest_ver.get("files", [])
    if not files:
        logger.error("No files found in latest version of '%s'", slug_or_id)
        return None

    # Pick primary file or first file
    target_file = next((f for f in files if f.get("primary")), files[0])
    file_url = target_file["url"]
    filename = target_file.get("filename") or f"{slug_or_id}.zip"
    file_size = target_file.get("size")

    out_dir = target_dir or (Path.home() / ".cache" / "mozitoolkit" / "resourcepacks")
    dest_file = out_dir / filename

    if dest_file.exists() and dest_file.stat().st_size == file_size:
        logger.info("Modrinth pack already cached at %s", dest_file)
        return dest_file

    logger.info("Downloading Modrinth pack '%s' -> %s ...", filename, dest_file)
    return download_modrinth_file(
        file_url=file_url,
        dest_path=dest_file,
        expected_size=file_size,
        progress_callback=progress_callback,
    )
