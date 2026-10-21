"""
Resource Pack Stack Configuration Bridge.
Extracts enabled resource packs and Fabric/Vanilla JARs from Blender preferences
and configures the libmtk native ResourcePackStack.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from ..engine import get_libmtk

logger = logging.getLogger("MoziToolKit.Bridge.Assets.Pack")

from ...utils.system import get_prefs


_CACHED_PACK_STACK: Optional[Any] = None
_CACHED_STACK_SIGNATURE: Optional[tuple] = None
_CACHED_CTM_SOLVER: Optional[Any] = None
_CACHED_CTM_SIGNATURE: Optional[tuple] = None


def invalidate_pack_stack_cache() -> None:
    """Invalidates memoized ResourcePackStack and CtmSolver instances."""
    global _CACHED_PACK_STACK, _CACHED_STACK_SIGNATURE, _CACHED_CTM_SOLVER, _CACHED_CTM_SIGNATURE
    _CACHED_PACK_STACK = None
    _CACHED_STACK_SIGNATURE = None
    _CACHED_CTM_SOLVER = None
    _CACHED_CTM_SIGNATURE = None


def get_configured_pack_stack(prefs=None) -> Optional[Any]:
    """
    Builds a libmtk ResourcePackStack from the Blender preferences configuration.
    Traverses enabled entries in order and pushes them to Rust.
    Reuses cached stack instance if configuration paths and mtimes are unchanged.
    """
    global _CACHED_PACK_STACK, _CACHED_STACK_SIGNATURE
    mtk = get_libmtk()
    if mtk is None:
        return None

    if prefs is None:
        prefs = get_prefs()

    # Collect active entries to compute a lightweight mtime-based signature
    paths_to_check = []
    single_path = getattr(prefs, "resource_pack_path", None) if prefs else None
    if single_path and Path(single_path).exists():
        paths_to_check.append(str(Path(single_path).resolve()))

    if prefs and hasattr(prefs, "resource_packs"):
        for entry in prefs.resource_packs:
            if getattr(entry, "enabled", True):
                raw_path = getattr(entry, "path", "").strip()
                if raw_path and Path(raw_path).exists():
                    paths_to_check.append(str(Path(raw_path).resolve()))

    sig = tuple((p, os.path.getmtime(p) if os.path.exists(p) else 0.0) for p in paths_to_check)
    if _CACHED_PACK_STACK is not None and _CACHED_STACK_SIGNATURE == sig:
        return _CACHED_PACK_STACK

    stack = mtk.ResourcePackStack()

    if not paths_to_check:
        _CACHED_PACK_STACK = stack
        _CACHED_STACK_SIGNATURE = sig
        return stack

    # 1. Single direct pack path if present
    if single_path and Path(single_path).exists():
        p = Path(single_path)
        if p.is_dir():
            stack.add_directory_pack(str(p.resolve()), p.stem)
        elif p.is_file() and p.suffix.lower() in {".zip", ".jar"}:
            stack.add_zip_pack(str(p.resolve()))

    # 2. Resource pack list entries
    if hasattr(prefs, "resource_packs"):
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

    _CACHED_PACK_STACK = stack
    _CACHED_STACK_SIGNATURE = sig
    return stack


def get_configured_ctm_solver(prefs=None) -> Optional[Any]:
    """
    Builds a CtmSolver from the configured resource pack stack if any CTM rules exist.
    Memoized against the active pack stack signature.
    """
    global _CACHED_CTM_SOLVER, _CACHED_CTM_SIGNATURE
    if prefs is not None and not getattr(prefs, "enable_ctm", True):
        return None
    stack = get_configured_pack_stack(prefs)
    if stack is None:
        return None

    ctm_sig = (_CACHED_STACK_SIGNATURE, True)
    if _CACHED_CTM_SOLVER is not None and _CACHED_CTM_SIGNATURE == ctm_sig:
        return _CACHED_CTM_SOLVER

    if hasattr(stack, "build_ctm_solver"):
        try:
            if hasattr(stack, "get_ctm_rule_count") and stack.get_ctm_rule_count() == 0:
                _CACHED_CTM_SOLVER = None
                _CACHED_CTM_SIGNATURE = ctm_sig
                return None
            solver = stack.build_ctm_solver()
            _CACHED_CTM_SOLVER = solver
            _CACHED_CTM_SIGNATURE = ctm_sig
            return solver
        except Exception as e:
            logger.debug("Failed building CTM solver: %s", e)
    return None


__all__ = ["get_configured_pack_stack", "get_configured_ctm_solver", "invalidate_pack_stack_cache"]
