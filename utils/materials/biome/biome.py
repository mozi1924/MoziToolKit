"""
Minecraft Biome Definitions, Tint Classification, and Block Model JSON Resolver.
Powered by LibMTK high-performance pure-Rust backend.
"""

from __future__ import annotations

from typing import Optional, Dict, Any, Tuple, List, Union
import libmtk_py as mtk

# --- Color Conversion Utilities ---

def hex_to_rgb(hex_str: str) -> tuple[float, float, float]:
    """Convert hex color string (e.g. '#91BD59' or '91BD59') to sRGB float tuple (0..1)."""
    clean = hex_str.strip().lstrip("#")
    if len(clean) in (6, 8):
        r = int(clean[0:2], 16) / 255.0
        g = int(clean[2:4], 16) / 255.0
        b = int(clean[4:6], 16) / 255.0
        return (r, g, b)
    return (1.0, 1.0, 1.0)


def srgb_to_linear(c: float) -> float:
    """Convert sRGB component (0..1) to Linear RGB component."""
    return mtk.srgb_to_linear(float(c))


def linear_to_srgb(c: float) -> float:
    """Convert Linear RGB component (0..1) to standard sRGB component."""
    return mtk.linear_to_srgb(float(c))


def hex_to_linear_rgb(hex_str: str) -> tuple[float, float, float]:
    """Convert hex color string to Linear RGB float tuple for Blender shaders."""
    lin = mtk.hex_to_linear_rgba(hex_str, 1.0)
    return (lin[0], lin[1], lin[2])


