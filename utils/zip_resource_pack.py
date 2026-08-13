import os
import zipfile
import hashlib
import json
import tempfile
from pathlib import Path
import bpy


def get_cache_dir() -> Path:
    """
    Get the cache root directory in Blender's configured temporary directory.
    Fallback to OS tempdir if bpy.app.tempdir is unavailable or empty.
    """
    temp_dir = getattr(bpy.app, "tempdir", None)
    if not temp_dir:
        temp_dir = tempfile.gettempdir()
    cache_root = Path(temp_dir) / "MoziToolKit_cache" / "resource_packs"
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root


def get_file_hash(filepath: str) -> str:
    """Compute MD5 hash of a file for cache key generation."""
    hasher = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_directory_hash(directory: Path) -> str:
    """Compute a stable provenance hash for an unpacked resource pack."""
    hasher = hashlib.md5()
    for filepath in sorted(path for path in directory.rglob("*") if path.is_file()):
        hasher.update(str(filepath.relative_to(directory)).encode("utf-8"))
        with open(filepath, "rb") as source:
            for chunk in iter(lambda: source.read(65536), b""):
                hasher.update(chunk)
    return hasher.hexdigest()


def parse_mcmeta(mcmeta_path: Path) -> dict:
    """Parse a .mcmeta JSON file into a standard animation dictionary."""
    if not mcmeta_path.exists():
        return None
    try:
        with open(mcmeta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            anim = data.get("animation", {})
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
        self._load_pack()

    def _load_pack(self):
        if not self.zip_path.exists():
            raise FileNotFoundError(f"Resource pack not found: {self.zip_path}")

        if self.zip_path.is_dir():
            # An unpacked development/resource-pack directory is already in
            # the form consumed by _build_index.  Do not copy or mutate it.
            self.pack_hash = get_directory_hash(self.zip_path)
            self.extract_dir = self.zip_path
            self._build_index()
            return

        if not zipfile.is_zipfile(self.zip_path):
            raise ValueError(f"Resource pack must be a ZIP/JAR archive or directory: {self.zip_path}")

        # This is provenance metadata as well as a cache key, so it must be
        # stable even when the caller opts out of cache reuse.
        self.pack_hash = get_file_hash(str(self.zip_path))
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

                    # Determine channel type (_n, _s, or base albedo)
                    if rel_name.endswith("_n"):
                        base_stem = rel_name[:-2]
                        channel = "normal"
                    elif rel_name.endswith("_s"):
                        base_stem = rel_name[:-2]
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

    def get_texture_info(self, base_name: str, namespace: str = "minecraft") -> dict:
        """
        Query texture paths and mcmeta metadata for an exact texture base name.

        Material replacement must be conservative: a name such as
        ``magma_block`` must not silently select ``magma`` just because one is
        a substring of the other.  The only normalization retained is removal
        of Blender's duplicate suffix (``.001``) and a file extension.
        """
        if not base_name:
            return None
            
        clean_name = base_name.lower().replace(".png", "")
        # Remove duplicate index suffix like .001, .002
        if "." in clean_name and clean_name.rsplit(".", 1)[1].isdigit():
            clean_name = clean_name.rsplit(".", 1)[0]

        return self.texture_index.get((namespace.lower(), clean_name))
