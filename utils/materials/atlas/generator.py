"""
Atlas Generator for Minecraft Resource Packs / JARs using libmtk_py.
Generates size-bounded texture atlas images (Albedo, Normal, Specular) and mapping JSON.
"""

from __future__ import annotations

import os
import json
import logging
from pathlib import Path
from typing import Any, Optional, Union, Iterator, Tuple

import libmtk_py as mtk

from ..constants import (
    FACE_ORDER,
    FALLBACK_TEXTURE_KEY,
    ATLAS_FORMAT_VERSION,
    classify_texture_category,
)
from ..pack.pack_stack import ResourcePackStack, get_configured_pack_stack

logger = logging.getLogger("MoziToolKit.Atlas.Generator")

MAX_IMAGE_DIMENSION = 16384
HAS_PIL = True


def is_animated_texture(image: Any = None, mcmeta: Optional[dict] = None) -> bool:
    if mcmeta and "animation" in mcmeta:
        return True
    if image and hasattr(image, "size") and image.size[1] > image.size[0]:
        return (image.size[1] % image.size[0] == 0)
    return False


def analyze_texture_transparency(image: Any = None) -> tuple[bool, str]:
    if not image or not hasattr(image, "getextrema"):
        return True, "OPAQUE"
    try:
        bands = image.getbands()
        if "A" not in bands:
            return True, "OPAQUE"
        alpha_idx = bands.index("A")
        extrema = image.getextrema()
        min_a, max_a = extrema[alpha_idx] if isinstance(extrema, tuple) and isinstance(extrema[0], tuple) else extrema
        if min_a == 255:
            return True, "OPAQUE"
        if min_a == 0 and max_a == 255:
            return False, "MASK"
        return False, "BLEND"
    except Exception:
        return True, "OPAQUE"


class AtlasGenerator:
    """
    Parses Minecraft block models and textures using Rust LibMTK core.
    Constructs deduplicated, size-bounded atlas chunks and mapping.
    """

    def __init__(
        self,
        resource_path: Optional[Union[str, Path, ResourcePackStack]] = None,
        default_tile_size: int = 16,
        max_chunk_size: int = 4096,
        fallback_stack: Optional[ResourcePackStack] = None,
        included_categories: Optional[set[str]] = None,
        filter_scene_blacklist: bool = False,
    ):
        if isinstance(resource_path, ResourcePackStack):
            self.pack_stack = resource_path
        elif fallback_stack is not None:
            self.pack_stack = fallback_stack
        elif resource_path:
            self.pack_stack = ResourcePackStack([Path(resource_path)])
        else:
            self.pack_stack = get_configured_pack_stack()

        self.default_tile_size = default_tile_size
        self.max_chunk_size = max_chunk_size
        self.included_categories = frozenset(included_categories) if included_categories else None
        self.filter_scene_blacklist = filter_scene_blacklist
        self._baked_atlas: Optional[mtk.BakedAtlas] = None

    def classify_texture(self, path_or_key: str, namespace: str = "minecraft") -> tuple[str, str]:
        clean = (path_or_key or "").replace("\\", "/").strip("/").lower()
        if ":" in clean:
            ns_part, clean = clean.split(":", 1)
            if not namespace or namespace == "minecraft":
                namespace = ns_part
        if "textures/" in clean:
            clean = clean.split("textures/", 1)[1].strip("/")
        cat = classify_texture_category(clean)
        return cat, clean

    def build(self, output_dir: str | Path) -> dict:
        result = None
        for _frac, _msg, res in self.build_iter(output_dir):
            if res is not None:
                result = res
        return result or {}

    def build_iter(self, output_dir: str | Path) -> Iterator[Tuple[float, str, Optional[dict]]]:
        yield (0.10, "Initializing LibMTK Atlas Builder...", None)
        out_path = Path(output_dir).resolve()
        out_path.mkdir(parents=True, exist_ok=True)

        yield (0.30, "Packing texture atlas sheets with Rust core...", None)
        rust_stack = getattr(self.pack_stack, "_rust_stack", None)
        if rust_stack is None:
            rust_stack = mtk.ResourcePackStack()
            if self.pack_stack and self.pack_stack.packs:
                for p in self.pack_stack.packs:
                    zp = Path(p.zip_path)
                    if zp.is_dir():
                        rust_stack.add_directory_pack(str(zp))
                    elif zp.is_file():
                        rust_stack.add_zip_pack(str(zp))

        builder = mtk.AtlasBuilder(
            max_width=self.max_chunk_size,
            max_height=self.max_chunk_size,
        )

        if self.included_categories:
            self._baked_atlas = builder.build_categories(rust_stack, list(self.included_categories))
        else:
            self._baked_atlas = builder.build_all(rust_stack)

        yield (0.70, "Saving baked atlas chunks and mapping to disk...", None)
        self._baked_atlas.save_to_dir(str(out_path))

        mapping_file = out_path / "atlas_mapping.json"
        mapping_data = {}
        if mapping_file.exists():
            try:
                with open(mapping_file, "r", encoding="utf-8") as f:
                    mapping_data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read written atlas_mapping.json: {e}")
        mapping_data["mapping"] = mapping_file
        mapping_data["mapping_path"] = mapping_file
        yield (1.0, f"Atlas build complete: {self._baked_atlas.chunk_count} chunk(s)", mapping_data)

    def cleanup(self) -> None:
        self._baked_atlas = None


__all__ = [
    "AtlasGenerator",
    "is_animated_texture",
    "analyze_texture_transparency",
    "MAX_IMAGE_DIMENSION",
    "HAS_PIL",
]
