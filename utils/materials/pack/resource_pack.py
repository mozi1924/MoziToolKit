"""
Resource pack extraction, indexing, caching, and .mcmeta parsing for Minecraft textures.
"""

import logging
import os
import zipfile
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Optional, Union, Any, Tuple

logger = logging.getLogger("MoziToolKit.Materials.ResourcePack")

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from ..constants import DEFAULT_NAMESPACE


# Resource pack zip extraction security limits
MAX_ZIP_TOTAL_UNCOMPRESSED = 2 * 1024 * 1024 * 1024  # 2 GB maximum uncompressed size
MAX_ZIP_MEMBER_COUNT = 50_000                       # Maximum 50,000 files
MAX_ZIP_COMPRESSION_RATIO = 100.0                   # Max compression ratio for files > 1MB


def get_temp_extraction_dir() -> Path:
    """
    Get the system temporary extraction directory for unpacking ZIP/JAR resource packs.
    Used during preprocessing so raw uncompressed assets live in OS temp rather than user data.
    Supports MOZI_TEMP_DIR environment override for test sandboxing.
    """
    env_dir = os.environ.get("MOZI_TEMP_DIR")
    if env_dir:
        temp_root = Path(env_dir)
        if temp_root.name != "extracted":
            temp_root = temp_root / "extracted"
    else:
        temp_root = Path(tempfile.gettempdir()) / "MoziToolKit" / "extracted"

    temp_root.mkdir(parents=True, exist_ok=True)
    return temp_root


def get_cache_dir() -> Path:
    """
    Get the persistent data directory for MoziToolKit baked stack outputs.
    Stores only the final compiled Atlas texture sheets and atlas_mapping.json metadata for the active stack.
    Supports MOZI_CACHE_DIR environment override for test sandboxing.
    """
    env_dir = os.environ.get("MOZI_CACHE_DIR")
    if env_dir:
        cache_dir = Path(env_dir)
        if cache_dir.name != "baked_stack":
            cache_dir = cache_dir / "baked_stack"
    else:
        cache_dir = None
        if bpy and hasattr(bpy, "utils") and hasattr(bpy.utils, "user_resource"):
            try:
                cache_dir = Path(bpy.utils.user_resource("DATAFILES")) / "MoziToolKit" / "cache" / "baked_stack"
            except Exception:
                cache_dir = None

        if not cache_dir:
            cache_dir = Path.home() / ".config" / "blender" / "MoziToolKit" / "cache" / "baked_stack"

    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir




def clean_obsolete_stack_caches(current_stack_hash: Optional[str] = None) -> tuple[int, int]:
    """
    Remove previous baked stack compilations from persistent data storage,
    keeping only the current active stack hash to save disk space.
    Returns (directories_removed_count, bytes_freed).
    """
    import shutil
    cache_root = get_cache_dir()
    dirs_removed = 0
    bytes_freed = 0
    if not cache_root.exists():
        return 0, 0

    for item in list(cache_root.iterdir()):
        if item.is_dir():
            if current_stack_hash and item.name == current_stack_hash:
                continue
            for sub in item.rglob("*"):
                if sub.is_file():
                    try:
                        bytes_freed += sub.stat().st_size
                    except Exception:
                        pass
            try:
                shutil.rmtree(item, ignore_errors=True)
                dirs_removed += 1
            except Exception:
                pass
    get_cache_stats(force_refresh=True)
    return dirs_removed, bytes_freed


_cached_stats = None
_cached_stats_time = 0.0


