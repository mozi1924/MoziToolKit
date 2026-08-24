"""
Atlas Generator for Minecraft Resource Packs / JARs.
Generates size-bounded texture atlas images (Albedo, Normal, Specular) and mapping JSON.
"""

from __future__ import annotations

import sys
import os
import json
import zipfile
from pathlib import Path
from typing import Any

from .constants import (
    FACE_ORDER,
    ATLAS_FORMAT_VERSION,
    ATLAS_CATEGORY_PRIORITY,
    RECT_PACKED_CATEGORIES,
    classify_texture_category,
)
from .rect_packer import pack_category_textures
from .biome import BiomeResolver
from .pack_stack import ResourcePackStack, get_configured_pack_stack
from ..system.dependencies import has_pillow
from ..mc_baker import StateBaker, JarResourceLoader

try:
    from PIL import Image
    HAS_PIL = True
    Image.MAX_IMAGE_PIXELS = 128 * 1024 * 1024  # 128 MP max image pixels threshold
except ImportError:
    Image = None
    HAS_PIL = False

MAX_IMAGE_DIMENSION = 16384  # Max allowed width/height in pixels for a single texture


def _safe_open_image(source):
    """Read an image into memory and promptly release its source file handle.

    Resource packs commonly contain thousands of PNGs.  Keeping Pillow's
    source images open until garbage collection can exhaust file descriptors
    (especially when reading directly from a ZIP), which then surfaces as
    intermittent ``failed to load`` warnings on later replacements.
    """
    with Image.open(source) as img:
        if img.width > MAX_IMAGE_DIMENSION or img.height > MAX_IMAGE_DIMENSION:
            raise ValueError(
                f"Image dimensions ({img.width}x{img.height}) exceed safety limit ({MAX_IMAGE_DIMENSION}px)"
            )
        converted = img.convert("RGBA")
        converted.load()
        return converted


