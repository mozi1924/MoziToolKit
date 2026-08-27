"""
Chunk packing strategies (Rect Bin Pack, Uniform Grid, Vertical Animation Strips) and metadata bake routines.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from collections import Counter

from .image_utils import (
    Image,
    _is_power_of_two,
    analyze_texture_transparency,
)
from .packer import pack_category_textures
from ..constants import (
    FALLBACK_TEXTURE_KEY,
    SHORT_NAME_ALLOWED_CATEGORIES,
    FACE_ORDER,
)


def pack_rect_category_chunks(
    cat: str,
    ns: str,
    static_map: dict,
    normal_by_ns_cat: dict,
    specular_by_ns_cat: dict,
    max_chunk_size: int,
    chunks: list,
    category_chunk_counts: dict,
    texture_locations: dict,
    staging_dir: Path,
    output_path: Path,
    outputs: dict,
    biome_resolver: Any,
    fallback_rel_path: str,
    find_static_image_fn: Callable,
    texture_name_fn: Callable,
):
    """Pack irregular sized textures using 2D Rect Bin Packing."""
    rect_items = [(rel_p, static_map[rel_p].width, static_map[rel_p].height) for rel_p in sorted(static_map.keys())]
    packed_chunks = pack_category_textures(rect_items, max_chunk_size=max_chunk_size)

    for chunk_w, chunk_h, placed_rects in packed_chunks:
        chunk_id = len(chunks)
        category_chunk_counts[cat] = category_chunk_counts.get(cat, 0) + 1
        cat_chunk_index = category_chunk_counts[cat]
        images = {
            "albedo": Image.new("RGBA", (chunk_w, chunk_h), (0, 0, 0, 0)),
        }
        overlay_img_canvas = None
        chunk_has_overlay = False
        chunk_has_tint = False
        category_normals = normal_by_ns_cat.get(ns, {}).get(cat, {})
        category_speculars = specular_by_ns_cat.get(ns, {}).get(cat, {})
        has_normal = any(rect.key in category_normals for rect in placed_rects)
        has_specular = any(rect.key in category_speculars for rect in placed_rects)

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
                norm_src = category_normals.get(rel_p)
                if norm_src is not None:
                    if norm_src.size != (rect.width, rect.height):
                        norm_src = norm_src.resize((rect.width, rect.height), Image.NEAREST)
                    images["normal"].paste(norm_src, (rect.x, rect.y))

            if has_specular:
                spec_src = category_speculars.get(rel_p)
                if spec_src is not None:
                    if spec_src.size != (rect.width, rect.height):
                        spec_src = spec_src.resize((rect.width, rect.height), Image.NEAREST)
                    images["specular"].paste(spec_src, (rect.x, rect.y))

            stem = rel_p.split("/")[-1]
            canonical_key = f"{ns}:{rel_p}"
            tint_info = biome_resolver.get_tint_info(stem)
            if tint_info.get("tint_type", 0) != 0 or tint_info.get("is_hardcoded") or tint_info.get("has_overlay"):
                chunk_has_tint = True
            transparency = analyze_texture_transparency(source_albedo)

            overlay_stem = tint_info.get("overlay_texture")
            if overlay_stem:
                overlay_src = find_static_image_fn(overlay_stem, namespace=ns, category=cat)
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
            if rel_p == fallback_rel_path:
                loc_entry["texture_key"] = FALLBACK_TEXTURE_KEY
                loc_entry["is_fallback"] = True
                texture_locations[FALLBACK_TEXTURE_KEY] = loc_entry
            texture_locations[canonical_key] = loc_entry
            texture_locations[rel_p] = loc_entry
            raw_key = texture_name_fn(ns, rel_p.removeprefix("block/") if rel_p.startswith("block/") else rel_p)
            texture_locations[raw_key] = loc_entry
            if ns == "minecraft":
                texture_locations[f"minecraft:{rel_p}"] = loc_entry
                if cat in SHORT_NAME_ALLOWED_CATEGORIES:
                    texture_locations.setdefault(f"minecraft:{stem}", loc_entry)
                    texture_locations.setdefault(stem, loc_entry)
                    if rel_p.startswith("item/"):
                        texture_locations[f"item_{stem}"] = loc_entry
                        texture_locations[f"minecraft:item_{stem}"] = loc_entry
                    elif rel_p.startswith("block/"):
                        texture_locations[stem] = loc_entry
                        texture_locations[f"minecraft:{stem}"] = loc_entry
            else:
                if cat in SHORT_NAME_ALLOWED_CATEGORIES:
                    texture_locations[f"{ns}:{stem}"] = loc_entry
                    if rel_p.startswith("item/"):
                        texture_locations[f"{ns}:item_{stem}"] = loc_entry

        if chunk_has_overlay and overlay_img_canvas is not None:
            images["overlay"] = overlay_img_canvas

        for channel, image in images.items():
            filename = f"{cat}_chunk_{cat_chunk_index:03d}_{channel}.png"
            image.save(staging_dir / filename)
            files[channel] = filename

        chunks.append({
            "chunk_id": chunk_id,
            "category": cat,
            "category_chunk_index": cat_chunk_index,
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


def pack_grid_category_chunks(
    cat: str,
    ns: str,
    static_map: dict,
    normal_by_ns_cat: dict,
    specular_by_ns_cat: dict,
    normal_textures: dict,
    specular_textures: dict,
    default_tile_size: int,
    max_chunk_size: int,
    chunks: list,
    category_chunk_counts: dict,
    texture_locations: dict,
    staging_dir: Path,
    output_path: Path,
    outputs: dict,
    biome_resolver: Any,
    fallback_rel_path: str,
    find_static_image_fn: Callable,
    texture_name_fn: Callable,
):
    """Pack uniform square tiles in regular grid sheets."""
    square_widths = [
        image.width for rel_p, image in static_map.items()
        if rel_p != fallback_rel_path
        and image.width == image.height and _is_power_of_two(image.width)
    ]
    if square_widths:
        counts = Counter(square_widths)
        cat_tile_size = max(counts.keys(), key=lambda w: (counts[w], w))
    else:
        cat_tile_size = default_tile_size

    if cat_tile_size > max_chunk_size:
        raise ValueError(f"Tile size {cat_tile_size}px for category '{cat}' ({ns}) exceeds chunk limit {max_chunk_size}px.")

    tiles_per_row = max(1, max_chunk_size // cat_tile_size)
    capacity = max(1, tiles_per_row * tiles_per_row)
    static_rel_paths = sorted(static_map.keys())

    def tile_for(rel_p, channel, tile_sz=cat_tile_size, namespace_val=ns, category_val=cat):
        clean_k = texture_name_fn(namespace_val, rel_p.removeprefix("block/") if rel_p.startswith("block/") else rel_p)
        if channel == "albedo":
            source = find_static_image_fn(rel_p, namespace=namespace_val, category=category_val)
        elif channel == "normal":
            norm_map = normal_by_ns_cat.get(namespace_val, {}).get(category_val, {})
            source = (
                norm_map.get(rel_p)
                or norm_map.get(f"block/{rel_p}")
                or norm_map.get(rel_p.removeprefix("block/"))
                or normal_textures.get(clean_k)
                or normal_textures.get(rel_p)
            )
        elif channel == "specular":
            spec_map = specular_by_ns_cat.get(namespace_val, {}).get(category_val, {})
            source = (
                spec_map.get(rel_p)
                or spec_map.get(f"block/{rel_p}")
                or spec_map.get(rel_p.removeprefix("block/"))
                or specular_textures.get(clean_k)
                or specular_textures.get(rel_p)
            )
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
        category_chunk_counts[cat] = category_chunk_counts.get(cat, 0) + 1
        cat_chunk_index = category_chunk_counts[cat]
        rows = min(tiles_per_row, max(1, (len(names) + tiles_per_row - 1) // tiles_per_row))
        width = min(max_chunk_size, tiles_per_row * cat_tile_size)
        height = min(max_chunk_size, rows * cat_tile_size)

        images = {
            "albedo": Image.new("RGBA", (width, height), (0, 0, 0, 0)),
        }
        overlay_img_canvas = None
        chunk_has_overlay = False
        chunk_has_tint = False
        category_normals = normal_by_ns_cat.get(ns, {}).get(cat, {})
        category_speculars = specular_by_ns_cat.get(ns, {}).get(cat, {})
        has_normal = any(rel_p in category_normals for rel_p in names)
        has_specular = any(rel_p in category_speculars for rel_p in names)

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
            tint_info = biome_resolver.get_tint_info(stem)
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
                "pixel_x": x,
                "pixel_y": y,
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
            if rel_p == fallback_rel_path:
                loc_entry["texture_key"] = FALLBACK_TEXTURE_KEY
                loc_entry["is_fallback"] = True
                texture_locations[FALLBACK_TEXTURE_KEY] = loc_entry
            texture_locations[canonical_key] = loc_entry
            texture_locations[rel_p] = loc_entry
            raw_key = texture_name_fn(ns, rel_p.removeprefix("block/") if rel_p.startswith("block/") else rel_p)
            texture_locations[raw_key] = loc_entry
            if ns == "minecraft":
                texture_locations[f"minecraft:{rel_p}"] = loc_entry
                if cat in SHORT_NAME_ALLOWED_CATEGORIES:
                    texture_locations.setdefault(f"minecraft:{stem}", loc_entry)
                    texture_locations.setdefault(stem, loc_entry)
                    if rel_p.startswith("item/"):
                        texture_locations[f"item_{stem}"] = loc_entry
                        texture_locations[f"minecraft:item_{stem}"] = loc_entry
                    elif rel_p.startswith("block/"):
                        texture_locations[stem] = loc_entry
                        texture_locations[f"minecraft:{stem}"] = loc_entry
            else:
                if cat in SHORT_NAME_ALLOWED_CATEGORIES:
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
                if overlay_tile and overlay_tile.getbbox():
                    if overlay_img_canvas is None:
                        overlay_img_canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                    overlay_img_canvas.paste(overlay_tile, (x, y))
                    chunk_has_overlay = True

        if chunk_has_overlay and overlay_img_canvas is not None:
            images["overlay"] = overlay_img_canvas

        for channel, image in images.items():
            filename = f"{cat}_chunk_{cat_chunk_index:03d}_{channel}.png"
            image.save(staging_dir / filename)
            files[channel] = filename

        chunks.append({
            "chunk_id": chunk_id,
            "category": cat,
            "category_chunk_index": cat_chunk_index,
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


def pack_animated_category_chunks(
    cat: str,
    ns: str,
    anim_map: dict,
    normal_by_ns_cat: dict,
    specular_by_ns_cat: dict,
    max_chunk_size: int,
    chunks: list,
    category_chunk_counts: dict,
    texture_locations: dict,
    animations: list,
    staging_dir: Path,
    output_path: Path,
    outputs: dict,
    biome_resolver: Any,
    find_static_image_fn: Callable,
    texture_name_fn: Callable,
):
    """Pack animated vertical strips into side-by-side columns."""
    animation_columns = []
    for rel_p in sorted(anim_map.keys()):
        source = anim_map[rel_p]
        image = source["image"]
        if image.width > max_chunk_size or image.height > max_chunk_size:
            raise ValueError(
                f"Animation '{ns}:{rel_p}' ({image.width}x{image.height}) exceeds "
                f"the {max_chunk_size}px chunk limit and cannot be stored losslessly."
            )
        meta_val = source.get("mcmeta") or {}
        anim_dict = meta_val.get("animation") if isinstance(meta_val.get("animation"), dict) else meta_val
        animation_columns.append((rel_p, image, anim_dict))

    def save_animation_chunk(columns, namespace_val=ns, category_val=cat):
        chunk_id = len(chunks)
        category_chunk_counts[category_val] = category_chunk_counts.get(category_val, 0) + 1
        cat_chunk_index = category_chunk_counts[category_val]
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
        category_normals = normal_by_ns_cat.get(namespace_val, {}).get(category_val, {})
        category_speculars = specular_by_ns_cat.get(namespace_val, {}).get(category_val, {})
        has_normal = any(rel_p in category_normals for rel_p, _image, _metadata in columns)
        has_specular = any(rel_p in category_speculars for rel_p, _image, _metadata in columns)

        if has_normal:
            images["normal"] = Image.new("RGBA", (chunk_width, chunk_height), (128, 128, 255, 255))
        if has_specular:
            images["specular"] = Image.new("RGBA", (chunk_width, chunk_height), (0, 0, 0, 0))

        x_offset = 0
        for texture_id, (rel_p, image, metadata) in enumerate(columns):
            target_w = image.width
            target_h = image.height
            x_offset = ((x_offset + target_w - 1) // target_w) * target_w
            clean_k = texture_name_fn(namespace_val, rel_p.removeprefix("block/") if rel_p.startswith("block/") else rel_p)

            for channel, img_canvas in images.items():
                if channel == "albedo":
                    img_canvas.paste(image, (x_offset, 0))
                elif channel == "normal":
                    norm_src = category_normals.get(rel_p)
                    if norm_src:
                        if norm_src.size != (target_w, target_h):
                            norm_src = norm_src.resize((target_w, target_h), Image.NEAREST)
                        img_canvas.paste(norm_src, (x_offset, 0))
                elif channel == "specular":
                    spec_src = category_speculars.get(rel_p)
                    if spec_src:
                        if spec_src.size != (target_w, target_h):
                            spec_src = spec_src.resize((target_w, target_h), Image.NEAREST)
                        img_canvas.paste(spec_src, (x_offset, 0))

            stem = rel_p.split("/")[-1]
            raw_name = clean_k
            canonical_key = f"{namespace_val}:{rel_p}"
            tint_info = biome_resolver.get_tint_info(stem)
            if tint_info.get("tint_type", 0) != 0 or tint_info.get("is_hardcoded") or tint_info.get("has_overlay"):
                chunk_has_tint = True

            overlay_stem = tint_info.get("overlay_texture")
            if overlay_stem:
                overlay_src = find_static_image_fn(overlay_stem, namespace=namespace_val, category=category_val)
                if overlay_src is not None:
                    if overlay_src.size != (target_w, target_w):
                        overlay_src = overlay_src.resize((target_w, target_w), Image.NEAREST)
                    if overlay_src.getbbox():
                        if overlay_img_canvas is None:
                            overlay_img_canvas = Image.new("RGBA", (chunk_width, chunk_height), (0, 0, 0, 0))
                        num_frames = max(1, target_h // target_w)
                        for f_idx in range(num_frames):
                            overlay_img_canvas.paste(overlay_src, (x_offset, f_idx * target_w))
                        chunk_has_overlay = True

            frame_width = int(metadata.get("width") or image.width) if isinstance(metadata, dict) else image.width
            frame_height = int(metadata.get("height") or frame_width) if isinstance(metadata, dict) else frame_width
            frametime = int(metadata.get("frametime", 1)) if isinstance(metadata, dict) else 1
            interpolate = bool(metadata.get("interpolate", False)) if isinstance(metadata, dict) else False
            frame_count = max(1, image.height // max(1, frame_height))

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
                "frame_count": frame_count,
                "frame_width": frame_width,
                "frame_height": frame_height,
                "tile_size": frame_width,
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
                "preview_frame": 0,
            }
            texture_locations[canonical_key] = anim_loc
            texture_locations[rel_p] = anim_loc
            texture_locations[clean_k] = anim_loc
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
            filename = f"{category_val}_chunk_{cat_chunk_index:03d}_{channel}.png"
            img_canvas.save(staging_dir / filename)
            files[channel] = filename

        chunks.append({
            "chunk_id": chunk_id,
            "category": category_val,
            "category_chunk_index": cat_chunk_index,
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
        if pending_columns and aligned_next_width > max_chunk_size:
            save_animation_chunk(pending_columns)
            pending_columns, pending_width = [], 0
            aligned_next_width = column_width
        pending_columns.append(column)
        pending_width = aligned_next_width
    if pending_columns:
        save_animation_chunk(pending_columns)