def get_cache_stats(force_refresh: bool = False) -> dict:
    """
    Get summary statistics about the persistent cache directory.
    Cached for 60 seconds to avoid disk I/O bottleneck during UI redraw ticks.
    Returns dict with keys: 'path', 'files_count', 'total_size_bytes', 'size_formatted'.
    """
    global _cached_stats, _cached_stats_time
    import time
    now = time.time()
    if not force_refresh and _cached_stats is not None and (now - _cached_stats_time) < 60.0:
        return _cached_stats

    cache_root = get_cache_dir()
    files_count = 0
    total_size = 0
    if cache_root.exists():
        try:
            for root, _, files in os.walk(cache_root):
                files_count += len(files)
                for f in files:
                    try:
                        total_size += os.path.getsize(os.path.join(root, f))
                    except Exception:
                        pass
        except Exception:
            pass

    if total_size < 1024:
        size_str = f"{total_size} B"
    elif total_size < 1024 * 1024:
        size_str = f"{total_size / 1024:.1f} KB"
    elif total_size < 1024 * 1024 * 1024:
        size_str = f"{total_size / (1024 * 1024):.1f} MB"
    else:
        size_str = f"{total_size / (1024 * 1024 * 1024):.2f} GB"

    _cached_stats = {
        "path": cache_root,
        "files_count": files_count,
        "total_size_bytes": total_size,
        "size_formatted": size_str,
    }
    _cached_stats_time = now
    return _cached_stats


def clear_temp_extraction_cache() -> tuple[int, int]:
    """
    Clear all temporary extracted raw resource pack files in OS temp.
    Returns (files_removed_count, bytes_freed).
    """
    import shutil
    files_count = 0
    bytes_freed = 0
    temp_dir = get_temp_extraction_dir()
    if temp_dir.exists():
        for item in list(temp_dir.iterdir()):
            try:
                if item.is_dir():
                    for sub in item.rglob("*"):
                        if sub.is_file():
                            bytes_freed += sub.stat().st_size
                            files_count += 1
                    shutil.rmtree(item, ignore_errors=True)
                elif item.is_file():
                    bytes_freed += item.stat().st_size
                    files_count += 1
                    item.unlink(missing_ok=True)
            except Exception:
                pass
    return files_count, bytes_freed


def clear_baked_stack_cache() -> tuple[int, int]:
    """
    Clear all compiled baked stack atlas, model, and standalone caches in persistent storage.
    Returns (files_removed_count, bytes_freed).
    """
    import shutil
    files_count = 0
    bytes_freed = 0
    cache_root = get_cache_dir()
    if cache_root.exists():
        for item in list(cache_root.iterdir()):
            try:
                if item.is_dir():
                    for sub in item.rglob("*"):
                        if sub.is_file():
                            bytes_freed += sub.stat().st_size
                            files_count += 1
                    shutil.rmtree(item, ignore_errors=True)
                elif item.is_file():
                    bytes_freed += item.stat().st_size
                    files_count += 1
                    item.unlink(missing_ok=True)
            except Exception:
                pass
    get_cache_stats(force_refresh=True)
    return files_count, bytes_freed


def clear_resource_pack_cache() -> tuple[int, int]:
    """
    Clear all cached extracted resource packs and compiled atlas outputs in both persistent and temp directories.
    Invoked exclusively by explicit user action in Addon Preferences.
    Returns (files_removed_count, bytes_freed).
    """
    f1, b1 = clear_temp_extraction_cache()
    f2, b2 = clear_baked_stack_cache()
    return f1 + f2, b1 + b2


def get_file_hash(filepath: str) -> str:
    """Compute MD5 hash of a file for cache key generation."""
    hasher = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _is_ignored_path(rel_path: str) -> bool:
    """Check if a relative path should be excluded from resource pack hash calculation."""
    parts = rel_path.replace("\\", "/").strip("/").split("/")
    for part in parts:
        if part.startswith(".") or part in ("__MACOSX", "Thumbs.db", "desktop.ini"):
            return True
    return False


# In-memory cache for pack hashes keyed by (resolved_path, mtime_ns, size)
_PACK_HASH_CACHE: dict[tuple[str, int, int], str] = {}