def _is_power_of_two(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def is_animated_texture(image, mcmeta: dict | None) -> bool:
    """
    Determine if a texture is truly animated based on its image dimensions and mcmeta metadata.
    """
    if not mcmeta or not isinstance(mcmeta, dict):
        return False
    anim = mcmeta.get("animation")
    if anim is None or not isinstance(anim, dict):
        return False

    if image is None:
        return True

    w, h = image.size
    frame_width = max(1, int(anim.get("width", w)))
    frame_height = max(1, int(anim.get("height", frame_width)))
    frame_count = max(1, h // frame_height) if frame_height > 0 else 1
    frames = anim.get("frames", [])

    return (frame_count > 1) or (isinstance(frames, list) and len(frames) > 1)


def analyze_texture_transparency(image: Any) -> dict[str, Any]:
    """
    Analyze the alpha channel of an image to classify its transparency.
    Returns:
        {
            "is_opaque": bool,        # True if alpha is 255 for all pixels
            "alpha_mode": str,        # "OPAQUE" | "CUTOUT" | "TRANSLUCENT"
            "min_alpha": int,         # 0..255
            "max_alpha": int,         # 0..255
        }
    """
    if image is None:
        return {
            "is_opaque": True,
            "alpha_mode": "OPAQUE",
            "min_alpha": 255,
            "max_alpha": 255,
        }
    try:
        alpha_channel = image.getchannel("A") if "A" in image.getbands() else None
        if alpha_channel is None:
            return {
                "is_opaque": True,
                "alpha_mode": "OPAQUE",
                "min_alpha": 255,
                "max_alpha": 255,
            }
        min_a, max_a = alpha_channel.getextrema()
        if min_a == 255:
            return {
                "is_opaque": True,
                "alpha_mode": "OPAQUE",
                "min_alpha": int(min_a),
                "max_alpha": int(max_a),
            }
        # Check for intermediate alpha (translucent) vs binary alpha (cutout)
        colors = alpha_channel.getcolors(maxcolors=256)
        if colors:
            alpha_vals = {val for count, val in colors}
            has_intermediate = any(0 < val < 255 for val in alpha_vals)
            alpha_mode = "TRANSLUCENT" if has_intermediate else "CUTOUT"
        else:
            alpha_mode = "TRANSLUCENT" if (min_a > 0 or max_a < 255) else "CUTOUT"

        return {
            "is_opaque": False,
            "alpha_mode": alpha_mode,
            "min_alpha": int(min_a),
            "max_alpha": int(max_a),
        }
    except Exception:
        return {
            "is_opaque": True,
            "alpha_mode": "OPAQUE",
            "min_alpha": 255,
            "max_alpha": 255,
        }


class AtlasGenerator:
    """
    Parses Minecraft block models and textures from a JAR archive, ZIP file, or directory.
    Constructs deduplicated, size-bounded atlas chunks:
    - Static textures are packed once each and referenced by every matching face.
    - Each animation owns independent vertical frame-strip chunk(s).
    - Different namespaces are strictly isolated into separate chunks.
    - Native resolution is determined per-namespace via statistical mode.
    """

    def __init__(
        self,
        resource_path: str | Path,
        default_tile_size: int = 16,
        max_chunk_size: int = 4096,
        fallback_stack: Optional[ResourcePackStack] = None,
        included_categories: Optional[set[str]] = None,
    ):
        self.resource_path = Path(resource_path)
        self.default_tile_size = default_tile_size
        self.max_chunk_size = max_chunk_size
        self.fallback_stack = fallback_stack
        # ``None`` preserves the full resource-pack behavior used for normal
        # mesh replacement.  Yefira world replacement supplies a focused set
        # so UI/particle atlases are never decoded or brought into Blender.
        self.included_categories = frozenset(included_categories) if included_categories else None

        self.static_textures = {}    # clean_stem -> Image
        self.animated_textures = {}  # clean_stem -> {image: Image, mcmeta: dict}
        self.normal_textures = {}    # clean_stem -> Image
        self.specular_textures = {}  # clean_stem -> Image
        self.models = {}             # model_name -> dict JSON

        # Grouped by namespace: namespace -> {stem: data}
        self.static_by_namespace = {}
        self.animated_by_namespace = {}
        self.normal_by_namespace = {}
        self.specular_by_namespace = {}

        # Multi-category partitioned mappings: namespace -> category -> {rel_path: data}
        self.static_by_ns_cat = {}
        self.animated_by_ns_cat = {}
        self.normal_by_ns_cat = {}
        self.specular_by_ns_cat = {}

        self.block_mappings = {}     # block_id -> 6 face texture names
        self.static_materials = []   # list of static material metadata
        self.animated_materials = [] # list of animated material metadata
        self.biome_resolver = BiomeResolver()

        self.baker: Optional[StateBaker] = None
        try:
            composite_loader = self.fallback_stack.get_composite_loader() if self.fallback_stack else None
            primary_loader = JarResourceLoader(self.resource_path, fallback_loader=composite_loader)
            self.baker = StateBaker(jar_path=None)
            self.baker.resource_loader = primary_loader
            self.baker.model_parser.model_loader_fn = primary_loader.load_model
            self.baker.state_resolver.blockstate_loader_fn = primary_loader.load_blockstate
        except Exception:
            self.baker = None

    def _includes_category(self, category: str) -> bool:
        return self.included_categories is None or category in self.included_categories

    def load_resources(self):
        """Load PNG images, mcmeta animation data, and models from source and fallback stack across all categories."""
        # Pillow 12 can defer decoder registration until its first open.  In
        # Blender 5.2 that first open may fail after mesh creation; eagerly
        # initialize plugins before touching a resource pack.
        Image.init()
        if not self.resource_path.exists():
            raise FileNotFoundError(f"Resource path not found: {self.resource_path}")

        if self.resource_path.is_dir():
            self._load_from_dir(self.resource_path)
        elif zipfile.is_zipfile(self.resource_path):
            self._load_from_zip(self.resource_path)
        else:
            raise ValueError(f"Unsupported resource format: {self.resource_path}")

        # Populate missing fallback textures and models from enabled packs/JARs in the stack
        if self.fallback_stack and self.fallback_stack.packs:
            for fallback_pack in self.fallback_stack.packs:
                try:
                    if (
                        (fallback_pack.zip_path and fallback_pack.zip_path.resolve() == self.resource_path.resolve())
                        or (fallback_pack.extract_dir and fallback_pack.extract_dir.resolve() == self.resource_path.resolve())
                    ):
                        continue
                except Exception:
                    pass
                self._load_fallback_from_pack(fallback_pack)

        self.biome_resolver.set_models(self.models)

    def _load_fallback_from_pack(self, pack: ZipResourcePack):
        """Populate missing textures and models across all categories from a lower-priority fallback pack."""
        # 1. Load models from all namespaces under assets/*/models/{block,item}
        if pack.extract_dir:
            assets_dir = pack.extract_dir / "assets"
            if assets_dir.exists():
                for ns_dir in assets_dir.iterdir():
                    if not ns_dir.is_dir():
                        continue
                    ns = ns_dir.name.lower().strip()
                    for model_type in ("block", "item"):
                        models_dir = ns_dir / "models" / model_type
                        if models_dir.exists():
                            for root, _, files in os.walk(models_dir):
                                for f in files:
                                    if f.endswith(".json"):
                                        rel_model = (Path(root) / f).relative_to(models_dir).with_suffix("").as_posix().lower()
                                        if ns == "minecraft":
                                            model_key = rel_model if model_type == "block" else f"item/{rel_model}"
                                        else:
                                            model_key = f"{ns}:{model_type}/{rel_model}"
                                        if model_key not in self.models:
                                            try:
                                                with open(Path(root) / f, "r", encoding="utf-8") as fp:
                                                    self.models[model_key] = json.load(fp)
                                            except Exception:
                                                pass

        # 2. Load textures across all categories from fallback pack
        for (ns, path_key), info in pack.texture_path_index.items():
            base_rel = path_key.strip("/")
            category = classify_texture_category(base_rel)
            if not self._includes_category(category):
                continue
            if base_rel.startswith("block/"):
                clean_name = self._texture_name(ns, base_rel.removeprefix("block/"))
                base_stem = base_rel.removeprefix("block/")
            else:
                clean_name = self._texture_name(ns, base_rel)
                base_stem = base_rel

            if (ns in self.static_by_ns_cat and category in self.static_by_ns_cat[ns] and base_rel in self.static_by_ns_cat[ns][category]) or \
               (ns in self.animated_by_ns_cat and category in self.animated_by_ns_cat[ns] and base_rel in self.animated_by_ns_cat[ns][category]):
                continue

            albedo_file = info.get("albedo")
            if not albedo_file or not Path(albedo_file).exists():
                continue

            try:
                img = _safe_open_image(albedo_file)
                mcmeta = info.get("albedo_mcmeta")
                if is_animated_texture(img, mcmeta):
                    anim_data = {"image": img, "mcmeta": mcmeta or {}}
                    self.animated_textures[clean_name] = anim_data
                    self.animated_by_namespace.setdefault(ns, {})[base_stem] = anim_data
                    self.animated_by_ns_cat.setdefault(ns, {}).setdefault(category, {})[base_rel] = anim_data
                else:
                    self.static_textures[clean_name] = img
                    self.static_by_namespace.setdefault(ns, {})[base_stem] = img
                    self.static_by_ns_cat.setdefault(ns, {}).setdefault(category, {})[base_rel] = img

                normal_file = info.get("normal")
                if normal_file and Path(normal_file).exists():
                    n_img = _safe_open_image(normal_file)
                    self.normal_textures[clean_name] = n_img
                    self.normal_by_namespace.setdefault(ns, {})[base_stem] = n_img
                    self.normal_by_ns_cat.setdefault(ns, {}).setdefault(category, {})[base_rel] = n_img

                specular_file = info.get("specular")
                if specular_file and Path(specular_file).exists():
                    s_img = _safe_open_image(specular_file)
                    self.specular_textures[clean_name] = s_img
                    self.specular_by_namespace.setdefault(ns, {})[base_stem] = s_img
                    self.specular_by_ns_cat.setdefault(ns, {}).setdefault(category, {})[base_rel] = s_img
            except Exception:
                pass

    @staticmethod
    def _texture_name(namespace: str, stem: str) -> str:
        """Keep legacy vanilla names while making non-vanilla names unique."""
        stem = stem.strip("/").lower()
        namespace = namespace.lower()
        return stem if namespace == "minecraft" else f"{namespace}:{stem}"

    @staticmethod
    def _source_texture_key(texture_name: str) -> str:
        """Return the canonical resource key represented by an atlas entry."""
        if ":" in texture_name:
            namespace, stem = texture_name.split(":", 1)
        else:
            namespace, stem = "minecraft", texture_name
        if "/" in stem:
            return f"{namespace}:{stem}"
        return f"{namespace}:block/{stem}"

    def _load_from_zip(self, zip_path: Path):
        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = zf.namelist()

            # 1. Index mcmetas across all textures
            mcmetas = {}
            for name in namelist:
                parts = Path(name).parts
                if len(parts) >= 4 and parts[0] == "assets" and parts[2] == "textures" and name.endswith(".png.mcmeta"):
                    ns = parts[1].lower().strip()
                    rel_path = "/".join(parts[3:])[:-11].strip()
                    stem = rel_path.split("/")[-1]
                    texture_name = self._texture_name(ns, stem)
                    try:
                        meta_obj = json.loads(zf.read(name).decode("utf-8"))
                        mcmetas[texture_name] = meta_obj
                        mcmetas[(ns, stem)] = meta_obj
                        mcmetas[(ns, rel_path)] = meta_obj
                        mcmetas[f"{ns}:{rel_path}"] = meta_obj
                    except Exception:
                        pass

            # 2. Load models (block and item)
            for name in namelist:
                parts = Path(name).parts
                if len(parts) >= 5 and parts[0] == "assets" and parts[2] == "models" and parts[3] in ("block", "item") and name.endswith(".json"):
                    ns = parts[1].lower().strip()
                    model_type = parts[3]
                    stem = "/".join(parts[4:])[:-5].strip().lower()
                    if ns == "minecraft":
                        model_key = stem if model_type == "block" else f"item/{stem}"
                    else:
                        model_key = f"{ns}:{model_type}/{stem}"
                    try:
                        model_data = json.loads(zf.read(name).decode("utf-8"))
                        self.models[model_key] = model_data
                    except Exception:
                        pass

            # 3. Load PNG textures across all categories
            for name in namelist:
                parts = Path(name).parts
                if len(parts) >= 4 and parts[0] == "assets" and parts[2] == "textures" and name.endswith(".png"):
                    ns = parts[1].lower().strip()
                    rel_path = "/".join(parts[3:])[:-4].strip()

                    channel = "albedo"
                    if rel_path.endswith("_n"):
                        base_rel = rel_path[:-2].strip()
                        channel = "normal"
                    elif rel_path.endswith("_s"):
                        base_rel = rel_path[:-2].strip()
                        channel = "specular"
                    else:
                        base_rel = rel_path
                        channel = "albedo"

                    category = classify_texture_category(base_rel)
                    if not self._includes_category(category):
                        continue
                    if base_rel.startswith("block/"):
                        clean_stem = self._texture_name(ns, base_rel.removeprefix("block/"))
                        base_stem = base_rel.removeprefix("block/")
                    else:
                        clean_stem = self._texture_name(ns, base_rel)
                        base_stem = base_rel

                    try:
                        with zf.open(name) as img_file:
                            img = _safe_open_image(img_file)
                            if channel == "normal":
                                self.normal_textures[clean_stem] = img
                                self.normal_by_namespace.setdefault(ns, {})[base_stem] = img
                                self.normal_by_ns_cat.setdefault(ns, {}).setdefault(category, {})[base_rel] = img
                            elif channel == "specular":
                                self.specular_textures[clean_stem] = img
                                self.specular_by_namespace.setdefault(ns, {})[base_stem] = img
                                self.specular_by_ns_cat.setdefault(ns, {}).setdefault(category, {})[base_rel] = img
                            else:
                                meta = (
                                    mcmetas.get((ns, base_rel))
                                    or mcmetas.get(f"{ns}:{base_rel}")
                                    or mcmetas.get((ns, base_stem))
                                    or mcmetas.get(clean_stem)
                                )
                                if is_animated_texture(img, meta):
                                    anim_data = {
                                        "image": img,
                                        "mcmeta": meta or {}
                                    }
                                    self.animated_textures[clean_stem] = anim_data
                                    self.animated_by_namespace.setdefault(ns, {})[base_stem] = anim_data
                                    self.animated_by_ns_cat.setdefault(ns, {}).setdefault(category, {})[base_rel] = anim_data
                                else:
                                    self.static_textures[clean_stem] = img
                                    self.static_by_namespace.setdefault(ns, {})[base_stem] = img
                                    self.static_by_ns_cat.setdefault(ns, {}).setdefault(category, {})[base_rel] = img
                    except Exception as e:
                        print(f"[AtlasGenerator] Warning: failed to load texture {name}: {e}")

    def _load_from_dir(self, dir_path: Path):
        # 1. Index mcmetas across all texture folders
        mcmetas = {}
        assets_dir = dir_path / "assets"
        if assets_dir.exists():
            for namespace_dir in assets_dir.iterdir():
                if not namespace_dir.is_dir():
                    continue
                ns = namespace_dir.name.lower().strip()
                textures_dir = namespace_dir / "textures"
                if not textures_dir.exists():
                    continue
                for root, _, files in os.walk(textures_dir):
                    for f in files:
                        if f.endswith(".png.mcmeta"):
                            rel_path = (Path(root) / f).relative_to(textures_dir).as_posix()[:-11].strip()
                            stem = rel_path.split("/")[-1]
                            mcmeta_path = Path(root) / f
                            try:
                                with open(mcmeta_path, "r", encoding="utf-8") as fp:
                                    meta_obj = json.load(fp)
                                    mcmetas[(ns, rel_path)] = meta_obj
                                    mcmetas[(ns, stem)] = meta_obj
                                    mcmetas[self._texture_name(ns, stem)] = meta_obj
                                    mcmetas[f"{ns}:{rel_path}"] = meta_obj
                            except Exception:
                                pass

        # 2. Load models (block and item)
        if assets_dir.exists():
            for namespace_dir in assets_dir.iterdir():
                if not namespace_dir.is_dir():
                    continue
                ns = namespace_dir.name.lower().strip()
                models_dir = namespace_dir / "models"
                if not models_dir.exists():
                    continue
                for model_type in ("block", "item"):
                    sub_models = models_dir / model_type
                    if sub_models.exists():
                        for root, _, files in os.walk(sub_models):
                            for f in files:
                                if f.endswith(".json"):
                                    stem = (Path(root) / f).relative_to(sub_models).with_suffix("").as_posix().lower().strip()
                                    if ns == "minecraft":
                                        model_key = stem if model_type == "block" else f"item/{stem}"
                                    else:
                                        model_key = f"{ns}:{model_type}/{stem}"
                                    try:
                                        with open(Path(root) / f, "r", encoding="utf-8") as fp:
                                            model_data = json.load(fp)
                                            self.models[model_key] = model_data
                                    except Exception:
                                        pass

        # 3. Load PNG textures across all categories
        if assets_dir.exists():
            for namespace_dir in assets_dir.iterdir():
                if not namespace_dir.is_dir():
                    continue
                ns = namespace_dir.name.lower().strip()
                textures_dir = namespace_dir / "textures"
                if not textures_dir.exists():
                    continue
                for root, _, files in os.walk(textures_dir):
                    for f in files:
                        if not f.endswith(".png"):
                            continue
                        rel_path = (Path(root) / f).relative_to(textures_dir).with_suffix("").as_posix().strip()

                        channel = "albedo"
                        if rel_path.endswith("_n"):
                            base_rel = rel_path[:-2].strip()
                            channel = "normal"
                        elif rel_path.endswith("_s"):
                            base_rel = rel_path[:-2].strip()
                            channel = "specular"
                        else:
                            base_rel = rel_path
                            channel = "albedo"

                        category = classify_texture_category(base_rel)
                        if not self._includes_category(category):
                            continue
                        if base_rel.startswith("block/"):
                            clean_stem = self._texture_name(ns, base_rel.removeprefix("block/"))
                            base_stem = base_rel.removeprefix("block/")
                        else:
                            clean_stem = self._texture_name(ns, base_rel)
                            base_stem = base_rel

                        img_path = Path(root) / f
                        try:
                            img = _safe_open_image(img_path)
                            if channel == "normal":
                                self.normal_textures[clean_stem] = img
                                self.normal_by_namespace.setdefault(ns, {})[base_stem] = img
                                self.normal_by_ns_cat.setdefault(ns, {}).setdefault(category, {})[base_rel] = img
                            elif channel == "specular":
                                self.specular_textures[clean_stem] = img
                                self.specular_by_namespace.setdefault(ns, {})[base_stem] = img
                                self.specular_by_ns_cat.setdefault(ns, {}).setdefault(category, {})[base_rel] = img
                            else:
                                meta = (
                                    mcmetas.get((ns, base_rel))
                                    or mcmetas.get(f"{ns}:{base_rel}")
                                    or mcmetas.get((ns, base_stem))
                                    or mcmetas.get(clean_stem)
                                )
                                if is_animated_texture(img, meta):
                                    anim_data = {
                                        "image": img,
                                        "mcmeta": meta or {}
                                    }
                                    self.animated_textures[clean_stem] = anim_data
                                    self.animated_by_namespace.setdefault(ns, {})[base_stem] = anim_data
                                    self.animated_by_ns_cat.setdefault(ns, {}).setdefault(category, {})[base_rel] = anim_data
                                else:
                                    self.static_textures[clean_stem] = img
                                    self.static_by_namespace.setdefault(ns, {})[base_stem] = img
                                    self.static_by_ns_cat.setdefault(ns, {}).setdefault(category, {})[base_rel] = img
                        except Exception as e:
                            print(f"[AtlasGenerator] Warning: failed to load {img_path}: {e}")

    def resolve_model_textures(self, model_name: str, depth: int = 0) -> dict:
        """Recursively resolve texture variables from block model JSONs."""
        if depth > 10 or model_name not in self.models:
            return {}
        m = self.models[model_name]
        res = {}

        parent = m.get("parent")
        if parent and isinstance(parent, str):
            parent_clean = parent.replace("minecraft:block/", "").replace("block/", "").lower()
            res.update(self.resolve_model_textures(parent_clean, depth + 1))

        texs = m.get("textures", {})
        if isinstance(texs, dict):
            for k, v in texs.items():
                if isinstance(v, str):
                    res[k] = v.replace("minecraft:block/", "").replace("block/", "").lower()
        return res

    @staticmethod
    def expand_variables(tex_dict: dict) -> dict:
        """Resolve #variable references in texture dictionary."""
        resolved = dict(tex_dict)
        for _ in range(5):
            changed = False
            for k, v in list(resolved.items()):
                if v.startswith("#"):
                    var_key = v[1:]
                    if var_key in resolved and not resolved[var_key].startswith("#"):
                        resolved[k] = resolved[var_key]
                        changed = True
            if not changed:
                break
        return resolved

    def get_6_faces_for_model(self, model_name: str) -> dict:
        """
        Map block model to 6 face sub-textures:
        +X (East), -X (West), +Y (Up), -Y (Down), +Z (South), -Z (North).
        """
        raw_texs = self.resolve_model_textures(model_name)
        exp = self.expand_variables(raw_texs)

        fallback = list(exp.values())[0] if exp else model_name
        east = exp.get("east") or exp.get("side") or exp.get("all") or fallback
        west = exp.get("west") or exp.get("side") or exp.get("all") or east
        up = exp.get("up") or exp.get("top") or exp.get("end") or exp.get("all") or east
        down = exp.get("down") or exp.get("bottom") or exp.get("end") or exp.get("all") or east
        south = exp.get("south") or exp.get("side") or exp.get("all") or east
        north = exp.get("north") or exp.get("side") or exp.get("front") or exp.get("all") or east

        return {
            "+X": east,
            "-X": west,
            "+Y": up,
            "-Y": down,
            "+Z": south,
            "-Z": north
        }

    def _find_static_image(self, key_or_stem: str, namespace: str = "minecraft", category: str = None) -> Optional[Any]:
        """Lookup a static texture image across ns/category dicts and fallback indexes."""
        if not key_or_stem:
            return None
        clean = key_or_stem.strip().lower()
        if ":" in clean:
            ns_part, clean = clean.split(":", 1)
            if not namespace or namespace == "minecraft":
                namespace = ns_part
        clean = clean.removesuffix(".png").strip("/")
        stem = clean.split("/")[-1]

        candidates = [
            clean,
            stem,
            f"block/{stem}",
            f"item/{stem}",
            f"entity/{stem}",
            f"particle/{stem}",
        ]
        if category:
            cat_clean = category.strip("/").lower()
            candidates.insert(0, f"{cat_clean}/{stem}")
            if cat_clean.endswith("s") and len(cat_clean) > 1:
                candidates.insert(1, f"{cat_clean[:-1]}/{stem}")

        # 1. Search in category map if provided
        if category and namespace in self.static_by_ns_cat:
            cat_map = self.static_by_ns_cat[namespace].get(category, {})
            for c in candidates:
                if c in cat_map:
                    return cat_map[c]

        # 2. Search in all categories of this namespace
        if namespace in self.static_by_ns_cat:
            for cat_k, cat_map in self.static_by_ns_cat[namespace].items():
                for c in candidates:
                    if c in cat_map:
                        return cat_map[c]

        # 3. Search in static_by_namespace
        if namespace in self.static_by_namespace:
            ns_map = self.static_by_namespace[namespace]
            for c in (stem, clean):
                if c in ns_map:
                    return ns_map[c]

        # 4. Search in global static_textures
        clean_name = self._texture_name(namespace, stem)
        if clean_name in self.static_textures:
            return self.static_textures[clean_name]

        return None

    def build_iter(self, output_dir: str | Path):
        """
        Build deduplicated, size-bounded atlas chunks partitioned strictly per namespace.
        Yields (fraction: float, message: str, outputs: Optional[dict]).
        """
        if not HAS_PIL:
            raise ImportError("Pillow library is required for AtlasGenerator. Please install it using 'pip install pillow'.")
        Image.init()
        from collections import Counter

        yield (0.05, "Reading textures and models from resource pack...", None)
        self.load_resources()
        yield (0.15, f"Loaded {len(self.static_textures)} static & {len(self.animated_textures)} animated textures", None)

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        all_namespaces = sorted(set(list(self.static_by_ns_cat.keys()) + list(self.animated_by_ns_cat.keys()) + list(self.static_by_namespace.keys()) + list(self.animated_by_namespace.keys())))
        if "minecraft" in all_namespaces:
            all_namespaces.remove("minecraft")
            all_namespaces.insert(0, "minecraft")

        chunks = []
        texture_locations = {}
        animations = []
        outputs = {"chunks": []}
        has_normal = bool(self.normal_textures) or any(bool(m) for ns_dict in self.normal_by_ns_cat.values() for m in ns_dict.values())
        has_specular = bool(self.specular_textures) or any(bool(m) for ns_dict in self.specular_by_ns_cat.values() for m in ns_dict.values())

        total_ns = max(1, len(all_namespaces))
        for ns_idx, ns in enumerate(all_namespaces):
            ns_progress_base = 0.20 + 0.60 * (ns_idx / total_ns)

            # Discover all active categories for this namespace in priority order
            active_categories = []
            for cat in ATLAS_CATEGORY_PRIORITY:
                if (ns in self.static_by_ns_cat and cat in self.static_by_ns_cat[ns] and self.static_by_ns_cat[ns][cat]) or \
                   (ns in self.animated_by_ns_cat and cat in self.animated_by_ns_cat[ns] and self.animated_by_ns_cat[ns][cat]):
                    active_categories.append(cat)

            extra_cats = sorted(set(
                list(self.static_by_ns_cat.get(ns, {}).keys()) + list(self.animated_by_ns_cat.get(ns, {}).keys())
            ) - set(ATLAS_CATEGORY_PRIORITY))
            active_categories.extend(extra_cats)

            for cat in active_categories:
                if not self._includes_category(cat):
                    continue
                static_map = self.static_by_ns_cat.get(ns, {}).get(cat, {})
                if static_map:
                    yield (ns_progress_base, f"Packing static atlas chunks for namespace '{ns}' [{cat}]...", None)
                    is_rect_packed = (cat in RECT_PACKED_CATEGORIES)

                    if is_rect_packed:
                        rect_items = [(rel_p, static_map[rel_p].width, static_map[rel_p].height) for rel_p in sorted(static_map.keys())]
                        packed_chunks = pack_category_textures(rect_items, max_chunk_size=self.max_chunk_size)

                        for chunk_w, chunk_h, placed_rects in packed_chunks:
                            chunk_id = len(chunks)
                            images = {
                                "albedo": Image.new("RGBA", (chunk_w, chunk_h), (0, 0, 0, 0)),
                            }
                            overlay_img_canvas = None
                            chunk_has_overlay = False
                            chunk_has_tint = False

                            if has_normal:
                                images["normal"] = Image.new("RGBA", (chunk_w, chunk_h), (128, 128, 255, 255))
                            if has_specular:
                                images["specular"] = Image.new("RGBA", (chunk_w, chunk_h), (0, 0, 0, 0))
                            files = {}

                            for texture_id, rect in enumerate(placed_rects):
                                rel_p = rect.key
                                source_albedo = static_map[rel_p]
                                images["albedo"].paste(source_albedo, (rect.x, rect.y))

                                if has_normal:
                                    norm_src = self.normal_by_ns_cat.get(ns, {}).get(cat, {}).get(rel_p)
                                    if norm_src is not None:
                                        if norm_src.size != (rect.width, rect.height):
                                            norm_src = norm_src.resize((rect.width, rect.height), Image.NEAREST)
                                        images["normal"].paste(norm_src, (rect.x, rect.y))

                                if has_specular:
                                    spec_src = self.specular_by_ns_cat.get(ns, {}).get(cat, {}).get(rel_p)
                                    if spec_src is not None:
                                        if spec_src.size != (rect.width, rect.height):
                                            spec_src = spec_src.resize((rect.width, rect.height), Image.NEAREST)
                                        images["specular"].paste(spec_src, (rect.x, rect.y))

                                stem = rel_p.split("/")[-1]
                                canonical_key = f"{ns}:{rel_p}"
                                tint_info = self.biome_resolver.get_tint_info(stem)
                                if tint_info.get("tint_type", 0) != 0 or tint_info.get("is_hardcoded") or tint_info.get("has_overlay"):
                                    chunk_has_tint = True
                                transparency = analyze_texture_transparency(source_albedo)

                                overlay_stem = tint_info.get("overlay_texture")
                                if overlay_stem:
                                    overlay_src = self._find_static_image(overlay_stem, namespace=ns, category=cat)
                                    if overlay_src is not None:
                                        if overlay_src.size != (rect.width, rect.height):
                                            overlay_src = overlay_src.resize((rect.width, rect.height), Image.NEAREST)
                                        if overlay_src.getbbox():
                                            if overlay_img_canvas is None:
                                                overlay_img_canvas = Image.new("RGBA", (chunk_w, chunk_h), (0, 0, 0, 0))
                                            overlay_img_canvas.paste(overlay_src, (rect.x, rect.y))
                                            chunk_has_overlay = True

                                loc_entry = {
                                    "texture_key": canonical_key,
                                    "category": cat,
                                    "namespace": ns,
                                    "chunk_id": chunk_id,
                                    "texture_id": texture_id,
                                    "packing": "rect",
                                    "pixel_x": rect.x,
                                    "pixel_y": rect.y,
                                    "rect_width": rect.width,
                                    "rect_height": rect.height,
                                    "frame_width": rect.width,
                                    "frame_height": rect.height,
                                    "tile_size": max(rect.width, rect.height),
                                    "kind": "static",
                                    "is_opaque": transparency["is_opaque"],
                                    "alpha_mode": transparency["alpha_mode"],
                                    "min_alpha": transparency["min_alpha"],
                                    "tile_column": 0,
                                    "tile_row": 0,
                                    "frame_count": 1,
                                    "frametime": 1,
                                    "interpolate": False,
                                    "has_overlay": tint_info["has_overlay"],
                                    "overlay_texture": tint_info["overlay_texture"],
                                    "tint_category": tint_info["tint_category"],
                                    "tint_type": tint_info["tint_type"],
                                    "default_tint_weight": tint_info["tint_weight"],
                                    "default_base_tint_weight": tint_info.get("base_tint_weight", 1.0),
                                    "default_overlay_tint_weight": tint_info.get("overlay_tint_weight", 1.0),
                                    "is_hardcoded": tint_info["is_hardcoded"],
                                    "hardcoded_color": tint_info["hardcoded_color"],
                                    "hardcoded_hex": tint_info["hardcoded_hex"],
                                }
                                texture_locations[canonical_key] = loc_entry
                                texture_locations[rel_p] = loc_entry
                                raw_key = self._texture_name(ns, rel_p.removeprefix("block/") if rel_p.startswith("block/") else rel_p)
                                texture_locations[raw_key] = loc_entry
                                if ns == "minecraft":
                                    texture_locations[f"minecraft:{rel_p}"] = loc_entry
                                    texture_locations.setdefault(f"minecraft:{stem}", loc_entry)
                                    texture_locations.setdefault(stem, loc_entry)
                                    if rel_p.startswith("item/"):
                                        texture_locations[f"item_{stem}"] = loc_entry
                                        texture_locations[f"minecraft:item_{stem}"] = loc_entry
                                    elif rel_p.startswith("block/"):
                                        texture_locations[stem] = loc_entry
                                        texture_locations[f"minecraft:{stem}"] = loc_entry
                                else:
                                    texture_locations[f"{ns}:{stem}"] = loc_entry
                                    if rel_p.startswith("item/"):
                                        texture_locations[f"{ns}:item_{stem}"] = loc_entry

                            if chunk_has_overlay and overlay_img_canvas is not None:
                                images["overlay"] = overlay_img_canvas

                            for channel, image in images.items():
                                filename = f"{cat}_chunk_{chunk_id:03d}_{channel}.png"
                                image.save(output_path / filename)
                                files[channel] = filename

                            chunks.append({
                                "chunk_id": chunk_id,
                                "category": cat,
                                "namespace": ns,
                                "kind": "static",
                                "width": chunk_w,
                                "height": chunk_h,
                                "tile_size": max((rect.width for rect in placed_rects), default=16),
                                "texture_count": len(placed_rects),
                                "packing": "rect_bin_pack",
                                "has_tint": chunk_has_tint,
                                "has_overlay": chunk_has_overlay,
                                "files": files,
                            })
                            outputs["chunks"].append(output_path / files["albedo"])
                    else:
                        # Uniform grid packing for uniform square identical tiles (e.g. standard blocks / items)
                        square_widths = [
                            image.width for image in static_map.values()
                            if image.width == image.height and _is_power_of_two(image.width)
                        ]
                        if square_widths:
                            counts = Counter(square_widths)
                            cat_tile_size = max(counts.keys(), key=lambda w: (counts[w], w))
                        else:
                            cat_tile_size = self.default_tile_size

                        if cat_tile_size > self.max_chunk_size:
                            raise ValueError(f"Tile size {cat_tile_size}px for category '{cat}' ({ns}) exceeds chunk limit {self.max_chunk_size}px.")

                        tiles_per_row = max(1, self.max_chunk_size // cat_tile_size)
                        capacity = max(1, tiles_per_row * tiles_per_row)
                        static_rel_paths = sorted(static_map.keys())

                        def tile_for(rel_p, channel, tile_sz=cat_tile_size, namespace_val=ns, category_val=cat):
                            if channel == "albedo":
                                source = self._find_static_image(rel_p, namespace=namespace_val, category=category_val)
                            elif channel == "normal":
                                norm_map = self.normal_by_ns_cat.get(namespace_val, {}).get(category_val, {})
                                source = norm_map.get(rel_p) or norm_map.get(f"{category_val}/{rel_p}") or norm_map.get(f"block/{rel_p}") or norm_map.get(rel_p.split("/")[-1])
                            elif channel == "specular":
                                spec_map = self.specular_by_ns_cat.get(namespace_val, {}).get(category_val, {})
                                source = spec_map.get(rel_p) or spec_map.get(f"{category_val}/{rel_p}") or spec_map.get(f"block/{rel_p}") or spec_map.get(rel_p.split("/")[-1])
                            else:
                                source = None

                            if source is None:
                                fill = (128, 128, 255, 255) if channel == "normal" else (0, 0, 0, 0)
                                return Image.new("RGBA", (tile_sz, tile_sz), fill)
                            if source.size == (tile_sz, tile_sz):
                                return source
                            return source.resize((tile_sz, tile_sz), Image.NEAREST)

                        for first in range(0, len(static_rel_paths), capacity):
                            names = static_rel_paths[first:first + capacity]
                            chunk_id = len(chunks)
                            rows = min(tiles_per_row, max(1, (len(names) + tiles_per_row - 1) // tiles_per_row))
                            width = min(self.max_chunk_size, tiles_per_row * cat_tile_size)
                            height = min(self.max_chunk_size, rows * cat_tile_size)

                            images = {
                                "albedo": Image.new("RGBA", (width, height), (0, 0, 0, 0)),
                            }
                            overlay_img_canvas = None
                            chunk_has_overlay = False
                            chunk_has_tint = False

                            if has_normal:
                                images["normal"] = Image.new("RGBA", (width, height), (128, 128, 255, 255))
                            if has_specular:
                                images["specular"] = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                            files = {}

                            for texture_id, rel_p in enumerate(names):
                                x = (texture_id % tiles_per_row) * cat_tile_size
                                y = (texture_id // tiles_per_row) * cat_tile_size
                                stem = rel_p.split("/")[-1]
                                canonical_key = f"{ns}:{rel_p}"
                                tint_info = self.biome_resolver.get_tint_info(stem)
                                if tint_info.get("tint_type", 0) != 0 or tint_info.get("is_hardcoded") or tint_info.get("has_overlay"):
                                    chunk_has_tint = True
                                transparency = analyze_texture_transparency(static_map.get(rel_p))
                                loc_entry = {
                                    "texture_key": canonical_key,
                                    "category": cat,
                                    "namespace": ns,
                                    "chunk_id": chunk_id,
                                    "texture_id": texture_id,
                                    "tile_column": texture_id % tiles_per_row,
                                    "tile_row": texture_id // tiles_per_row,
                                    "kind": "static",
                                    "is_opaque": transparency["is_opaque"],
                                    "alpha_mode": transparency["alpha_mode"],
                                    "min_alpha": transparency["min_alpha"],
                                    "tile_size": cat_tile_size,
                                    "frame_width": cat_tile_size,
                                    "frame_height": cat_tile_size,
                                    "frame_count": 1,
                                    "frametime": 1,
                                    "interpolate": False,
                                    "has_overlay": tint_info["has_overlay"],
                                    "overlay_texture": tint_info["overlay_texture"],
                                    "tint_category": tint_info["tint_category"],
                                    "tint_type": tint_info["tint_type"],
                                    "default_tint_weight": tint_info["tint_weight"],
                                    "default_base_tint_weight": tint_info.get("base_tint_weight", 1.0),
                                    "default_overlay_tint_weight": tint_info.get("overlay_tint_weight", 1.0),
                                    "is_hardcoded": tint_info["is_hardcoded"],
                                    "hardcoded_color": tint_info["hardcoded_color"],
                                    "hardcoded_hex": tint_info["hardcoded_hex"],
                                }
                                texture_locations[canonical_key] = loc_entry
                                texture_locations[rel_p] = loc_entry
                                raw_key = self._texture_name(ns, rel_p.removeprefix("block/") if rel_p.startswith("block/") else rel_p)
                                texture_locations[raw_key] = loc_entry
                                if ns == "minecraft":
                                    texture_locations[f"minecraft:{rel_p}"] = loc_entry
                                    texture_locations.setdefault(f"minecraft:{stem}", loc_entry)
                                    texture_locations.setdefault(stem, loc_entry)
                                    if rel_p.startswith("item/"):
                                        texture_locations[f"item_{stem}"] = loc_entry
                                        texture_locations[f"minecraft:item_{stem}"] = loc_entry
                                    elif rel_p.startswith("block/"):
                                        texture_locations[stem] = loc_entry
                                        texture_locations[f"minecraft:{stem}"] = loc_entry
                                else:
                                    texture_locations[f"{ns}:{stem}"] = loc_entry
                                    if rel_p.startswith("item/"):
                                        texture_locations[f"{ns}:item_{stem}"] = loc_entry

                                images["albedo"].paste(tile_for(rel_p, "albedo"), (x, y))
                                if has_normal:
                                    images["normal"].paste(tile_for(rel_p, "normal"), (x, y))
                                if has_specular:
                                    images["specular"].paste(tile_for(rel_p, "specular"), (x, y))

                                overlay_stem = tint_info.get("overlay_texture")
                                if overlay_stem:
                                    overlay_tile = tile_for(overlay_stem, "albedo")
                                    if overlay_tile.getbbox():
                                        if overlay_img_canvas is None:
                                            overlay_img_canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                                        overlay_img_canvas.paste(overlay_tile, (x, y))
                                        chunk_has_overlay = True

                            if chunk_has_overlay and overlay_img_canvas is not None:
                                images["overlay"] = overlay_img_canvas

                            for channel, image in images.items():
                                filename = f"{cat}_chunk_{chunk_id:03d}_{channel}.png"
                                image.save(output_path / filename)
                                files[channel] = filename

                            chunks.append({
                                "chunk_id": chunk_id,
                                "category": cat,
                                "namespace": ns,
                                "kind": "static",
                                "width": width,
                                "height": height,
                                "tile_size": cat_tile_size,
                                "tiles_per_row": tiles_per_row,
                                "texture_count": len(names),
                                "packing": "grid",
                                "has_tint": chunk_has_tint,
                                "has_overlay": chunk_has_overlay,
                                "files": files,
                            })
                            outputs["chunks"].append(output_path / files["albedo"])

                # Animated textures for (ns, cat)
                anim_map = self.animated_by_ns_cat.get(ns, {}).get(cat, {})
                if anim_map:
                    yield (ns_progress_base + 0.05, f"Packing animated strip chunks for namespace '{ns}' [{cat}]...", None)
                    animation_columns = []
                    for rel_p in sorted(anim_map.keys()):
                        source = anim_map[rel_p]
                        image = source["image"]
                        if image.width > self.max_chunk_size or image.height > self.max_chunk_size:
                            raise ValueError(
                                f"Animation '{ns}:{rel_p}' ({image.width}x{image.height}) exceeds "
                                f"the {self.max_chunk_size}px chunk limit and cannot be stored losslessly."
                            )
                        animation_columns.append((rel_p, image, source["mcmeta"].get("animation", {})))

                    def save_animation_chunk(columns, namespace_val=ns, category_val=cat):
                        chunk_id = len(chunks)
                        x_calc = 0
                        for _s, img, _m in columns:
                            tw = img.width
                            x_calc = ((x_calc + tw - 1) // tw) * tw
                            x_calc += tw
                        chunk_width = max(16, x_calc)
                        chunk_height = max(img.height for _s, img, _m in columns)
                        images = {
                            "albedo": Image.new("RGBA", (chunk_width, chunk_height), (0, 0, 0, 0)),
                        }
                        overlay_img_canvas = None
                        chunk_has_overlay = False
                        chunk_has_tint = False

                        if has_normal:
                            images["normal"] = Image.new("RGBA", (chunk_width, chunk_height), (128, 128, 255, 255))
                        if has_specular:
                            images["specular"] = Image.new("RGBA", (chunk_width, chunk_height), (0, 0, 0, 0))

                        x_offset = 0
                        for texture_id, (rel_p, image, metadata) in enumerate(columns):
                            target_w = image.width
                            target_h = image.height
                            x_offset = ((x_offset + target_w - 1) // target_w) * target_w

                            for channel, img_canvas in images.items():
                                if channel == "albedo":
                                    source_img = image
                                elif channel == "normal":
                                    source_img = self.normal_by_ns_cat.get(namespace_val, {}).get(category_val, {}).get(rel_p)
                                elif channel == "specular":
                                    source_img = self.specular_by_ns_cat.get(namespace_val, {}).get(category_val, {}).get(rel_p)
                                else:
                                    source_img = None

                                if source_img is not None:
                                    src_w, src_h = source_img.size
                                    if src_w != target_w:
                                        scale_ratio = target_w / src_w
                                        scaled_h = max(1, int(round(src_h * scale_ratio)))
                                        source_img = source_img.resize((target_w, scaled_h), Image.NEAREST)
                                        src_w, src_h = source_img.size

                                    if src_h >= target_h:
                                        img_canvas.paste(source_img.crop((0, 0, target_w, target_h)), (x_offset, 0))
                                    else:
                                        y = 0
                                        while y < target_h:
                                            h_chunk = min(src_h, target_h - y)
                                            if h_chunk < src_h:
                                                img_canvas.paste(source_img.crop((0, 0, target_w, h_chunk)), (x_offset, y))
                                            else:
                                                img_canvas.paste(source_img, (x_offset, y))
                                            y += src_h

                            frame_width = max(1, int(metadata.get("width", image.width)))
                            frame_height = max(1, int(metadata.get("height", frame_width)))
                            frame_count = max(1, image.height // frame_height)
                            frametime = max(1, int(metadata.get("frametime", 2)))
                            interpolate = bool(metadata.get("interpolate", False))
                            stem = rel_p.split("/")[-1]
                            canonical_key = f"{namespace_val}:{rel_p}"
                            tint_info = self.biome_resolver.get_tint_info(stem)
                            if tint_info.get("tint_type", 0) != 0 or tint_info.get("is_hardcoded") or tint_info.get("has_overlay"):
                                chunk_has_tint = True
                            transparency = analyze_texture_transparency(image)

                            anim_loc = {
                                "texture_key": canonical_key,
                                "category": category_val,
                                "namespace": namespace_val,
                                "chunk_id": chunk_id,
                                "texture_id": texture_id,
                                "kind": "animation",
                                "is_opaque": transparency["is_opaque"],
                                "alpha_mode": transparency["alpha_mode"],
                                "min_alpha": transparency["min_alpha"],
                                "pixel_x": x_offset,
                                "pixel_y": 0,
                                "preview_frame": 0,
                                "frame_width": frame_width,
                                "frame_height": frame_height,
                                "frame_count": frame_count,
                                "frametime": frametime,
                                "interpolate": interpolate,
                                "has_overlay": tint_info["has_overlay"],
                                "overlay_texture": tint_info["overlay_texture"],
                                "tint_category": tint_info["tint_category"],
                                "tint_type": tint_info["tint_type"],
                                "default_tint_weight": tint_info["tint_weight"],
                                "default_base_tint_weight": tint_info.get("base_tint_weight", 1.0),
                                "default_overlay_tint_weight": tint_info.get("overlay_tint_weight", 1.0),
                                "is_hardcoded": tint_info["is_hardcoded"],
                                "hardcoded_color": tint_info["hardcoded_color"],
                                "hardcoded_hex": tint_info["hardcoded_hex"],
                            }
                            texture_locations[canonical_key] = anim_loc
                            texture_locations[rel_p] = anim_loc
                            raw_name = self._texture_name(namespace_val, rel_p.removeprefix("block/") if rel_p.startswith("block/") else rel_p)
                            texture_locations[raw_name] = anim_loc
                            if namespace_val == "minecraft":
                                texture_locations[f"minecraft:{rel_p}"] = anim_loc
                                texture_locations.setdefault(f"minecraft:{stem}", anim_loc)
                                texture_locations.setdefault(stem, anim_loc)
                                if rel_p.startswith("item/"):
                                    texture_locations[f"item_{stem}"] = anim_loc
                                    texture_locations[f"minecraft:item_{stem}"] = anim_loc
                                elif rel_p.startswith("block/"):
                                    texture_locations[stem] = anim_loc
                                    texture_locations[f"minecraft:{stem}"] = anim_loc
                            else:
                                texture_locations[f"{namespace_val}:{stem}"] = anim_loc

                            animations.append({
                                "name": raw_name,
                                "texture_key": canonical_key,
                                "category": category_val,
                                "namespace": namespace_val,
                                "chunk_id": chunk_id,
                                "texture_id": texture_id,
                                "pixel_x": x_offset,
                                "frame_count": frame_count,
                                "frame_width": frame_width,
                                "frame_height": frame_height,
                                "frametime": frametime,
                                "interpolate": interpolate,
                                "preview_frame": 0,
                                "mcmeta": metadata,
                            })
                            x_offset += target_w

                        if chunk_has_overlay and overlay_img_canvas is not None:
                            images["overlay"] = overlay_img_canvas

                        files = {}
                        for channel, img_canvas in images.items():
                            filename = f"{category_val}_chunk_{chunk_id:03d}_{channel}.png"
                            img_canvas.save(output_path / filename)
                            files[channel] = filename

                        chunks.append({
                            "chunk_id": chunk_id,
                            "category": category_val,
                            "namespace": namespace_val,
                            "kind": "animation",
                            "width": chunk_width,
                            "height": chunk_height,
                            "texture_count": len(columns),
                            "packing": "vertical_columns",
                            "has_tint": chunk_has_tint,
                            "has_overlay": chunk_has_overlay,
                            "files": files,
                        })
                        outputs["chunks"].append(output_path / files["albedo"])

                    pending_columns, pending_width = [], 0
                    for column in animation_columns:
                        column_width = column[1].width
                        aligned_next_width = ((pending_width + column_width - 1) // column_width) * column_width + column_width
                        if pending_columns and aligned_next_width > self.max_chunk_size:
                            save_animation_chunk(pending_columns)
                            pending_columns, pending_width = [], 0
                            aligned_next_width = column_width
                        pending_columns.append(column)
                        pending_width = aligned_next_width
                    if pending_columns:
                        save_animation_chunk(pending_columns)

        yield (0.85, "Baking block models and custom UV definitions...", None)
        baked_states = {}
        if hasattr(self, "baker") and self.baker:
            try:
                baked_states = self.baker.bake_all_pack_states()
            except Exception as e:
                print(f"[AtlasGenerator] Warning: StateBaker bake_all_pack_states: {e}")

        dir_to_face_order = {"east": "+X", "west": "-X", "up": "+Y", "down": "-Y", "south": "+Z", "north": "-Z"}
        block_states_data = {}
        for state_key, baked_model in baked_states.items():
            faces_data = {}
            for dir_name, face_key in dir_to_face_order.items():
                baked_face = baked_model.get_face(dir_name)
                if not baked_face:
                    continue
                tex_full = baked_face.texture
                tex_stem = tex_full.split("/")[-1]
                loc = texture_locations.get(tex_full) or texture_locations.get(tex_stem) or texture_locations.get(f"minecraft:{tex_stem}") or texture_locations.get(f"minecraft:block/{tex_stem}")
                if isinstance(loc, dict):
                    entry = dict(loc)
                    entry["uv_rotation"] = float(baked_face.uv_rot)
                    entry["u_min"] = float(baked_face.uv_bounds[0])
                    entry["v_min"] = float(baked_face.uv_bounds[1])
                    entry["u_max"] = float(baked_face.uv_bounds[2])
                    entry["v_max"] = float(baked_face.uv_bounds[3])
                    entry["tint_index"] = int(baked_face.tint_index)
                    faces_data[face_key] = entry
            if faces_data:
                block_states_data[state_key] = {
                    "is_cube": baked_model.is_cube,
                    "is_opaque": baked_model.is_opaque,
                    "is_emissive": baked_model.is_emissive,
                    "faces": faces_data,
                }

        materials = []
        all_material_names = sorted(set(self.models) | set(self.static_textures) | set(self.animated_textures))
        for material_id, name in enumerate(all_material_names):
            baked_model = None
            if hasattr(self, "baker") and self.baker:
                try:
                    baked_model = self.baker.bake_block_state(name)
                except Exception:
                    pass

            faces_data = {}
            if baked_model:
                for dir_name, face_key in dir_to_face_order.items():
                    baked_face = baked_model.get_face(dir_name)
                    if baked_face:
                        tex_full = baked_face.texture
                        tex_stem = tex_full.split("/")[-1]
                        loc = texture_locations.get(tex_full) or texture_locations.get(tex_stem) or texture_locations.get(f"minecraft:{tex_stem}") or texture_locations.get(f"minecraft:block/{tex_stem}")
                        if isinstance(loc, dict):
                            entry = dict(loc)
                            entry["uv_rotation"] = float(baked_face.uv_rot)
                            entry["u_min"] = float(baked_face.uv_bounds[0])
                            entry["v_min"] = float(baked_face.uv_bounds[1])
                            entry["u_max"] = float(baked_face.uv_bounds[2])
                            entry["v_max"] = float(baked_face.uv_bounds[3])
                            entry["tint_index"] = int(baked_face.tint_index)
                            faces_data[face_key] = entry

            if not faces_data:
                faces = self.get_6_faces_for_model(name) if name in self.models else {face: name for face in FACE_ORDER}
                for face, texture_name in faces.items():
                    loc = texture_locations.get(texture_name)
                    if isinstance(loc, dict):
                        entry = dict(loc)
                        entry.setdefault("uv_rotation", 0.0)
                        entry.setdefault("u_min", 0.0)
                        entry.setdefault("v_min", 0.0)
                        entry.setdefault("u_max", 1.0)
                        entry.setdefault("v_max", 1.0)
                        faces_data[face] = entry
                    else:
                        faces_data[face] = None

            mat_is_opaque = all(
                entry.get("is_opaque", True) for entry in faces_data.values() if isinstance(entry, dict)
            ) if faces_data else True

            materials.append({
                "material_id": material_id,
                "name": name,
                "is_opaque": mat_is_opaque,
                "faces": faces_data,
            })

        # Determine base tile_size for mapping summary (preference to minecraft)
        mc_chunk = next((c for c in chunks if c.get("namespace") == "minecraft" and "tile_size" in c), None)
        primary_tile_size = mc_chunk["tile_size"] if mc_chunk else (chunks[0].get("tile_size", self.default_tile_size) if chunks else self.default_tile_size)

        mapping_data = {
            "format_version": ATLAS_FORMAT_VERSION,
            "provenance_schema_version": 1,
            "max_chunk_size": self.max_chunk_size,
            "tile_size": primary_tile_size,
            "face_order": list(FACE_ORDER),
            "chunks": chunks,
            "textures": texture_locations,
            "materials": materials,
            "block_states": block_states_data,
            "animations": animations,
            "static_texture_count": len(self.static_textures),
            "static_chunk_count": sum(chunk["kind"] == "static" for chunk in chunks),
            "animation_count": len(animations),
            "baked_states_count": len(block_states_data),
        }
        mapping_path = output_path / "atlas_mapping.json"
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        with open(mapping_path, "w", encoding="utf-8") as fp:
            json.dump(mapping_data, fp, indent=2)
        outputs["mapping"] = mapping_path

        yield (1.0, f"Atlas built: {len(chunks)} chunks, {len(animations)} animations", outputs)

    def build(self, output_dir: str | Path, progress_callback=None) -> dict:
        """Build deduplicated, size-bounded atlas chunks partitioned strictly per namespace."""
        final_outputs = None
        for frac, msg, res in self.build_iter(output_dir):
            if progress_callback:
                progress_callback(frac, msg)
            if res is not None:
                final_outputs = res
        return final_outputs or {}



if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate Minecraft Texture Atlas from Resource Pack / JAR.")
    parser.add_argument("resource_path", help="Path to resource pack ZIP/JAR or unpacked directory")
    parser.add_argument("-o", "--output", default="./dist_atlas", help="Output directory for generated atlas files")
    args = parser.parse_args()

    gen = AtlasGenerator(args.resource_path)
    gen.build(args.output)
