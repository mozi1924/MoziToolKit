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
    Manages extraction, caching, and indexing of a Minecraft Java Edition Resource Pack (ZIP / JAR).
    """

    def __init__(self, zip_path: str, use_cache: bool = True):
        self.zip_path = Path(zip_path)
        self.use_cache = use_cache
        self.extract_dir = None
        self.texture_index = {}
        self._load_pack()

    def _load_pack(self):
        if not self.zip_path.exists():
            raise FileNotFoundError(f"Resource pack not found: {self.zip_path}")

        pack_hash = get_file_hash(str(self.zip_path)) if self.use_cache else "nocache"
        cache_root = get_cache_dir()
        self.extract_dir = cache_root / pack_hash

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
        
        # Candidate texture root directories inside extracted pack
        assets_dir = self.extract_dir / "assets" / "minecraft" / "textures"
        search_dirs = [
            assets_dir / "block",
            assets_dir / "item",
            assets_dir / "entity",
            assets_dir,
        ]

        # Scan all png files
        for sdir in search_dirs:
            if not sdir.exists():
                continue
            for root, _, files in os.walk(sdir):
                root_path = Path(root)
                for fname in files:
                    if not fname.endswith(".png"):
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

                    if base_stem not in self.texture_index:
                        self.texture_index[base_stem] = {
                            "albedo": None,
                            "albedo_mcmeta": None,
                            "normal": None,
                            "normal_mcmeta": None,
                            "specular": None,
                            "specular_mcmeta": None,
                        }

                    mcmeta_file = root_path / f"{fname}.mcmeta"
                    mcmeta_data = parse_mcmeta(mcmeta_file)

                    entry = self.texture_index[base_stem]
                    entry[channel] = full_path
                    entry[f"{channel}_mcmeta"] = mcmeta_data

    def get_texture_info(self, base_name: str) -> dict:
        """
        Query texture paths and mcmeta metadata for a given texture base name.
        Includes fallback fuzzy matching for block names (e.g. magma_block -> magma).
        """
        if not base_name:
            return None
            
        clean_name = base_name.lower().replace(".png", "")
        # Remove duplicate index suffix like .001, .002
        if "." in clean_name and clean_name.rsplit(".", 1)[1].isdigit():
            clean_name = clean_name.rsplit(".", 1)[0]

        if clean_name in self.texture_index:
            return self.texture_index[clean_name]

        # Clean common model suffixes (_all, _side, _end, _top, _bottom, _block, _texture)
        cleaned_stem = clean_name
        for s in ["_all", "_side", "_end", "_top", "_bottom", "_block", "_texture"]:
            cleaned_stem = cleaned_stem.replace(s, "")
            if cleaned_stem in self.texture_index:
                return self.texture_index[cleaned_stem]

        # Fallback: substring match against registered stems
        for stem, info in self.texture_index.items():
            if stem == clean_name or stem == cleaned_stem:
                return info
            if stem in clean_name or clean_name in stem:
                return info

        return None

