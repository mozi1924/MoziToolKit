"""
Resource pack extraction, indexing, caching, and .mcmeta parsing for Minecraft textures.
"""

import os
import zipfile
import hashlib
import json
import tempfile
from pathlib import Path
try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from .constants import DEFAULT_NAMESPACE


def get_cache_dir() -> Path:
    """
    Get the cache root directory in Blender's configured temporary directory.
    Fallback to OS tempdir if bpy.app.tempdir is unavailable or empty.
    """
    temp_dir = getattr(bpy.app, "tempdir", None) if (bpy and hasattr(bpy, "app")) else None
    if not temp_dir:
        temp_dir = tempfile.gettempdir()
    cache_root = Path(temp_dir) / "MoziToolKit_cache" / "resource_packs"
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root


def clear_resource_pack_cache() -> tuple[int, int]:
    """
    Clear all cached extracted resource packs and temporary atlas outputs in the cache directory.
    Returns (files_removed_count, bytes_freed).
    """
    import shutil
    cache_root = get_cache_dir()
    files_count = 0
    bytes_freed = 0
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
    return files_count, bytes_freed


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


def get_pack_hash(pack_path: Path | str) -> str:
    """
    Compute a deterministic provenance content hash for a resource pack.
    Produces identical hashes for identical content whether provided as a
    ZIP archive, a JAR archive, or an unpacked directory.
    """
    path = Path(pack_path)
    if not path.exists():
        raise FileNotFoundError(f"Resource pack path not found: {path}")

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
        return hasher.hexdigest()

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
        return hasher.hexdigest()
    else:
        raise ValueError(f"Resource pack must be a ZIP/JAR archive or directory: {path}")


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
        print(f"[MoziToolKit] Error reading mcmeta {mcmeta_path}: {e}")
        return None


class ZipResourcePack:
    """
    Manages extraction, caching, and indexing of a Minecraft Java Edition
    resource pack supplied as a ZIP/JAR archive or an unpacked directory.
    """

    def __init__(self, zip_path: str, use_cache: bool = True):
        self.zip_path = Path(zip_path)
        self.use_cache = use_cache
        self.extract_dir = None
        self.pack_hash = None
        self.texture_index = {}
        self.texture_path_index = {}
        self._load_pack()

    def _load_pack(self):
        if not self.zip_path.exists():
            raise FileNotFoundError(f"Resource pack not found: {self.zip_path}")

        # Compute content-based pack hash (identical for ZIP, JAR, or unpacked directory)
        self.pack_hash = get_pack_hash(self.zip_path)

        if self.zip_path.is_dir():
            # An unpacked development/resource-pack directory is already in
            # the form consumed by _build_index.  Do not copy or mutate it.
            self.extract_dir = self.zip_path
            self._build_index()
            return

        if not zipfile.is_zipfile(self.zip_path):
            raise ValueError(f"Resource pack must be a ZIP/JAR archive or directory: {self.zip_path}")

        cache_root = get_cache_dir()
        self.extract_dir = cache_root / self.pack_hash

        marker_file = self.extract_dir / ".extracted"
        if not (self.use_cache and marker_file.exists()):
            self.extract_dir.mkdir(parents=True, exist_ok=True)
            print(f"[MoziToolKit] Extracting resource pack to {self.extract_dir}")
            with zipfile.ZipFile(self.zip_path, 'r') as zf:
                zf.extractall(self.extract_dir)
            with open(marker_file, 'w', encoding='utf-8') as f:
                f.write("OK")

        self._build_index()

    def _build_index(self):
        """Index block, item, entity, and misc textures and their matching .mcmeta files."""
        self.texture_index = {}
        self.texture_path_index = {}
        
        assets_root = self.extract_dir / "assets"
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
                for fname in files:
                    if not fname.lower().endswith(".png"):
                        continue
                    
                    full_path = root_path / fname
                    rel_name = fname[:-4]  # Remove .png
                    texture_key = full_path.relative_to(textures_dir).with_suffix("").as_posix().lower()

                    # Determine channel type (_n, _s, or base albedo)
                    if rel_name.endswith("_n"):
                        base_stem = rel_name[:-2]
                        texture_key = texture_key[:-2]
                        channel = "normal"
                    elif rel_name.endswith("_s"):
                        base_stem = rel_name[:-2]
                        texture_key = texture_key[:-2]
                        channel = "specular"
                    else:
                        base_stem = rel_name
                        channel = "albedo"

                    base_stem = base_stem.lower()
                    index_key = (namespace, base_stem)
                    if index_key not in self.texture_index:
                        self.texture_index[index_key] = {
                            "namespace": namespace,
                            "texture_name": base_stem,
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

                    entry = self.texture_index[index_key]
                    entry[channel] = full_path
                    entry[f"{channel}_mcmeta"] = mcmeta_data
                    self.texture_path_index[(namespace, texture_key)] = entry

    def get_texture_info(self, base_name: str, namespace: str = DEFAULT_NAMESPACE) -> dict:
        """
        Query texture paths and mcmeta metadata for an exact texture base name.
        """
        if not base_name:
            return None
            
        clean_name = base_name.lower().replace(".png", "")
        # Remove duplicate index suffix like .001, .002
        if "." in clean_name and clean_name.rsplit(".", 1)[1].isdigit():
            clean_name = clean_name.rsplit(".", 1)[0]

        namespace = namespace.lower()
        return (
            self.texture_path_index.get((namespace, clean_name))
            or self.texture_index.get((namespace, clean_name))
        )
