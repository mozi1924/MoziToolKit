"""Import-compatibility profile loader.

The JSON file is intentionally Python-owned so modded/legacy exporter fixes can
be iterated without recompiling the Rust core. It is merged into the precompiled
asset cache and installed again when that cache is opened.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("MoziToolKit.Bridge.Assets.Compat")

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "configs" / "import_compat.json"
_ENV_PATH = "MTK_IMPORT_COMPAT"


def import_compat_path() -> Path:
    override = os.environ.get(_ENV_PATH, "").strip()
    return Path(override) if override else _DEFAULT_PATH


def load_import_compat_json() -> Optional[str]:
    path = import_compat_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Import compatibility profile %s is unreadable: %s", path, exc)
        return None
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Import compatibility profile %s is invalid JSON: %s", path, exc)
        return None
    return text


_STAMP_NAME = "import_compat.sha256"


def compat_profile_hash(text: Optional[str] = None) -> str:
    payload = load_import_compat_json() if text is None else text
    return hashlib.sha256(payload.encode("utf-8")).hexdigest() if payload else ""


def compat_stamp_matches(cache_dir: Path) -> bool:
    expected = compat_profile_hash()
    if not expected:
        return True
    stamp = Path(cache_dir) / _STAMP_NAME
    try:
        return stamp.read_text(encoding="utf-8").strip() == expected
    except OSError:
        return False


def write_compat_stamp(cache_dir: Path, profile_json: Optional[str] = None) -> None:
    stamp = Path(cache_dir) / _STAMP_NAME
    expected = compat_profile_hash(profile_json)
    try:
        if expected:
            stamp.write_text(expected, encoding="utf-8")
        elif stamp.exists():
            stamp.unlink()
    except OSError as exc:
        logger.warning("Could not write import compatibility stamp: %s", exc)
