"""
Palette Permutation Baker for Minecraft Atlases (LabPBR / Permutations).
Bakes `minecraft:paletted_permutations` sources by mapping key palette pixels to permutation palette pixels in memory.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .image_utils import HAS_PIL, Image, _safe_open_image

logger = logging.getLogger("MoziToolKit.Atlas.PaletteBaker")


def _extract_palette_colors(palette_img: Any) -> list[tuple[int, int, int, int]]:
    """Extract ordered RGBA color tuples from a palette image (1xN or Nx1)."""
    if palette_img is None:
        return []
    w, h = palette_img.size
    rgba_img = palette_img.convert("RGBA")
    colors = []
    if w >= h:
        for x in range(w):
            for y in range(h):
                colors.append(rgba_img.getpixel((x, y)))
    else:
        for y in range(h):
            for x in range(w):
                colors.append(rgba_img.getpixel((x, y)))
    return colors


def bake_paletted_permutation(
    base_image: Any,
    key_palette_image: Any,
    perm_palette_image: Any,
) -> Optional[Any]:
    """
    Apply a single paletted color permutation to a base texture in-memory.
    Matches non-zero alpha pixels of `base_image` to `key_palette_image` colors,
    and replaces them with corresponding colors from `perm_palette_image`.
    """
    if not HAS_PIL or base_image is None or key_palette_image is None or perm_palette_image is None:
        return None

    key_colors = _extract_palette_colors(key_palette_image)
    perm_colors = _extract_palette_colors(perm_palette_image)

    if not key_colors or not perm_colors:
        return base_image.copy()

    # Build color lookup map: (r, g, b) -> (new_r, new_g, new_b, new_a)
    color_map: dict[tuple[int, int, int], tuple[int, int, int, int]] = {}
    num_entries = min(len(key_colors), len(perm_colors))
    for i in range(num_entries):
        kr, kg, kb, ka = key_colors[i]
        pr, pg, pb, pa = perm_colors[i]
        color_map[(kr, kg, kb)] = (pr, pg, pb, pa)

    base_rgba = base_image.convert("RGBA")
    w, h = base_rgba.size
    result_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    base_pixels = base_rgba.load()
    res_pixels = result_img.load()

    for y in range(h):
        for x in range(w):
            r, g, b, a = base_pixels[x, y]
            if a == 0:
                continue

            # Check exact RGB match in key palette
            rgb_key = (r, g, b)
            if rgb_key in color_map:
                pr, pg, pb, pa = color_map[rgb_key]
                # Modulate alpha
                final_a = int(round((a * pa) / 255.0))
                res_pixels[x, y] = (pr, pg, pb, final_a)
            else:
                # Keep original pixel if not present in palette key
                res_pixels[x, y] = (r, g, b, a)

    return result_img


class PalettePermutationEngine:
    """Manages loading palette keys, permutations, and batch baking permutation textures."""

    def __init__(self, image_finder_fn=None):
        self._image_finder = image_finder_fn
        self._palette_cache: dict[str, Any] = {}

    def _resolve_image(self, resource_key: str) -> Optional[Any]:
        if resource_key in self._palette_cache:
            return self._palette_cache[resource_key]

        img = None
        if self._image_finder:
            img = self._image_finder(resource_key)

        if img is not None:
            self._palette_cache[resource_key] = img
        return img

    def bake_source(
        self,
        palette_key: str,
        permutations: dict[str, str],
        textures: list[str],
        get_texture_fn=None,
    ) -> dict[str, Any]:
        """
        Bake all permutations for the given textures list.
        Returns:
            dict mapping canonical sprite key (e.g. 'minecraft:trims/items/helmet_trim_amethyst') to baked PIL.Image.
        """
        results: dict[str, Any] = {}
        if not HAS_PIL:
            return results

        key_img = self._resolve_image(palette_key)
        if key_img is None and get_texture_fn:
            key_img = get_texture_fn(palette_key)
        if key_img is None:
            logger.debug(f"Palette key image not found: {palette_key}")
            return results

        for perm_name, perm_res in permutations.items():
            perm_img = self._resolve_image(perm_res)
            if perm_img is None and get_texture_fn:
                perm_img = get_texture_fn(perm_res)
            if perm_img is None:
                continue

            for tex_res in textures:
                base_img = get_texture_fn(tex_res) if get_texture_fn else self._resolve_image(tex_res)
                if base_img is None:
                    continue

                baked = bake_paletted_permutation(base_img, key_img, perm_img)
                if baked is not None:
                    # Output sprite naming: e.g. "minecraft:trims/items/helmet_trim_amethyst"
                    ns = "minecraft"
                    tex_clean = tex_res
                    if ":" in tex_res:
                        ns, tex_clean = tex_res.split(":", 1)
                    sprite_key = f"{ns}:{tex_clean}_{perm_name}"
                    results[sprite_key] = baked

        return results