def get_pack_hash(pack_path: Path | str) -> str:
    """
    Compute a deterministic provenance content hash for a resource pack.
    Produces identical hashes for identical content whether provided as a
    ZIP archive, a JAR archive, or an unpacked directory.
    Uses filesystem mtime and size caching to avoid redundant re-hashing.
    """
    path = Path(pack_path)
    if not path.exists():
        raise FileNotFoundError(f"Resource pack path not found: {path}")

    try:
        stat_info = path.stat()
        cache_key = (
            str(path.resolve()),
            stat_info.st_mtime_ns,
            stat_info.st_size if not path.is_dir() else 0,
        )
        if cache_key in _PACK_HASH_CACHE:
            return _PACK_HASH_CACHE[cache_key]
    except Exception:
        cache_key = None

    hasher = hashlib.md5()

    if path.is_dir():
        file_map = {}
        for filepath in path.rglob("*"):
            if not filepath.is_file():
                continue
            rel_path = filepath.relative_to(path).as_posix().strip("/")
            if _is_ignored_path(rel_path):
                continue
            file_map[rel_path] = filepath

        for rel_path in sorted(file_map.keys()):
            hasher.update(rel_path.encode("utf-8") + b"\0")
            fp = file_map[rel_path]
            with open(fp, "rb") as source:
                for chunk in iter(lambda: source.read(65536), b""):
                    hasher.update(chunk)
        result = hasher.hexdigest()

    elif zipfile.is_zipfile(path):
        file_map = {}
        with zipfile.ZipFile(path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                rel_path = info.filename.replace("\\", "/").strip("/")
                if _is_ignored_path(rel_path):
                    continue
                file_map[rel_path] = info

            for rel_path in sorted(file_map.keys()):
                hasher.update(rel_path.encode("utf-8") + b"\0")
                info = file_map[rel_path]
                with zf.open(info, "r") as source:
                    for chunk in iter(lambda: source.read(65536), b""):
                        hasher.update(chunk)
        result = hasher.hexdigest()
    else:
        raise ValueError(f"Resource pack must be a ZIP/JAR archive or directory: {path}")

    if cache_key is not None:
        _PACK_HASH_CACHE[cache_key] = result
    return result



def get_directory_hash(directory: Path) -> str:
    """Compute a stable provenance hash for an unpacked resource pack or archive path."""
    return get_pack_hash(directory)


def parse_mcmeta(mcmeta_path: Path) -> dict:
    """Parse a .mcmeta JSON file into a standard animation dictionary if animation metadata is present."""
    if not mcmeta_path.exists():
        return None
    try:
        with open(mcmeta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return None
            anim = data.get("animation")
            if anim is None or not isinstance(anim, dict):
                return None
            return {
                "frametime": anim.get("frametime", 1),
                "interpolate": anim.get("interpolate", False),
                "frames": anim.get("frames", []),
                "width": anim.get("width"),
                "height": anim.get("height")
            }
    except Exception as e:
        logger.error(f"Error reading mcmeta {mcmeta_path}: {e}")
        return None



def derive_texture_name(texture_key: str, base_stem: str = "") -> str:
    """Derive the human-readable texture/material name from a texture key.

    Preserves nested subfolders as hyphenated names for entity textures
    and other categories (e.g., "entity/bed/white" -> "bed-white",
    "entity/chest/normal" -> "chest-normal", "entity/signs/hanging/birch" -> "signs-hanging-birch"),
    while maintaining clean single names for standard block/item textures (e.g., "block/stone" -> "stone").
    """
    key = (texture_key or "").strip("/").lower()
    if not key:
        return (base_stem or "").lower()

    if "/" in key:
        category, rest = key.split("/", 1)
        if category in ("block", "item", "items", "painting", "colormap"):
            return rest.replace("/", "-")
        elif category == "entity":
            return rest.replace("/", "-")
        else:
            return rest.replace("/", "-")
    return key


def texture_category_priority(texture_key: str) -> int:
    """Return category priority for deterministic tie-breaking (lower = higher priority).

    1. block/
    2. item/ or items/
    3. entity/
    4. painting/
    5. particle/
    6. everything else
    """
    k = (texture_key or "").lower()
    if k.startswith("block/"):
        return 1
    if k.startswith("item/") or k.startswith("items/"):
        return 2
    if k.startswith("entity/"):
        return 3
    if k.startswith("painting/"):
        return 4
    if k.startswith("particle/") or k.startswith("particles/"):
        return 5
    return 6


class ZipResourcePack:
    """
    Manages extraction, caching, and indexing of a Minecraft Java Edition
    resource pack supplied as a ZIP/JAR archive or an unpacked directory.
    Supports lazy extraction so pack hashes and bake manifests can be inspected
    without unpacking archives to disk.
    """

    def __init__(self, zip_path: str, use_cache: bool = True, lazy: Optional[bool] = None):
        self.zip_path = Path(zip_path)
        self.use_cache = use_cache
        self.lazy = (use_cache if lazy is None else lazy)
        self._extract_dir = None
        self.pack_hash = None
        self._texture_index = None
        self._texture_path_index = None
        self._loaded = False
        self._load_pack_metadata()
        if not self.lazy:
            self.ensure_extracted()

    def _load_pack_metadata(self):
        if not self.zip_path.exists():
            raise FileNotFoundError(f"Resource pack not found: {self.zip_path}")

        # Compute content-based pack hash (identical for ZIP, JAR, or unpacked directory)
        self.pack_hash = get_pack_hash(self.zip_path)

        if self.zip_path.is_dir():
            self._extract_dir = self.zip_path
        elif zipfile.is_zipfile(self.zip_path):
            cache_root = get_temp_extraction_dir()
            self._extract_dir = cache_root / self.pack_hash
        else:
            raise ValueError(f"Resource pack must be a ZIP/JAR archive or directory: {self.zip_path}")

    @property
    def extract_dir(self) -> Path:
        self.ensure_extracted()
        return self._extract_dir

    @extract_dir.setter
    def extract_dir(self, value: Path):
        self._extract_dir = value

    @property
    def texture_index(self) -> dict:
        self.ensure_extracted()
        return self._texture_index if self._texture_index is not None else {}

    @texture_index.setter
    def texture_index(self, value: dict):
        self._texture_index = value

    @property
    def texture_path_index(self) -> dict:
        self.ensure_extracted()
        return self._texture_path_index if self._texture_path_index is not None else {}

    @texture_path_index.setter
    def texture_path_index(self, value: dict):
        self._texture_path_index = value

    def ensure_extracted(self) -> Path:
        """Ensure archive is safely unpacked to temp and texture indices are built in RAM."""
        if self._loaded:
            return self._extract_dir

        if self.zip_path.is_dir():
            self._extract_dir = self.zip_path
            self._build_index()
            self._loaded = True
            return self._extract_dir

        marker_file = self._extract_dir / ".extracted"
        if not (self.use_cache and marker_file.exists()):
            self._extract_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Extracting resource pack to {self._extract_dir}")
            with zipfile.ZipFile(self.zip_path, 'r') as zf:
                self._safe_extract(zf, self._extract_dir)
            with open(marker_file, 'w', encoding='utf-8') as f:
                f.write("OK")


        self._build_index()
        self._loaded = True
        return self._extract_dir

    @staticmethod
    def _safe_extract(zf: zipfile.ZipFile, target_dir: Path) -> None:
        """Safely extract all members from a zip archive, preventing zip-slip path traversal and zip bombs."""
        resolved_target = target_dir.resolve()
        total_uncompressed_bytes = 0
        member_count = 0

        for member in zf.infolist():
            member_count += 1
            if member_count > MAX_ZIP_MEMBER_COUNT:
                raise ValueError(
                    f"Malicious zip archive detected (too many entries): contains more than {MAX_ZIP_MEMBER_COUNT} files."
                )

            total_uncompressed_bytes += member.file_size
            if total_uncompressed_bytes > MAX_ZIP_TOTAL_UNCOMPRESSED:
                raise ValueError(
                    f"Malicious zip archive detected (zip bomb): uncompressed size exceeds {MAX_ZIP_TOTAL_UNCOMPRESSED // (1024 * 1024)} MB."
                )

            if member.file_size > 1024 * 1024 and member.compress_size > 0:
                ratio = member.file_size / member.compress_size
                if ratio > MAX_ZIP_COMPRESSION_RATIO:
                    raise ValueError(
                        f"Malicious zip archive entry detected (excessive compression ratio {ratio:.1f}x > {MAX_ZIP_COMPRESSION_RATIO}x): '{member.filename}'"
                    )

            member_path = (target_dir / member.filename).resolve()
            try:
                member_path.relative_to(resolved_target)
            except ValueError:
                raise ValueError(
                    f"Malicious zip archive entry detected (zip-slip path traversal): '{member.filename}'"
                )
        zf.extractall(target_dir)

    def _build_index(self):
        """Index block, item, entity, and misc textures and their matching .mcmeta files."""
        self._texture_index = {}
        self._texture_path_index = {}
        
        if not self._extract_dir:
            return

        assets_root = self._extract_dir / "assets"
        if not assets_root.exists():
            return

        # Every namespace under assets is indexed.  Vanilla packs use
        # ``minecraft``; mod and add-on packs use their own namespace.
        for namespace_dir in assets_root.iterdir():
            textures_dir = namespace_dir / "textures"
            if not namespace_dir.is_dir() or not textures_dir.is_dir():
                continue
            namespace = namespace_dir.name.lower()
            for root, _, files in os.walk(textures_dir):
                root_path = Path(root)
                for fname in sorted(files):
                    if not fname.lower().endswith(".png"):
                        continue
                    
                    full_path = root_path / fname
                    rel_name = fname[:-4].strip()  # Remove .png
                    texture_key = full_path.relative_to(textures_dir).with_suffix("").as_posix().lower().strip()

                    # Determine channel type (_n, _s, or base albedo)
                    # Resource locations are case-sensitive, but a few PBR packs
                    # use an upper-case channel suffix (``_N`` / ``_S``).  The
                    # suffix is metadata, rather than part of the texture name,
                    # so classify it case-insensitively.  Without this, an _N-only
                    # overlay pack creates a separate albedo entry and can mask
                    # the real albedo provided by a lower stack layer.
                    rel_name_lower = rel_name.lower()
                    if rel_name_lower.endswith("_n"):
                        base_stem = rel_name[:-2].strip()
                        texture_key = texture_key[:-2].strip()
                        channel = "normal"
                    elif rel_name_lower.endswith("_s"):
                        base_stem = rel_name[:-2].strip()
                        texture_key = texture_key[:-2].strip()
                        channel = "specular"
                    else:
                        base_stem = rel_name
                        channel = "albedo"

                    base_stem = base_stem.lower()
                    texture_name = derive_texture_name(texture_key, base_stem)
                    path_index_key = (namespace, texture_key)
                    if path_index_key not in self._texture_path_index:
                        self._texture_path_index[path_index_key] = {
                            "namespace": namespace,
                            "texture_name": texture_name,
                            # Canonical resource location survives same-name
                            # textures in block/item/entity folders.  Keep
                            # texture_name as a legacy lookup/display alias.
                            "texture_key": texture_key,
                            "albedo": None,
                            "albedo_mcmeta": None,
                            "normal": None,
                            "normal_mcmeta": None,
                            "specular": None,
                            "specular_mcmeta": None,
                        }

                    mcmeta_file = root_path / f"{fname}.mcmeta"
                    mcmeta_data = parse_mcmeta(mcmeta_file)

                    entry = self._texture_path_index[path_index_key]
                    entry[channel] = full_path
                    entry[f"{channel}_mcmeta"] = mcmeta_data

                    # Primary index by derived texture_name (e.g. "bed-white", "chest-normal", "stone")
                    self._texture_index[(namespace, texture_name)] = entry
                    if "-" in texture_name:
                        self._texture_index[(namespace, texture_name.replace("-", "/"))] = entry

                    # Fallback short stem index with deterministic category priority
                    stem_index_key = (namespace, base_stem)
                    existing_entry = self._texture_index.get(stem_index_key)
                    if existing_entry is None:
                        self._texture_index[stem_index_key] = entry
                    else:
                        new_pri = texture_category_priority(texture_key)
                        old_pri = texture_category_priority(existing_entry.get("texture_key", ""))
                        if new_pri < old_pri:
                            self._texture_index[stem_index_key] = entry

    def get_texture_info(self, base_name: str, namespace: str = DEFAULT_NAMESPACE) -> dict | None:
        """
        Query texture paths and mcmeta metadata for an exact texture base name.
        """
        if not base_name:
            return None
            
        clean_name = base_name.lower().replace(".png", "")
        # Remove duplicate index suffix like .001, .002
        if "." in clean_name and clean_name.rsplit(".", 1)[1].isdigit():
            clean_name = clean_name.rsplit(".", 1)[0]

        if ":" in clean_name:
            ns_part, clean_name = clean_name.split(":", 1)
            if ns_part:
                namespace = ns_part
        elif "/" in clean_name and not clean_name.startswith("//"):
            parts = clean_name.split("/", 1)
            known_namespaces = {ns for ns, _ in self.texture_path_index.keys()}
            if parts[0] in known_namespaces:
                namespace = parts[0]
                clean_name = parts[1]

        namespace = (namespace or DEFAULT_NAMESPACE).lower()
        res = (
            self.texture_path_index.get((namespace, clean_name))
            or self.texture_index.get((namespace, clean_name))
        )
        if res is not None:
            return res

        # Try alternate hyphen / slash representations (e.g. 'bed-white' <-> 'bed/white', 'entity/bed-white' <-> 'entity/bed/white')
        if "-" in clean_name:
            slash_candidate = clean_name.replace("-", "/")
            res = (
                self.texture_path_index.get((namespace, slash_candidate))
                or self.texture_index.get((namespace, slash_candidate))
            )
            if res is not None:
                return res
        if "/" in clean_name:
            hyphen_candidate = clean_name.replace("/", "-")
            res = (
                self.texture_path_index.get((namespace, hyphen_candidate))
                or self.texture_index.get((namespace, hyphen_candidate))
            )
            if res is not None:
                return res

        # Suffix matching within the same namespace (e.g. 'signs/jungle' -> 'entity/signs/jungle', 'bed/red' -> 'entity/bed/red')
        if "/" in clean_name:
            suffix_matches = [
                info for (ns, path_key), info in self.texture_path_index.items()
                if ns == namespace and (path_key == clean_name or path_key.endswith("/" + clean_name))
            ]
            if suffix_matches:
                suffix_matches.sort(key=lambda inf: texture_category_priority(inf.get("texture_key", "")))
                return suffix_matches[0]

        # Suffix matching with hyphenated candidate
        if "-" in clean_name:
            slash_cand = clean_name.replace("-", "/")
            suffix_matches = [
                info for (ns, path_key), info in self.texture_path_index.items()
                if ns == namespace and (path_key == slash_cand or path_key.endswith("/" + slash_cand))
            ]
            if suffix_matches:
                suffix_matches.sort(key=lambda inf: texture_category_priority(inf.get("texture_key", "")))
                return suffix_matches[0]

        # Fallback: If not found under default namespace, check if texture exists in another loaded namespace
        if namespace == DEFAULT_NAMESPACE:
            matches = [
                info for (ns, key), info in self.texture_index.items()
                if key == clean_name or (isinstance(key, str) and "-" in clean_name and key == clean_name.replace("-", "/"))
            ]
            if not matches:
                matches = [
                    info for (ns, path_key), info in self.texture_path_index.items()
                    if path_key == clean_name or path_key.endswith("/" + clean_name)
                    or ("-" in clean_name and (path_key == clean_name.replace("-", "/") or path_key.endswith("/" + clean_name.replace("-", "/"))))
                ]
            if matches:
                matches.sort(key=lambda inf: texture_category_priority(inf.get("texture_key", "")))
                return matches[0]

        return None

