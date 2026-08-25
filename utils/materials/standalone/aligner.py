"""
Standalone texture aligner for animated Minecraft materials with PBR channels (_s, _n).
Ensures all texture channels (Albedo, Normal, Specular, Overlay) have matching frame counts
and unified animation metadata, preventing UV stretching / distortion when mesh UVs are baked to Frame 0.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..pack.resource_pack import get_cache_dir
from ...system.dependencies import has_pillow

try:
    from PIL import Image
    HAS_PIL = True
    Image.MAX_IMAGE_PIXELS = 128 * 1024 * 1024  # 128 MP max image pixels threshold
except ImportError:
    Image = None
    HAS_PIL = False

MAX_IMAGE_DIMENSION = 16384  # Max allowed width/height in pixels


def _get_channel_image_size(img_path: Path | str | None) -> tuple[int, int] | None:
    """Safely get (width, height) of an image path using PIL."""
    if not img_path:
        return None
    p = Path(img_path)
    if not p.exists() or not HAS_PIL:
        return None
    try:
        with Image.open(p) as img:
            return img.size
    except Exception:
        return None


def is_channel_animated(img_path: Path | str | None, mcmeta: dict | None) -> bool:
    """Determine if a single channel has animation (multiple frames)."""
    if not img_path:
        return False
    size = _get_channel_image_size(img_path)
    if not size:
        return False
    w, h = size
    if mcmeta and isinstance(mcmeta, dict):
        frame_w = int(mcmeta.get("width") or w)
        frame_h = int(mcmeta.get("height") or frame_w)
        frames = mcmeta.get("frames", [])
        total_frames = h // frame_h if frame_h > 0 else 1
        if total_frames > 1 or (isinstance(frames, list) and len(frames) > 1):
            return True
    elif h > w and h % w == 0:
        return True
    return False


def align_standalone_textures(
    texture_info: dict,
    pack_hash: str | None = None,
    output_dir: Path | None = None,
) -> dict:
    """
    Inspect texture channels in texture_info. If any channel is animated, ensure all
    present channels (Albedo, Normal, Specular, Overlay) are aligned to the same frame
    count by tiling static or shorter channels vertically.

    Returns a new or updated texture_info dictionary with aligned image paths and animation metadata.
    """
    if not texture_info or not isinstance(texture_info, dict):
        return texture_info

    # If Pillow is unavailable, return original texture_info
    if not HAS_PIL:
        return texture_info

    # Check which channels exist and are animated
    channels = ["albedo", "normal", "specular", "overlay"]
    animated_channels = {}
    channel_sizes = {}

    for ch in channels:
        p = texture_info.get(ch)
        if p and Path(p).exists():
            meta = texture_info.get(f"{ch}_mcmeta")
            size = _get_channel_image_size(p)
            if size:
                channel_sizes[ch] = size
                if is_channel_animated(p, meta):
                    animated_channels[ch] = (size, meta)

    # If no channel is animated, return original info unchanged
    if not animated_channels:
        return texture_info

    # Find the reference animation properties (prefer albedo if animated, else first animated channel)
    ref_ch = "albedo" if "albedo" in animated_channels else next(iter(animated_channels.keys()))
    (ref_w, ref_h), ref_meta = animated_channels[ref_ch]

    ref_meta = ref_meta or {}
    ref_frame_w = int(ref_meta.get("width") or ref_w)
    ref_frame_h = int(ref_meta.get("height") or ref_frame_w)
    target_frame_count = max(1, ref_h // ref_frame_h) if ref_frame_h > 0 else 1
    target_frametime = max(1, int(ref_meta.get("frametime", 1)))
    target_interpolate = bool(ref_meta.get("interpolate", False))
    target_frames = ref_meta.get("frames", [])

    if target_frame_count <= 1 and not (isinstance(target_frames, list) and len(target_frames) > 1):
        return texture_info

    # Prepare output directory for aligned standalone images
    if output_dir:
        align_cache_dir = Path(output_dir)
    else:
        cache_root = get_cache_dir()
        hash_folder = pack_hash or texture_info.get("pack_hash") or "standalone"
        align_cache_dir = cache_root / hash_folder / "aligned_standalone"
    align_cache_dir.mkdir(parents=True, exist_ok=True)

    result_info = dict(texture_info)
    namespace = texture_info.get("namespace", "minecraft")
    tex_name = texture_info.get("texture_name", "texture")
    short_hash = (pack_hash or texture_info.get("pack_hash") or "")[:8]

    for ch in channels:
        p = texture_info.get(ch)
        if not p or not Path(p).exists() or ch not in channel_sizes:
            continue

        src_w, src_h = channel_sizes[ch]
        ch_meta = texture_info.get(f"{ch}_mcmeta") or {}
        ch_frame_w = int(ch_meta.get("width") or src_w)
        ch_frame_h = int(ch_meta.get("height") or ch_frame_w)
        ch_frame_count = max(1, src_h // ch_frame_h) if ch_frame_h > 0 else 1

        aligned_h = ch_frame_h * target_frame_count

        # Check if already aligned in frame count
        if ch_frame_count == target_frame_count and src_h == aligned_h:
            # Already matching frame count; ensure metadata is synchronized
            result_info[f"{ch}_mcmeta"] = {
                "frametime": target_frametime,
                "interpolate": target_interpolate,
                "frames": target_frames,
                "width": ch_frame_w,
                "height": ch_frame_h,
            }
            continue

        # Need to generate aligned tiled image
        clean_tex_name = tex_name.replace("/", "-").replace(":", "-")
        out_filename = f"aligned_{short_hash}_{namespace}_{clean_tex_name}_{ch}_{src_w}x{aligned_h}.png"
        out_path = align_cache_dir / out_filename

        try:
            with Image.open(p) as src_img:
                if src_img.width > MAX_IMAGE_DIMENSION or src_img.height > MAX_IMAGE_DIMENSION:
                    raise ValueError(f"Image dimensions ({src_img.width}x{src_img.height}) exceed limit ({MAX_IMAGE_DIMENSION}px)")
                src_img = src_img.convert("RGBA")
                fill_color = (128, 128, 255, 255) if ch == "normal" else (0, 0, 0, 0)
                aligned_img = Image.new("RGBA", (src_w, aligned_h), fill_color)

                if src_h >= aligned_h:
                    aligned_img.paste(src_img.crop((0, 0, src_w, aligned_h)), (0, 0))
                else:
                    y = 0
                    while y < aligned_h:
                        h_chunk = min(src_h, aligned_h - y)
                        if h_chunk < src_h:
                            aligned_img.paste(src_img.crop((0, 0, src_w, h_chunk)), (0, y))
                        else:
                            aligned_img.paste(src_img, (0, y))
                        y += src_h

                aligned_img.save(out_path)

            result_info[ch] = out_path
            result_info[f"{ch}_mcmeta"] = {
                "frametime": target_frametime,
                "interpolate": target_interpolate,
                "frames": target_frames,
                "width": ch_frame_w,
                "height": ch_frame_h,
            }
        except Exception as e:
            print(f"[MoziToolKit] Warning: Failed to align standalone channel '{ch}' for '{tex_name}': {e}")

    return result_info
