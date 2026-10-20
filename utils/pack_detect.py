"""
MoziToolKit Asset Source Classification (Content-Based Pack Probe).

Classifies a user-selected ``.jar`` / ``.zip`` archive (or an extracted assets folder) as a
Minecraft **vanilla client**, **vanilla server**, **mod** (Fabric / Quilt / Forge / NeoForge),
**resource pack**, **data pack**, or **modpack** by inspecting ZIP central-directory entry names
and a few tiny metadata payloads.

Design constraints (see ``docs/packs/pack_detection.md``):

* Pure host-side metadata logic: no ``bpy``, no ``libmtk_py``, no heavy compute. Safe to call
  from UI callbacks, configuration loaders, CLI tooling, and unit tests.
* ZIP archives are **never** fully decompressed. Only the central directory is parsed, plus at
  most ``META_LIMIT`` bytes per metadata file.
* Signatures are matched against **exact archive-root paths** (never substrings): vanilla client
  JARs legitimately contain ``data/minecraft/datapacks/*/pack.mcmeta`` and a root ``pack.png``.
* Evidence is scored instead of "first hit wins", because real archives overlap (a Forge
  universal JAR carries both ``META-INF/mods.toml`` and ``pack.mcmeta`` + ``assets/``).
* Results are memoized by ``(resolved path, size, mtime_ns)`` so repeated UI redraws and
  typing in the path field never re-open the archive.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import zipfile
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

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
TEXTURE_SOURCE_KINDS = frozenset({KIND_VANILLA_CLIENT, KIND_VANILLA_SERVER, KIND_MOD, KIND_RESOURCE_PACK})

TYPE_SOURCE_AUTO = "AUTO"
TYPE_SOURCE_MANUAL = "MANUAL"

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

#: Upper bound for any metadata payload we decode (pack.mcmeta / version.json / fabric.mod.json).
META_LIMIT = 64 * 1024

#: Minimum total evidence before a kind is reported at all.
MIN_SCORE = 15

#: Minimum score margin (relative to the winning kind) required to auto-apply a pack type.
MIN_CONFIDENCE = 0.15

_CACHE_LIMIT = 128

_METADATA_PROBES = (
    "pack.mcmeta",
    "version.json",
    "fabric.mod.json",
    "quilt.mod.json",
    "META-INF/mods.toml",
    "META-INF/neoforge.mods.toml",
)

_VANILLA_SIGNATURES = ("assets/.mcassetsroot", "data/.mcassetsroot")
_MOJANG_SIGNATURE_PREFIX = "META-INF/MOJANGCS."


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


class _Signals:
    """Accumulates weighted evidence for one kind of archive."""

    __slots__ = ("scores", "evidence")

    def __init__(self) -> None:
        self.scores: Dict[str, int] = {}
        self.evidence: List[str] = []

    def add(self, kind: str, weight: int, reason: str) -> None:
        self.scores[kind] = self.scores.get(kind, 0) + weight
        if weight > 0:
            self.evidence.append(f"{reason} (+{weight})")

    def rank(self) -> Tuple[str, int, int]:
        if not self.scores:
            return KIND_UNKNOWN, 0, 0
        ordered = sorted(self.scores.items(), key=lambda item: item[1], reverse=True)
        kind, top = ordered[0]
        second = ordered[1][1] if len(ordered) > 1 else 0
        return kind, top, second

    def score(self, kind: str) -> int:
        return self.scores.get(kind, 0)


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


# ---------------------------------------------------------------------------
# Metadata helpers (bounded reads, never raise)
# ---------------------------------------------------------------------------


def _read_metadata(zf: zipfile.ZipFile, name: str) -> Optional[bytes]:
    try:
        with zf.open(name) as fp:
            return fp.read(META_LIMIT)
    except (KeyError, RuntimeError, NotImplementedError, zipfile.BadZipFile, OSError, ValueError):
        return None


def _read_json(zf: zipfile.ZipFile, name: str) -> Optional[Dict[str, Any]]:
    raw = _read_metadata(zf, name)
    if not raw:
        return None
    try:
        parsed = json.loads(raw.decode("utf-8", "replace"))
    except (UnicodeDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _manifest_text(zf: zipfile.ZipFile) -> str:
    raw = _read_metadata(zf, "META-INF/MANIFEST.MF")
    if not raw:
        return ""
    return raw.decode("utf-8", "replace")


def _pack_metadata(details: Dict[str, Any], meta: Optional[Dict[str, Any]]) -> None:
    if not meta:
        return
    pack = meta.get("pack")
    if isinstance(pack, dict):
        details["pack_format"] = pack.get("pack_format")
        description = pack.get("description")
        if isinstance(description, str):
            details["description"] = description[:160]


# ---------------------------------------------------------------------------
# ZIP classification
# ---------------------------------------------------------------------------


def _strip_wrapper_root(nameset: Iterable[str]) -> Tuple[str, set]:
    """
    Detect archives whose payload lives under a single top-level folder.

    Re-zipping a pack folder is a common user mistake; Minecraft itself refuses such packs, but
    we still classify the payload so the UI can explain *why* it is unusable.
    """
    names = set(nameset)
    files = [name for name in names if name and not name.endswith("/")]
    if not files:
        return "", names
    if any("/" not in name for name in files):
        return "", names
    heads = {name.split("/", 1)[0] for name in files}
    if len(heads) != 1:
        return "", names
    head = next(iter(heads))
    prefix = f"{head}/"
    if not any(f"{prefix}{probe}" in names for probe in _METADATA_PROBES):
        return "", names
    stripped = {name[len(prefix):] for name in names if name.startswith(prefix)}
    return prefix, stripped


def _classify_zip(zf: zipfile.ZipFile, raw_names: Iterable[str], probe: PackProbe) -> PackProbe:
    prefix, names = _strip_wrapper_root(raw_names)
    probe.entry_count = len(names)
    if prefix:
        probe.details["archive_root"] = prefix.rstrip("/")

    if not names:
        probe.error = "archive is empty"
        return probe

    sig = _Signals()

    def has(name: str) -> bool:
        return name in names

    def has_prefix(prefix_path: str) -> bool:
        return any(name.startswith(prefix_path) for name in names)

    # ------------------------------------------------------------------
    # Vanilla client
    # ------------------------------------------------------------------
    if has("version.json"):
        sig.add(KIND_VANILLA_CLIENT, 30, "root version.json")
        version = _read_json(zf, "version.json") or {}
        for key in ("id", "name"):
            if isinstance(version.get(key), str):
                probe.details["mc_version"] = version[key]
                break
        if version.get("world_version") is not None:
            probe.details["world_version"] = version.get("world_version")

    has_client_main = has("net/minecraft/client/main/Main.class")
    has_client_class = has("net/minecraft/client/Minecraft.class")
    if has_client_main:
        sig.add(KIND_VANILLA_CLIENT, 30, "net/minecraft/client/main/Main.class")
    if has_client_class:
        sig.add(KIND_VANILLA_CLIENT, 20, "net/minecraft/client/Minecraft.class")
    if has("assets/.mcassetsroot"):
        sig.add(KIND_VANILLA_CLIENT, 25, "assets/.mcassetsroot")
    if has("data/.mcassetsroot"):
        sig.add(KIND_VANILLA_CLIENT, 10, "data/.mcassetsroot")
    if any(name.startswith(_MOJANG_SIGNATURE_PREFIX) for name in names):
        sig.add(KIND_VANILLA_CLIENT, 25, "META-INF/MOJANGCS.* signature")

    # ------------------------------------------------------------------
    # Vanilla server (bundler jar since 1.18)
    # ------------------------------------------------------------------
    if has("META-INF/versions.list") and has("META-INF/libraries.list"):
        sig.add(KIND_VANILLA_SERVER, 40, "server bundler manifests")
    if has("net/minecraft/bundler/Main.class"):
        sig.add(KIND_VANILLA_SERVER, 30, "net/minecraft/bundler/Main.class")
    # A modern client JAR also ships `net/minecraft/server/Main.class`, so this signature is
    # only meaningful when nothing else points at a client distribution.
    if has("net/minecraft/server/Main.class") and not (has_client_main or has_client_class or has("version.json")):
        sig.add(KIND_VANILLA_SERVER, 25, "net/minecraft/server/Main.class")

    # ------------------------------------------------------------------
    # Mod loaders
    # ------------------------------------------------------------------
    if has("fabric.mod.json"):
        sig.add(KIND_MOD, 40, "fabric.mod.json")
        meta = _read_json(zf, "fabric.mod.json") or {}
        if isinstance(meta.get("id"), str):
            probe.details["mod_id"] = meta["id"]
        if isinstance(meta.get("name"), str):
            probe.details["mod_name"] = meta["name"]
        if isinstance(meta.get("version"), str):
            probe.details["mod_version"] = meta["version"]
    if has("quilt.mod.json"):
        sig.add(KIND_MOD, 40, "quilt.mod.json")
    if has("META-INF/mods.toml"):
        sig.add(KIND_MOD, 40, "META-INF/mods.toml")
    if has("META-INF/neoforge.mods.toml"):
        sig.add(KIND_MOD, 40, "META-INF/neoforge.mods.toml")
    if any(name.startswith("META-INF/jars/") and name.endswith(".jar") for name in names):
        sig.add(KIND_MOD, 20, "META-INF/jars/*.jar (jar-in-jar)")
    if any(name.endswith(".mixins.json") and "/" not in name for name in names):
        sig.add(KIND_MOD, 15, "root mixin configuration")
    if has_prefix("META-INF/services/"):
        sig.add(KIND_MOD, 5, "META-INF/services")

    manifest = None
    if has("META-INF/MANIFEST.MF"):
        manifest = _manifest_text(zf)
        if "FMLModType" in manifest or "ModLoader" in manifest:
            sig.add(KIND_MOD, 30, "MANIFEST FMLModType")
        if "Main-Class: net.minecraft" in manifest:
            sig.add(KIND_VANILLA_CLIENT, 20, "MANIFEST Main-Class net.minecraft")

    # ------------------------------------------------------------------
    # Resource pack / data pack
    # ------------------------------------------------------------------
    has_pack_mcmeta = has("pack.mcmeta")
    has_assets = has_prefix("assets/")
    has_data = has_prefix("data/")
    has_classes = has_prefix("net/") and any(name.endswith(".class") for name in names)

    if has_pack_mcmeta:
        _pack_metadata(probe.details, _read_json(zf, "pack.mcmeta"))
        if has_assets:
            sig.add(KIND_RESOURCE_PACK, 35, "pack.mcmeta + assets/")
        elif has_data:
            sig.add(KIND_DATA_PACK, 35, "pack.mcmeta + data/ only")
        else:
            sig.add(KIND_RESOURCE_PACK, 10, "pack.mcmeta only")
    elif has_assets:
        sig.add(KIND_RESOURCE_PACK, 15, "assets/ without mod or vanilla markers")

    if has("pack.png") and not has_classes:
        sig.add(KIND_RESOURCE_PACK, 10, "root pack.png")
    if has("assets/minecraft/textures/") or has_prefix("assets/minecraft/textures/"):
        sig.add(KIND_RESOURCE_PACK, 5, "assets/minecraft/textures/")

    # ------------------------------------------------------------------
    # Modpacks (recognized, but not a texture source)
    # ------------------------------------------------------------------
    if has("modrinth.index.json"):
        sig.add(KIND_MODPACK, 40, "modrinth.index.json")
    if has("manifest.json") and has_prefix("overrides/"):
        sig.add(KIND_MODPACK, 40, "manifest.json + overrides/")

    # Third-party library jars: compiled classes but no pack/loader markers.
    if has_classes and not has_pack_mcmeta:
        sig.add(KIND_MOD, 5, "compiled classes")

    return _finalize(probe, sig)


# ---------------------------------------------------------------------------
# Directory classification (extracted packs / clients)
# ---------------------------------------------------------------------------


def _classify_dir(path: Path, probe: PackProbe) -> PackProbe:
    try:
        entries = {entry.name for entry in os.scandir(path)}
    except OSError as exc:
        probe.error = str(exc)
        return probe

    probe.entry_count = len(entries)
    sig = _Signals()

    def is_file(*parts: str) -> bool:
        return path.joinpath(*parts).is_file()

    def is_dir(*parts: str) -> bool:
        return path.joinpath(*parts).is_dir()

    is_client_dir = is_dir("net", "minecraft", "client")

    if is_file("version.json"):
        sig.add(KIND_VANILLA_CLIENT, 30, "version.json")
        if is_client_dir:
            sig.add(KIND_VANILLA_CLIENT, 30, "net/minecraft/client")
        try:
            version = json.loads(path.joinpath("version.json").read_text("utf-8", "replace")[:META_LIMIT])
            if isinstance(version, dict):
                for key in ("id", "name"):
                    if isinstance(version.get(key), str):
                        probe.details["mc_version"] = version[key]
                        break
        except (OSError, ValueError):
            pass

    if is_file("assets", ".mcassetsroot"):
        sig.add(KIND_VANILLA_CLIENT, 25, "assets/.mcassetsroot")
    if is_dir("net", "minecraft", "bundler") or (is_dir("net", "minecraft", "server") and not is_client_dir):
        sig.add(KIND_VANILLA_SERVER, 30, "net/minecraft/bundler|server")

    if is_file("fabric.mod.json"):
        sig.add(KIND_MOD, 40, "fabric.mod.json")
        try:
            meta = json.loads(path.joinpath("fabric.mod.json").read_text("utf-8", "replace")[:META_LIMIT])
            if isinstance(meta, dict):
                if isinstance(meta.get("id"), str):
                    probe.details["mod_id"] = meta["id"]
                if isinstance(meta.get("name"), str):
                    probe.details["mod_name"] = meta["name"]
        except (OSError, ValueError):
            pass
    if is_file("quilt.mod.json"):
        sig.add(KIND_MOD, 40, "quilt.mod.json")
    if is_file("META-INF", "mods.toml"):
        sig.add(KIND_MOD, 40, "META-INF/mods.toml")
    if is_file("META-INF", "neoforge.mods.toml"):
        sig.add(KIND_MOD, 40, "META-INF/neoforge.mods.toml")

    has_assets_dir = is_dir("assets")
    if is_file("pack.mcmeta"):
        try:
            meta = json.loads(path.joinpath("pack.mcmeta").read_text("utf-8", "replace")[:META_LIMIT])
            if isinstance(meta, dict):
                _pack_metadata(probe.details, meta)
        except (OSError, ValueError):
            pass
        if has_assets_dir:
            sig.add(KIND_RESOURCE_PACK, 35, "pack.mcmeta + assets/")
        elif is_dir("data"):
            sig.add(KIND_DATA_PACK, 35, "pack.mcmeta + data/ only")
        else:
            sig.add(KIND_RESOURCE_PACK, 10, "pack.mcmeta only")
    elif has_assets_dir:
        sig.add(KIND_RESOURCE_PACK, 15, "assets/")
    if is_file("pack.png"):
        sig.add(KIND_RESOURCE_PACK, 5, "pack.png")

    if is_file("modrinth.index.json"):
        sig.add(KIND_MODPACK, 40, "modrinth.index.json")

    return _finalize(probe, sig)


# ---------------------------------------------------------------------------
# Shared finalization
# ---------------------------------------------------------------------------


def _finalize(probe: PackProbe, sig: _Signals) -> PackProbe:
    kind, top, second = sig.rank()
    probe.evidence = tuple(sig.evidence)
    probe.details.setdefault("scores", dict(sig.scores))

    if top < MIN_SCORE:
        probe.kind = KIND_UNKNOWN
        probe.confidence = 0.0
        probe.suggested_pack_type = None
        return probe

    probe.kind = kind
    probe.confidence = 1.0 if top <= 0 else max(0.0, min(1.0, (top - second) / float(top)))
    suggestion = KIND_TO_PACK_TYPE.get(kind)
    if suggestion is None or probe.confidence < MIN_CONFIDENCE:
        probe.suggested_pack_type = None
    else:
        probe.suggested_pack_type = suggestion
    return probe


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_pack_kind(path: Any, *, use_cache: bool = True) -> PackProbe:
    """
    Classify a pack/JAR path. Never raises; failures surface as ``KIND_UNKNOWN`` + ``error``.
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


def _classify_file(path: Path, probe: PackProbe) -> PackProbe:
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError):
        probe.error = "not a readable zip/jar archive"
        return probe
    with archive:
        try:
            names = archive.namelist()
        except (zipfile.BadZipFile, OSError, ValueError):
            probe.error = "corrupt zip central directory"
            return probe
        return _classify_zip(archive, names, probe)


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
    "TYPE_SOURCE_AUTO",
    "TYPE_SOURCE_MANUAL",
    "PackProbe",
    "detect_pack_kind",
    "resolve_pack_type",
    "invalidate_pack_probe",
    "peek_cached_probe",
    "pack_probe_cache_info",
]
