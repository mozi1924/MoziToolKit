"""
Resource Pack Stack Configuration Bridge.
Extracts enabled resource packs and Fabric/Vanilla JARs from Blender preferences
and configures the libmtk native ResourcePackStack.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from ..engine import get_libmtk

logger = logging.getLogger("MoziToolKit.Bridge.Assets.Pack")

try:
    from ...utils.system import get_prefs
except (ImportError, ValueError):
    from utils.system import get_prefs


def get_configured_pack_stack(prefs=None) -> Optional[Any]:
    """
    Builds a libmtk ResourcePackStack from the Blender preferences configuration.
    Traverses enabled entries in order and pushes them to Rust.
    """
    mtk = get_libmtk()
    if mtk is None:
        return None

    if prefs is None:
        prefs = get_prefs()

    stack = mtk.ResourcePackStack()

    if prefs is None or not hasattr(prefs, "resource_packs"):
        return stack

    for entry in prefs.resource_packs:
        if not getattr(entry, "enabled", True):
            continue

        raw_path = getattr(entry, "path", "").strip()
        if not raw_path:
            continue

        p = Path(raw_path)
        if not p.exists():
            continue

        name = getattr(entry, "name", None) or p.stem

        if p.is_dir():
            stack.add_directory_pack(str(p.resolve()), name)
        elif p.is_file() and p.suffix.lower() in {".zip", ".jar"}:
            stack.add_zip_pack(str(p.resolve()))

    return stack


__all__ = ["get_configured_pack_stack"]
