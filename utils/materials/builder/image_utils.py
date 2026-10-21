"""
Image and Material Node Helpers.
Provides high-performance image streaming (f32/rgba zero-copy memory buffers from .mtkcache),
Blender datablock creation/caching, and forward-compatible material node utilities.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False


def set_material_displacement_method(mat: Any, method: str = "BOTH") -> None:
    """Configure material displacement method for Cycles and EEVEE across Blender versions."""
    if not mat:
        return
    if hasattr(mat, "displacement_method"):
        try:
            mat.displacement_method = method
        except Exception:
            pass
    elif hasattr(mat, "cycles") and hasattr(mat.cycles, "displacement_method"):
        try:
            mat.cycles.displacement_method = method
        except Exception:
            pass


def ensure_material_node_tree(mat: Any) -> Any:
    """
    Ensure the material has an active node tree across Blender versions
    without accessing deprecated 'Material.use_nodes' in Blender 5.x/6.0+.
    """
    if mat is None:
        return None
    tree = getattr(mat, "node_tree", None)
    if tree is not None:
        return tree

    # Legacy Blender fallback (< 5.0) where node_tree is not initialized automatically
    try:
        import bpy
        if getattr(bpy.app, "version", (0, 0, 0)) < (5, 0, 0):
            mat.use_nodes = True
    except Exception:
        pass
    return getattr(mat, "node_tree", None)


def _is_valid_image(img: Any, expected_w: Optional[int] = None, expected_h: Optional[int] = None) -> bool:
    """Check if a Blender image datablock exists and holds valid image data."""
    if img is None:
        return False
    try:
        w, h = img.size[0], img.size[1]
        if w <= 0 or h <= 0:
            return False
        if expected_w is not None and w != expected_w:
            return False
        if expected_h is not None and h != expected_h:
            return False
        return True
    except Exception:
        return False


def get_or_create_image_from_f32(
    image_name: str,
    width: int,
    height: int,
    f32_bytes_or_memview: Any,
    colorspace: str = "sRGB",
    force_reload: bool = False,
) -> Optional[Any]:
    """
    Creates or updates an image datablock directly from normalized float32 memory buffer.
    Zero disk IO, zero numpy conversion, and zero intermediate copies into Blender's Image.pixels.
    """
    if not HAS_BPY:
        return None

    img = bpy.data.images.get(image_name)
    if not force_reload and _is_valid_image(img, width, height):
        if hasattr(img, "colorspace_settings") and colorspace:
            try:
                img.colorspace_settings.name = colorspace
            except Exception:
                pass
        return img

    try:
        if img is None:
            img = bpy.data.images.new(image_name, width=width, height=height, alpha=True)
        elif img.size[0] != width or img.size[1] != height:
            img.scale(width, height)

        mv = memoryview(f32_bytes_or_memview)
        if mv.format != "f":
            mv = mv.cast("f")
        img.pixels.foreach_set(mv)
        img.update()
        if hasattr(img, "pack"):
            try:
                img.pack()
            except Exception:
                pass
        if hasattr(img, "colorspace_settings") and colorspace:
            try:
                img.colorspace_settings.name = colorspace
            except Exception:
                pass
        return img
    except Exception:
        try:
            fresh_img = bpy.data.images.new(image_name, width=width, height=height, alpha=True)
            mv = memoryview(f32_bytes_or_memview)
            if mv.format != "f":
                mv = mv.cast("f")
            fresh_img.pixels.foreach_set(mv)
            fresh_img.update()
            if hasattr(fresh_img, "pack"):
                try:
                    fresh_img.pack()
                except Exception:
                    pass
            if hasattr(fresh_img, "colorspace_settings") and colorspace:
                try:
                    fresh_img.colorspace_settings.name = colorspace
                except Exception:
                    pass
            return fresh_img
        except Exception:
            return None


def get_or_create_image_from_rgba(
    image_name: str,
    width: int,
    height: int,
    rgba_bytes_or_memview: Any,
    colorspace: str = "sRGB",
    force_reload: bool = False,
    flip_y: bool = True,
) -> Optional[Any]:
    """
    Creates or updates an image datablock directly in memory using NumPy.
    Zero disk IO and zero temporary files, tightly packed into Blender.

    :param flip_y: If True (default), vertically flips image rows (np.flipud) to align
                   standard top-to-bottom image buffers with Blender's bottom-to-top img.pixels layout.
    """
    if not HAS_BPY:
        return None

    img = bpy.data.images.get(image_name)
    if not force_reload and _is_valid_image(img, width, height):
        if hasattr(img, "colorspace_settings") and colorspace:
            try:
                img.colorspace_settings.name = colorspace
            except Exception:
                pass
        return img

    try:
        import numpy as np
    except ImportError:
        np = None

    if np is None:
        return None

    try:
        if img is None:
            img = bpy.data.images.new(image_name, width=width, height=height, alpha=True)
        elif img.size[0] != width or img.size[1] != height:
            img.scale(width, height)

        raw_u8 = np.frombuffer(rgba_bytes_or_memview, dtype=np.uint8)
        if flip_y:
            u8_2d = raw_u8.reshape((height, width, 4))
            flipped = np.ascontiguousarray(np.flipud(u8_2d))
            flat_f32 = flipped.reshape(-1).astype(np.float32) * (1.0 / 255.0)
        else:
            flat_f32 = (raw_u8.astype(np.float32) * (1.0 / 255.0))
        img.pixels.foreach_set(flat_f32)
        img.update()
        if hasattr(img, "pack"):
            try:
                img.pack()
            except Exception:
                pass
        if hasattr(img, "colorspace_settings") and colorspace:
            try:
                img.colorspace_settings.name = colorspace
            except Exception:
                pass
        return img
    except Exception:
        try:
            fresh_img = bpy.data.images.new(image_name, width=width, height=height, alpha=True)
            raw_u8 = np.frombuffer(rgba_bytes_or_memview, dtype=np.uint8)
            if flip_y:
                u8_2d = raw_u8.reshape((height, width, 4))
                flipped = np.ascontiguousarray(np.flipud(u8_2d))
                flat_f32 = flipped.reshape(-1).astype(np.float32) * (1.0 / 255.0)
            else:
                flat_f32 = (raw_u8.astype(np.float32) * (1.0 / 255.0))
            fresh_img.pixels.foreach_set(flat_f32)
            fresh_img.update()
            if hasattr(fresh_img, "pack"):
                try:
                    fresh_img.pack()
                except Exception:
                    pass
            if hasattr(fresh_img, "colorspace_settings") and colorspace:
                try:
                    fresh_img.colorspace_settings.name = colorspace
                except Exception:
                    pass
            return fresh_img
        except Exception:
            return None


def get_or_create_image(
    image_path_or_source: Any,
    colorspace: str = "sRGB",
    force_reload: bool = False,
    chunk_id: Optional[str] = None,
    flip_y: bool = True,
) -> Optional[Any]:
    """
    Load or retrieve an image datablock from memory (.mtkcache) or disk.
    Prioritizes fast zero-disk memory streaming before falling back to filesystem.
    """
    if not HAS_BPY or image_path_or_source is None:
        return None

    # 1. Handle in-memory (width, height, buffer) tuple directly
    if isinstance(image_path_or_source, (tuple, list)) and len(image_path_or_source) == 3:
        w, h, buf = image_path_or_source
        img_name = os.path.basename(chunk_id) if chunk_id else "MTK_Memory_Image"
        nbytes = getattr(buf, "nbytes", len(buf))
        is_f32 = (nbytes == w * h * 16) or (hasattr(buf, "format") and buf.format == "f" and len(buf) == w * h * 4)
        if isinstance(buf, (bytes, bytearray, memoryview)) and is_f32:
            img = get_or_create_image_from_f32(img_name, w, h, buf, colorspace=colorspace, force_reload=force_reload)
            if img is not None:
                return img
        return get_or_create_image_from_rgba(
            img_name, w, h, buf, colorspace=colorspace, force_reload=force_reload, flip_y=flip_y
        )

    # 2. Try resolving chunk_id from package if explicit or identifiable
    resolved_chunk_id = chunk_id
    path_str = str(image_path_or_source)
    if not resolved_chunk_id:
        if path_str.startswith(("atlas/textures/", "biome/colormap/")):
            resolved_chunk_id = path_str
        elif "_chunk_" in path_str and path_str.endswith(".png"):
            resolved_chunk_id = f"atlas/textures/{os.path.basename(path_str)}"
    elif "_chunk_" in resolved_chunk_id and not resolved_chunk_id.startswith("atlas/textures/"):
        resolved_chunk_id = f"atlas/textures/{os.path.basename(resolved_chunk_id)}"

    if resolved_chunk_id:
        img_name = os.path.basename(resolved_chunk_id)
        existing_img = bpy.data.images.get(img_name)
        if not force_reload and _is_valid_image(existing_img):
            if hasattr(existing_img, "colorspace_settings") and colorspace:
                try:
                    existing_img.colorspace_settings.name = colorspace
                except Exception:
                    pass
            return existing_img

        from ....bridge.assets import get_cached_texture_f32, get_cached_texture_rgba

        # Tier 1: Zero-copy float32 streaming directly from native Rust (pre-flipped & converted)
        if get_cached_texture_f32 is not None:
            f32_tuple = get_cached_texture_f32(resolved_chunk_id, flip_y=flip_y)
            if f32_tuple is not None:
                w, h, memview = f32_tuple
                img = get_or_create_image_from_f32(
                    img_name, w, h, memview, colorspace=colorspace, force_reload=force_reload
                )
                if img is not None:
                    return img

        # Tier 2: Flipped RGBA8 buffer directly from native Rust
        if get_cached_texture_rgba is not None:
            rgba_tuple = get_cached_texture_rgba(resolved_chunk_id, flip_y=flip_y)
            if rgba_tuple is not None:
                w, h, memview = rgba_tuple
                img = get_or_create_image_from_rgba(
                    img_name, w, h, memview, colorspace=colorspace, force_reload=force_reload, flip_y=False
                )
                if img is not None:
                    return img

    # 3. Fallback: On-disk filesystem loading
    resolved_path = None
    try:
        p = Path(path_str).resolve()
        if p.exists() and p.is_file():
            resolved_path = str(p)
    except Exception:
        resolved_path = None

    if not resolved_path:
        return None

    file_name = os.path.basename(resolved_path)
    for img in bpy.data.images:
        if img.filepath == resolved_path or img.name == file_name:
            if force_reload and hasattr(img, "reload"):
                try:
                    img.reload()
                except Exception:
                    pass
            if hasattr(img, "colorspace_settings") and colorspace:
                try:
                    img.colorspace_settings.name = colorspace
                except Exception:
                    pass
            return img

    try:
        img = bpy.data.images.load(resolved_path, check_existing=True)
        if hasattr(img, "colorspace_settings") and colorspace:
            try:
                img.colorspace_settings.name = colorspace
            except Exception:
                pass
        return img
    except Exception:
        return None


def _create_frame(
    nodes: Any,
    name: str,
    label: str,
    color: tuple[float, float, float] | None = None,
) -> Any:
    """Helper to create and style a layout frame node."""
    frame = nodes.new("NodeFrame")
    frame.name = name
    frame.label = label
    if color is not None and hasattr(frame, "use_custom_color"):
        frame.use_custom_color = True
        frame.color = color
    return frame
