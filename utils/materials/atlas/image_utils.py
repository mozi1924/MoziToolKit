"""
Image safety, validation, animation detection, and alpha transparency analysis for Atlas generation.
"""

from __future__ import annotations

from typing import Any, Optional

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

    Resource packs commonly contain thousands of PNGs. Keeping Pillow's
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


def is_animated_texture(image: Any, mcmeta: dict | None) -> bool:
    """
    Determine if a texture is truly animated based on its image dimensions and mcmeta metadata.
    """
    if not mcmeta or not isinstance(mcmeta, dict):
        return False
    anim = mcmeta.get("animation") if isinstance(mcmeta.get("animation"), dict) else mcmeta
    if not isinstance(anim, dict):
        return False

    if image is None:
        return True

    w, h = image.size
    frame_width = max(1, int(anim.get("width") or w))
    frame_height = max(1, int(anim.get("height") or frame_width))
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
