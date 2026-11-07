"""
MoziToolKit Asset Source Classification (Content-Based Pack Probe).

Classifies a user-selected ``.jar`` / ``.zip`` archive (or an extracted assets folder) as a
Minecraft **vanilla client**, **vanilla server**, **mod** (Fabric / Quilt / Forge / NeoForge),
**resource pack**, **data pack**, or **modpack** by inspecting ZIP central-directory entry names
and metadata payloads.

Architecture & Constraints (GEMINI.md Rule 1 & Rule 2):
* Host-agnostic scanning and scoring are executed natively in Rust (`libmtk_py.probe_pack`).
* Zero Python fallback: all heuristic ranking and ZIP parsing live in `mtk-resource::probe`.
* Results are memoized by ``(resolved path, size, mtime_ns)`` so repeated UI redraws and
  typing in the path field never re-open the archive.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..bridge.engine import get_libmtk

logger = logging.getLogger("MoziToolKit.Utils.PackDetect")

# ---------------------------------------------------------------------------
# Internal kinds (richer than the 3-tier UI model)
# ---------------------------------------------------------------------------

KIND_VANILLA_CLIENT = "VANILLA_CLIENT"
KIND_VANILLA_SERVER = "VANILLA_SERVER"
KIND_MOD = "MOD"
KIND_RESOURCE_PACK = "RESOURCE_PACK"
KIND_DATA_PACK = "DATA_PACK"
KIND_MODPACK = "MODPACK"
KIND_UNKNOWN = "UNKNOWN"

ALL_KINDS: Tuple[str, ...] = (
    KIND_VANILLA_CLIENT,
    KIND_VANILLA_SERVER,
    KIND_MOD,
    KIND_RESOURCE_PACK,
    KIND_DATA_PACK,
    KIND_MODPACK,
    KIND_UNKNOWN,
)

#: Human-readable labels (translated at the UI edge via ``i18n.tr``).
KIND_LABELS: Dict[str, str] = {
    KIND_VANILLA_CLIENT: "Vanilla Client",
    KIND_VANILLA_SERVER: "Vanilla Server",
    KIND_MOD: "Mod (Fabric/Forge/NeoForge/Quilt)",
    KIND_RESOURCE_PACK: "Resource Pack",
    KIND_DATA_PACK: "Data Pack",
    KIND_MODPACK: "Modpack",
    KIND_UNKNOWN: "Unknown",
}

#: Mapping from rich kinds to the strict 3-tier pack type used by the fallback stack.
KIND_TO_PACK_TYPE: Dict[str, Optional[str]] = {
    KIND_VANILLA_CLIENT: "VANILLA",
    KIND_VANILLA_SERVER: "VANILLA",
    KIND_MOD: "MOD_JAR",
    KIND_RESOURCE_PACK: "RESOURCE_PACK",
    KIND_DATA_PACK: None,
    KIND_MODPACK: None,
    KIND_UNKNOWN: None,
}

#: Kinds that can actually contribute textures/models to the bake pipeline.
TEXTURE_SOURCE_KINDS = frozenset({KIND_VANILLA_CLIENT, KIND_MOD, KIND_RESOURCE_PACK})

#: Kinds that qualify as a valid standalone vanilla foundation base pack.
VALID_BASE_PACK_KINDS = frozenset({KIND_VANILLA_CLIENT})

TYPE_SOURCE_AUTO = "AUTO"
TYPE_SOURCE_MANUAL = "MANUAL"

_CACHE_LIMIT = 128


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class PackProbe:
    """Result of :func:`detect_pack_kind`."""

    kind: str = KIND_UNKNOWN
    confidence: float = 0.0
    suggested_pack_type: Optional[str] = None
    evidence: Tuple[str, ...] = ()
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    elapsed_ms: float = 0.0
    entry_count: int = 0
    cached: bool = False

    @property
    def is_known(self) -> bool:
        return self.kind != KIND_UNKNOWN

    @property
    def is_texture_source(self) -> bool:
        return self.kind in TEXTURE_SOURCE_KINDS

    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "confidence": round(self.confidence, 3),
            "suggested_pack_type": self.suggested_pack_type,
            "evidence": list(self.evidence),
            "details": dict(self.details),
            "error": self.error,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "entry_count": self.entry_count,
            "cached": self.cached,
        }


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_CACHE: "OrderedDict[Tuple[str, int, int], PackProbe]" = OrderedDict()
#: Last probe per *caller-supplied* path string, so UI code can peek without any filesystem I/O.
_BY_INPUT: "OrderedDict[str, PackProbe]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_HITS = 0
_CACHE_MISSES = 0


def _resolve(path: Any) -> Optional[Path]:
    try:
        return Path(os.fspath(path)).expanduser()
    except (TypeError, ValueError):
        return None


def _stat_key(path: Path) -> Optional[Tuple[str, int, int]]:
    try:
        st = path.stat()
        return (str(path.resolve()), int(st.st_size), int(st.st_mtime_ns))
    except OSError:
        return None


def invalidate_pack_probe(path: Any = None) -> None:
    """Drop one entry (or the whole probe cache). Call after an archive is replaced on disk."""
    global _CACHE_HITS, _CACHE_MISSES
    with _CACHE_LOCK:
        if path is None:
            _CACHE.clear()
            _BY_INPUT.clear()
            _CACHE_HITS = 0
            _CACHE_MISSES = 0
            return
        try:
            raw = os.fspath(path)
        except TypeError:
            return
        stripped = raw.strip()
        _BY_INPUT.pop(raw, None)
        _BY_INPUT.pop(stripped, None)
        resolved = _resolve(path)
        if resolved is None:
            return
        try:
            key_path = str(resolved.resolve())
        except OSError:
            key_path = str(resolved)
        stale = [key for key in _CACHE if key[0] == key_path]
        for key in stale:
            _CACHE.pop(key, None)


def pack_probe_cache_info() -> Dict[str, int]:
    """Return probe cache statistics (used by tests and diagnostics)."""
    with _CACHE_LOCK:
        return {"hits": _CACHE_HITS, "misses": _CACHE_MISSES, "size": len(_CACHE)}


def peek_cached_probe(path: Any) -> Optional[PackProbe]:
    """Return the last probe for *path* without touching the filesystem (safe inside ``draw``)."""
    try:
        raw = os.fspath(path)
    except TypeError:
        return None
    with _CACHE_LOCK:
        return _BY_INPUT.get(raw) or _BY_INPUT.get(raw.strip())


def _pack_probe_from_dict(res: Dict[str, Any]) -> PackProbe:
    return PackProbe(
        kind=res.get("kind", KIND_UNKNOWN),
        confidence=float(res.get("confidence", 0.0)),
        suggested_pack_type=res.get("suggested_pack_type"),
        evidence=tuple(res.get("evidence", ())),
        details=dict(res.get("details", {})),
        error=res.get("error"),
        entry_count=int(res.get("entry_count", 0)),
    )


# ---------------------------------------------------------------------------
# Native Core Dispatch (No Python Fallback)
# ---------------------------------------------------------------------------


def _classify_dir(path: Path, probe: PackProbe) -> PackProbe:
    mtk = get_libmtk()
    if mtk is None:
        raise RuntimeError("libmtk native core is required for pack detection")
    res = mtk.probe_pack(str(path))
    return _pack_probe_from_dict(res)


def _classify_file(path: Path, probe: PackProbe) -> PackProbe:
    mtk = get_libmtk()
    if mtk is None:
        raise RuntimeError("libmtk native core is required for pack detection")
    res = mtk.probe_pack(str(path))
    return _pack_probe_from_dict(res)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_pack_kind(path: Any, *, use_cache: bool = True) -> PackProbe:
    """
    Classify a pack/JAR path using the native libmtk core.
    Never raises; failures surface as ``KIND_UNKNOWN`` + ``error``.
    """
    started = time.perf_counter()
    resolved = _resolve(path)
    if resolved is None:
        return PackProbe(error="invalid path")

    try:
        raw_path: Optional[str] = os.fspath(path) if isinstance(path, (str, os.PathLike)) else None
    except TypeError:
        raw_path = None

    key = _stat_key(resolved)
    if key is not None and use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return replace(
                cached,
                cached=True,
                details=dict(cached.details),
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
            )

    probe = PackProbe()
    try:
        if resolved.is_dir():
            probe = _classify_dir(resolved, probe)
        elif resolved.is_file():
            probe = _classify_file(resolved, probe)
        else:
            probe.error = "path does not exist"
    except Exception as exc:  # defensive: never break a Blender callback
        logger.warning("pack probe failed for %s: %s", resolved, exc, exc_info=True)
        probe = PackProbe(kind=KIND_UNKNOWN, error=f"{type(exc).__name__}: {exc}")

    probe.elapsed_ms = (time.perf_counter() - started) * 1000.0
    if key is not None and probe.error is None:
        _cache_put(key, probe, raw_path)
    return probe


def resolve_pack_type(current_pack_type: str, type_source: str, probe: Optional[PackProbe]) -> str:
    """
    Apply the auto-detection policy without touching Blender state.

    Manual choices always win; auto-detection only replaces the type when it produced a
    confident suggestion.
    """
    if type_source == TYPE_SOURCE_MANUAL:
        return current_pack_type
    if probe is None or not probe.suggested_pack_type:
        return current_pack_type
    return probe.suggested_pack_type


def _cache_get(key: Tuple[str, int, int]) -> Optional[PackProbe]:
    global _CACHE_HITS, _CACHE_MISSES
    with _CACHE_LOCK:
        probe = _CACHE.get(key)
        if probe is None:
            _CACHE_MISSES += 1
            return None
        _CACHE.move_to_end(key)
        _CACHE_HITS += 1
        return probe


def _cache_put(key: Tuple[str, int, int], probe: PackProbe, raw_path: Optional[str]) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = probe
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
        if raw_path is not None:
            _BY_INPUT[raw_path.strip()] = probe
            _BY_INPUT.move_to_end(raw_path.strip())
            while len(_BY_INPUT) > _CACHE_LIMIT * 2:
                _BY_INPUT.popitem(last=False)


__all__ = [
    "KIND_VANILLA_CLIENT",
    "KIND_VANILLA_SERVER",
    "KIND_MOD",
    "KIND_RESOURCE_PACK",
    "KIND_DATA_PACK",
    "KIND_MODPACK",
    "KIND_UNKNOWN",
    "ALL_KINDS",
    "KIND_LABELS",
    "KIND_TO_PACK_TYPE",
    "TEXTURE_SOURCE_KINDS",
    "VALID_BASE_PACK_KINDS",
    "TYPE_SOURCE_AUTO",
    "TYPE_SOURCE_MANUAL",
    "PackProbe",
    "detect_pack_kind",
    "resolve_pack_type",
    "invalidate_pack_probe",
    "peek_cached_probe",
    "pack_probe_cache_info",
]
