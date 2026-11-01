"""
MoziToolKit Atlas Image Refresh (Blender host side).

Keeps already-loaded `bpy.data.images` datablocks in sync with the on-disk /
packaged atlas cache. This is pure DCC host business: it must not live in
`MoziToolKit.bridge`, which only marshals data between Blender and libmtk.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ....bridge.assets.cache import get_cache_dir

logger = logging.getLogger("MoziToolKit.Utils.Materials.Builder.AtlasRefresh")


def reload_atlas_images(prefs=None) -> int:
    """
    Finds loaded Blender image datablocks originating from the atlas cache directory
    or compiled .mtkcache container, refreshing image pixels and mipmaps so changes immediately
    reflect on screen.
    Returns the count of successfully reloaded images.
    """
    try:
        import bpy
    except ImportError:
        return 0

    if not hasattr(bpy, "data") or not hasattr(bpy.data, "images"):
        return 0

    cache_dir = get_cache_dir(prefs)
    atlas_dir = cache_dir / "atlas"
    atlas_dir_str = str(atlas_dir.resolve()).lower()

    reloaded_count = 0

    # 1. Reload file-backed images
    for img in bpy.data.images:
        fp = getattr(img, "filepath", "")
        if not fp:
            continue
        try:
            resolved_fp = str(Path(bpy.path.abspath(fp)).resolve()).lower()
            if atlas_dir_str in resolved_fp or "atlas" in resolved_fp:
                if hasattr(img, "reload"):
                    img.reload()
                    reloaded_count += 1
        except Exception:
            continue

    # 2. Reload in-memory packed atlas images from active cache package
    try:
        from ....bridge.assets.cache import load_baked_atlas_from_cache
        active_atlas = load_baked_atlas_from_cache(prefs)
        if active_atlas is not None and hasattr(active_atlas, "get_all_chunks_info"):
            chunks_info = active_atlas.get_all_chunks_info()
            for cm in chunks_info:
                cid = cm.get("chunk_id", 0)
                cat = cm.get("category", "blocks")
                c_idx = cm.get("category_chunk_index", cid + 1)
                is_anim = cm.get("is_animated", False)
                stem = cm.get("file_stem") or (f"{cat}_anim_chunk_{c_idx:03}" if is_anim else f"{cat}_chunk_{c_idx:03}")
                w = int(cm.get("width", 4096))
                h = int(cm.get("height", 4096))

                cand_names = [f"{stem}.png", stem, f"{cat}_chunk_{c_idx:03}.png"]
                img = None
                for nm in cand_names:
                    img = bpy.data.images.get(nm)
                    if img is not None:
                        break
                f32_tuple = None
                if active_atlas is not None and hasattr(active_atlas, "get_chunk_albedo_f32"):
                    try:
                        albedo_f32 = active_atlas.get_chunk_albedo_f32(cid, flip_v=True)
                        if albedo_f32 is not None:
                            f32_tuple = (w, h, albedo_f32)
                    except Exception:
                        pass
                if f32_tuple is None:
                    from ....bridge.assets.cache import get_cached_texture_f32
                    f32_tuple = get_cached_texture_f32(f"atlas/textures/{stem}.png", prefs=prefs, flip_y=True)

                if img is not None and f32_tuple is not None:
                    _, _, albedo_f32 = f32_tuple
                    try:
                        if img.size[0] != w or img.size[1] != h:
                            img.scale(w, h)
                        img.pixels.foreach_set(albedo_f32)
                        img.update()
                        reloaded_count += 1
                    except Exception:
                        pass
    except Exception as e:
        logger.debug("Failed refreshing in-memory atlas images: %s", e)

    return reloaded_count