def hex_to_rgba(hex_str: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    """Convert hex color string to sRGB RGBA tuple."""
    clean = hex_str.strip().lstrip("#")
    if len(clean) == 8:
        r = int(clean[0:2], 16) / 255.0
        g = int(clean[2:4], 16) / 255.0
        b = int(clean[4:6], 16) / 255.0
        a = int(clean[6:8], 16) / 255.0
        return (r, g, b, a)
    r, g, b = hex_to_rgb(hex_str)
    return (r, g, b, alpha)


def hex_to_linear_rgba(hex_str: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    """Convert hex color string to Linear RGBA tuple for Blender shaders."""
    lin = mtk.hex_to_linear_rgba(hex_str, float(alpha))
    return tuple(lin)


def linear_rgba_to_hex(r: Union[float, Sequence[float]], g: float = 0.0, b: float = 0.0, a: float = 1.0) -> str:
    """Convert Linear RGBA float tuple or components back to hex string."""
    if isinstance(r, (tuple, list)):
        vals = list(r)
        rf = float(vals[0]) if len(vals) > 0 else 0.0
        gf = float(vals[1]) if len(vals) > 1 else 0.0
        bf = float(vals[2]) if len(vals) > 2 else 0.0
        af = float(vals[3]) if len(vals) > 3 else 1.0
        return mtk.linear_rgba_to_hex(rf, gf, bf, af)
    return mtk.linear_rgba_to_hex(float(r), float(g), float(b), float(a))


def get_colormap_uv(temperature: float, downfall: float) -> tuple[float, float]:
    """Convert temperature and downfall into [0, 1] UV for Minecraft colormap textures."""
    uv = mtk.get_colormap_uv(float(temperature), float(downfall))
    return (uv[0], uv[1])


def sample_colormap_pixel(
    colormap_img: Any,
    temperature: float,
    downfall: float,
    default_color: tuple[float, float, float] = (0.57, 0.74, 0.35),
) -> tuple[float, float, float]:
    """Sample an sRGB color (0..1) from a 256x256 colormap Image."""
    t = max(0.0, min(1.0, float(temperature)))
    d = max(0.0, min(1.0, float(downfall))) * t
    if colormap_img is None:
        return default_color
    try:
        w, h = colormap_img.size
        x = int((1.0 - t) * (w - 1))
        y = int((1.0 - d) * (h - 1))
        x = max(0, min(w - 1, x))
        y = max(0, min(h - 1, y))
        pixel = colormap_img.getpixel((x, y))
        return (pixel[0] / 255.0, pixel[1] / 255.0, pixel[2] / 255.0)
    except Exception:
        return default_color


def blend_biome_colors(
    colors_with_weights: list[tuple[Union[str, dict[str, Any]], float]],
    tint_type: str = "grass",
) -> tuple[float, float, float, float]:
    """Compute a smooth blended Linear RGBA color across multiple weighted biomes."""
    if not colors_with_weights:
        return (1.0, 1.0, 1.0, 1.0)

    total_weight = sum(w for _, w in colors_with_weights)
    if total_weight <= 0:
        return (1.0, 1.0, 1.0, 1.0)

    key_map = {
        "grass": "grass_linear",
        "foliage": "foliage_linear",
        "dry_foliage": "dry_foliage_linear",
        "water": "water_linear",
    }
    col_key = key_map.get(tint_type.lower(), "grass_linear")

    r_acc, g_acc, b_acc, a_acc = 0.0, 0.0, 0.0, 1.0
    for biome_entry, weight in colors_with_weights:
        if weight <= 0.0:
            continue
        norm_w = weight / total_weight
        if isinstance(biome_entry, dict):
            if col_key in biome_entry:
                col = biome_entry[col_key]
            else:
                hex_str = biome_entry.get(tint_type.lower()) or biome_entry.get("grass") or "#91BD59"
                col = hex_to_linear_rgba(hex_str)
        else:
            colors = get_biome_colors(str(biome_entry))
            col = colors.get(col_key, (1.0, 1.0, 1.0, 1.0))

        r_acc += col[0] * norm_w
        g_acc += col[1] * norm_w
        b_acc += col[2] * norm_w
        if len(col) > 3:
            a_acc = col[3]

    return (r_acc, g_acc, b_acc, a_acc)


# --- Biome Preset Registry ---

def _build_biome_palettes_registry() -> dict[str, dict[str, Any]]:
    baked_map = mtk.bake_all_biome_palettes()
    res = {}
    for biome_id, colors in baked_map.items():
        key = biome_id.upper()
        res[key] = {
            "name": colors.name,
            "grass": colors.grass_hex,
            "foliage": colors.foliage_hex,
            "dry_foliage": colors.dry_foliage_hex,
            "water": colors.water_hex,
            "temperature": colors.temperature,
            "humidity": colors.humidity,
            "modifier": colors.modifier,
            "has_custom_grass": colors.has_custom_grass,
            "has_custom_foliage": colors.has_custom_foliage,
            "has_custom_dry_foliage": colors.has_custom_dry_foliage,
        }
    return res

BIOME_PALETTES: dict[str, dict[str, Any]] = _build_biome_palettes_registry()

BLOCK_TINT_REGISTRY: dict[str, list[tuple[str, Any]]] = {
    # Grass & Flora
    "grass_block": [("grass", 1.0)],
    "short_grass": [("grass", 1.0)],
    "grass": [("grass", 1.0)],
    "tall_grass": [("grass", 1.0)],
    "fern": [("grass", 1.0)],
    "large_fern": [("grass", 1.0)],
    "potted_fern": [("grass", 1.0)],
    "bush": [("grass", 1.0)],
    "sugar_cane": [("grass", 1.0)],
    # Multi-layer Flora (Layer 0 = Petals/Blank, Layer 1 = Stem/Grass)
    "pink_petals": [("none", 0.0), ("grass", 1.0)],
    "wildflowers": [("none", 0.0), ("grass", 1.0)],
    "bamboo": [("grass", 1.0)],
    # Foliage
    "oak_leaves": [("foliage", 1.0)],
    "jungle_leaves": [("foliage", 1.0)],
    "acacia_leaves": [("foliage", 1.0)],
    "dark_oak_leaves": [("foliage", 1.0)],
    "vine": [("foliage", 1.0)],
    "mangrove_leaves": [("foliage", 1.0)],
    # Dry Foliage
    "leaf_litter": [("dry_foliage", 1.0)],
    "pale_hanging_moss": [("dry_foliage", 1.0)],
    "pale_hanging_moss_tip": [("dry_foliage", 1.0)],
    "pale_oak_leaves": [("none", 1.0)],
    # Water & Fluid
    "water": [("water", 1.0)],
    "flowing_water": [("water", 1.0)],
    "water_still": [("water", 1.0)],
}

HARDCODED_BLOCK_TINTS: dict[str, str] = {
    "spruce_leaves": "#619961",
    "birch_leaves": "#80A755",
    "lily_pad": "#208030",
    "redstone_wire": "#4C0000",
    "attached_melon_stem": "#E0C71C",
    "attached_pumpkin_stem": "#E0C71C",
    "melon_stem": "#E0C71C",
    "pumpkin_stem": "#E0C71C",
}

KNOWN_OVERLAY_PAIRS: dict[str, str] = {
    "grass_block_side": "grass_block_side_overlay",
}

TINT_TYPE_NONE = 0
TINT_TYPE_GRASS = 1
TINT_TYPE_FOLIAGE = 2
TINT_TYPE_WATER = 3
TINT_TYPE_HARDCODED = 4
TINT_TYPE_DRY_FOLIAGE = 5

TINT_STR_TO_INT = {
    "none": TINT_TYPE_NONE,
    "grass": TINT_TYPE_GRASS,
    "foliage": TINT_TYPE_FOLIAGE,
    "water": TINT_TYPE_WATER,
    "hardcoded": TINT_TYPE_HARDCODED,
    "dry_foliage": TINT_TYPE_DRY_FOLIAGE,
}

BIOME_ENUM_ITEMS: list[tuple[str, str, str]] = [
    (k, v.get("name", k.title()), f"Minecraft {v.get('name', k.title())} Biome")
    for k, v in sorted(BIOME_PALETTES.items(), key=lambda x: x[1].get("name", x[0]))
]


class BiomeResolver:
    """High performance Biome resolver wrapping LibMTK with legacy compatibility facade."""
    def __init__(
        self,
        models: Optional[dict[str, dict]] = None,
        pack_root: Optional[Union[str, Path]] = None,
        pack_stack: Optional[Any] = None,
    ):
        self.models: dict[str, dict] = dict(models) if models else {}
        self.models_by_stem: dict[str, dict] = {}
        self.overlay_pairs: dict[str, str] = dict(KNOWN_OVERLAY_PAIRS)
        self.texture_tint_categories: dict[str, str] = {}
        self.texture_hardcoded_colors: dict[str, str] = {}
        self._rust_stack = getattr(pack_stack, "_rust_stack", None)
        self._resolver = mtk.BiomeResolver(self._rust_stack)
        if pack_root:
            self.load_from_pack_root(pack_root)
        elif pack_stack:
            self.load_from_pack_stack(pack_stack)
        elif self.models:
            self._analyze_models()

    def set_models(self, models: dict[str, dict]):
        self.models = dict(models)
        self._analyze_models()

    def load_from_pack_stack(self, pack_stack: Any):
        self._rust_stack = getattr(pack_stack, "_rust_stack", None)
        self._resolver = mtk.BiomeResolver(self._rust_stack)
        if hasattr(pack_stack, "get_all_models"):
            self.models.update(pack_stack.get_all_models())
            self._analyze_models()
        elif hasattr(pack_stack, "packs"):
            for pack in reversed(pack_stack.packs):
                self.load_from_pack(pack)

    def load_from_pack(self, pack: Any):
        if hasattr(pack, "get_all_models"):
            self.models.update(pack.get_all_models())
            self._analyze_models()
        elif getattr(pack, "extract_dir", None) and Path(pack.extract_dir).exists():
            self.load_from_pack_root(pack.extract_dir)
        elif getattr(pack, "zip_path", None) and Path(pack.zip_path).exists():
            self.load_from_zip(pack.zip_path)

    def load_from_pack_root(self, pack_root: Union[str, Path]):
        pack_path = Path(pack_root)
        if not pack_path.exists():
            return
        assets_dir = pack_path / "assets"
        if not assets_dir.exists():
            return
        import json
        for model_file in assets_dir.glob("*/models/**/*.json"):
            try:
                with open(model_file, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    if isinstance(data, dict):
                        rel_key = model_file.as_posix().split("/models/", 1)[-1].replace(".json", "").lower()
                        self.models[rel_key] = data
                        self.models[model_file.stem.lower()] = data
            except Exception:
                pass
        self._analyze_models()

    def load_from_zip(self, zip_path: Union[str, Path]):
        import zipfile, json
        zp = Path(zip_path)
        if not zp.exists() or not zipfile.is_zipfile(zp):
            return
        try:
            with zipfile.ZipFile(zp, "r") as z:
                for name in z.namelist():
                    if name.startswith("assets/") and "/models/" in name and name.endswith(".json"):
                        rel_key = name.split("/models/", 1)[1].replace(".json", "").lower()
                        try:
                            data = json.loads(z.read(name))
                            if isinstance(data, dict):
                                self.models[rel_key] = data
                                stem = rel_key.split("/")[-1]
                                self.models[stem] = data
                        except Exception:
                            pass
        except Exception:
            pass
        self._analyze_models()

    def _analyze_models(self):
        self.models_by_stem.clear()
        for k, v in self.models.items():
            stem = k.split("/")[-1].replace(".json", "")
            self.models_by_stem[stem] = v

    def get_overlay_texture(self, texture_stem: str) -> Optional[str]:
        return self.overlay_pairs.get(texture_stem)

    def get_tint_category(self, texture_stem: str, block_name: Optional[str] = None) -> str:
        return classify_tint_category(texture_stem, block_name)

    def get_tint_info(
        self,
        texture_name: str,
        block_name: Optional[str] = None,
        tint_index: Optional[int] = None,
    ) -> dict[str, Any]:
        """Determine full tint metadata for a texture stem / resource key."""
        clean = texture_name.lower().removeprefix("minecraft:").removeprefix("block/")
        if ":" in clean:
            clean = clean.split(":", 1)[1]
        cat = classify_tint_category(clean, block_name=block_name, tint_index=tint_index)
        tint_type_int = {
            "none": TINT_TYPE_NONE,
            "grass": TINT_TYPE_GRASS,
            "foliage": TINT_TYPE_FOLIAGE,
            "water": TINT_TYPE_WATER,
            "hardcoded": TINT_TYPE_HARDCODED,
            "dry_foliage": TINT_TYPE_DRY_FOLIAGE,
        }.get(cat, TINT_TYPE_NONE)
        hardcoded_hex = get_hardcoded_tint(clean) or (get_hardcoded_tint(block_name) if block_name else None)
        overlay_tex = self.overlay_pairs.get(clean)
        hardcoded_linear = hex_to_linear_rgba(hardcoded_hex) if hardcoded_hex else (1.0, 1.0, 1.0, 1.0)
        return {
            "tint_type": tint_type_int,
            "tint_category": cat,
            "tint_weight": 1.0 if cat != "none" else 0.0,
            "base_tint_weight": 1.0,
            "overlay_tint_weight": 1.0,
            "has_overlay": bool(overlay_tex),
            "overlay_texture": overlay_tex,
            "is_hardcoded": bool(cat == "hardcoded" or hardcoded_hex is not None),
            "hardcoded_color": hardcoded_hex,
            "hardcoded_hex": hardcoded_hex,
            "hardcoded_color_linear": hardcoded_linear,
        }

    def get_biome_colors(self, biome_id: str) -> dict[str, Any]:
        return self._resolver.resolve_biome(biome_id).to_dict()

    def bake_all(self) -> dict[str, dict[str, Any]]:
        palettes = self._resolver.bake_all_palettes()
        return {k: v.to_dict() for k, v in palettes.items()}


def get_biome_colors(biome_name: str, pack_stack: Optional[Any] = None) -> dict[str, Any]:
    """Look up biome color values using LibMTK."""
    rust_stack = getattr(pack_stack, "_rust_stack", None)
    clean_id = biome_name.lower().removeprefix("minecraft:")
    colors = mtk.get_biome_colors(clean_id, rust_stack)
    return colors.to_dict()


def classify_tint_category(
    texture_stem: str = "",
    block_name: Optional[str] = None,
    tint_index: Optional[int] = None,
    clean_stem: Optional[str] = None,
) -> str:
    """Classify the tint category for a block or texture stem."""
    stem = clean_stem if clean_stem is not None else texture_stem
    return mtk.classify_tint_category(stem, block_name, tint_index)


def get_hardcoded_tint(block_name: str) -> Optional[str]:
    """Look up hardcoded tint hex color."""
    return mtk.get_hardcoded_tint(block_name)
