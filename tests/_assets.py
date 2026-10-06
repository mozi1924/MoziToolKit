"""
Shared test-asset resolver for the MoziToolKit test suite (mirrors `mtk-testkit`).

Real Minecraft resource packs / saves are large and licensed, so they are never committed.
This module resolves them at test time using a deterministic priority chain:

1. Environment variable overrides (set by CI / local dev).
2. Conventional paths adjacent to the workspace (`../mc`, `../26.2-Fabric.jar`, ...).

Tests that require real assets must call `require_assets()` / `require_jar()` and skip
gracefully when the asset is unavailable, so the suite stays green on a fresh clone and
inside CI regardless of whether the real packs were downloaded.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# tests/_assets.py -> parents[0] = tests/, parents[1] = MoziToolKit/, parents[2] = <mtk>/
_WORKSPACE_PARENT = Path(__file__).resolve().parents[2]

_ASSET_ENV_VARS = ("MTK_TEST_ASSETS", "MC_ASSETS_DIR", "MC_DIR")
_JAR_ENV_VARS = ("MTK_TEST_JAR", "MC_JAR")


def _is_asset_root(path: Path) -> bool:
    return (path / "assets" / "minecraft").is_dir()


def assets_root() -> Optional[Path]:
    """Root directory that contains `assets/minecraft`, or `None` if unavailable."""
    for key in _ASSET_ENV_VARS:
        value = os.environ.get(key)
        if value and _is_asset_root(Path(value)):
            return Path(value)

    candidates = [
        _WORKSPACE_PARENT / "mc",
        _WORKSPACE_PARENT / "libmozitoolkit" / ".." / "mc",
    ]
    for candidate in candidates:
        if _is_asset_root(candidate):
            return candidate.resolve()
    return None


def fabric_jar() -> Optional[Path]:
    """Minecraft client / modpack jar used for pack-level baking tests."""
    for key in _JAR_ENV_VARS:
        value = os.environ.get(key)
        if value and Path(value).exists():
            return Path(value)

    candidates = [
        _WORKSPACE_PARENT / "26.2-Fabric.jar",
        Path.home() / "26.2-Fabric.jar",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def resource_pack_zip() -> Optional[Path]:
    """External resource pack `.zip` (SPBR / Continuity / PBR companions)."""
    value = os.environ.get("MTK_TEST_RESOURCE_PACK") or os.environ.get("MTK_TEST_RESOURCEPACK")
    if value and Path(value).exists():
        return Path(value)

    candidates = [
        _WORKSPACE_PARENT / "SPBR-21.zip",
        Path.home() / "Downloads" / "SPBR-21.zip",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def save_world() -> Optional[Path]:
    """A Minecraft save directory containing `level.dat`."""
    value = os.environ.get("MTK_TEST_SAVE")
    if value and Path(value).exists():
        return Path(value)
    return None


def blender_datafiles_cache() -> Optional[Path]:
    """Blender `DATAFILES/MoziToolKit/cache` directory, if resolvable on this machine."""
    value = os.environ.get("MTK_TEST_CACHE")
    if value and Path(value).exists():
        return Path(value)

    candidates = [
        _WORKSPACE_PARENT / "cache",
        _WORKSPACE_PARENT / "MoziToolKit" / "cache",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def require_assets() -> Path:
    """Returns the asset root or skips the enclosing test.

    The resolved path is exported to `MC_DIR` / `MC_ASSETS_DIR` so that production bridge
    code (`bridge/debug.py` etc.) locates the same assets the test suite found.
    """
    root = assets_root()
    if root is None:
        import pytest

        pytest.skip(
            "Minecraft assets unavailable: set MTK_TEST_ASSETS / MC_DIR or place an "
            "unpacked jar at ../mc"
        )
    os.environ.setdefault("MC_DIR", str(root))
    os.environ.setdefault("MC_ASSETS_DIR", str(root))
    os.environ.setdefault("MTK_TEST_ASSETS", str(root))
    return root


def require_jar() -> Path:
    """Returns the Minecraft jar path or skips the enclosing test."""
    jar = fabric_jar()
    if jar is None:
        import pytest

        pytest.skip(
            "Minecraft jar unavailable: set MTK_TEST_JAR or place ../26.2-Fabric.jar"
        )
    os.environ.setdefault("MTK_TEST_JAR", str(jar))
    return jar
