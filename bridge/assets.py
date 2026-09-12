"""
Bridge: Asset Precompilation & Resource Stack Management.
Transfers resource pack configuration from Blender to libmtk (Rust) for
headless Atlas stitching, Standalone material generation, and Model baking.
Zero-computation on the Python side: all parsing, packing, image decoding,
and geometric meshing are handled entirely within libmtk.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.system import ensure_sys_paths, get_prefs

ensure_sys_paths()

try:
    import libmtk_py
    HAS_LIBMTK = True
except ImportError:
    libmtk_py = None
    HAS_LIBMTK = False


def get_cache_dir(prefs=None) -> Path:
    """
    Returns the persistent cache directory for compiled assets.
    Delegates path resolution to the host (Blender/Python):
    1. Environment override (`MOZI_CACHE_DIR`) for test sandboxing / isolation.
    2. User-customized path in AddonPreferences (`prefs.cache_dir`).
    3. Blender standard plugin user data directory:
       `bpy.utils.user_resource("DATAFILES") / "MoziToolKit" / "cache"`
    4. Fallback to `~/.config/blender/MoziToolKit/cache`.
    """
    # 1. Environment sandbox override
    env_dir = os.environ.get("MOZI_CACHE_DIR")
    if env_dir:
        p = Path(env_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    # 2. Custom preference path if configured by user
    if prefs is None:
        try:
            prefs = get_prefs()
        except Exception:
            prefs = None

    if prefs is not None and hasattr(prefs, "cache_dir"):
        custom_path = getattr(prefs, "cache_dir", "").strip()
        if custom_path:
            try:
                import bpy
                resolved = bpy.path.abspath(custom_path)
            except Exception:
                resolved = custom_path
            p = Path(resolved)
            p.mkdir(parents=True, exist_ok=True)
            return p

    # 3. Blender standard plugin user data directory
    cache_dir = None
    try:
        import bpy
        if hasattr(bpy, "utils") and hasattr(bpy.utils, "user_resource"):
            cache_dir = Path(bpy.utils.user_resource("DATAFILES")) / "MoziToolKit" / "cache"
    except Exception:
        cache_dir = None

    if not cache_dir:
        cache_dir = Path.home() / ".config" / "blender" / "MoziToolKit" / "cache"

    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_configured_pack_stack(prefs=None) -> Optional[Any]:
    """
    Builds a libmtk ResourcePackStack from the Blender preferences configuration.
    Traverses enabled entries in order and pushes them to Rust.
    """
    if not HAS_LIBMTK:
        return None

    if prefs is None:
        prefs = get_prefs()

    stack = libmtk_py.ResourcePackStack()

    if prefs is None or not hasattr(prefs, "resource_packs"):
        return stack

    for entry in prefs.resource_packs:
        if not getattr(entry, "enabled", True):
            continue

        raw_path = getattr(entry, "path", "").strip()
        if not raw_path:
            continue

        p = Path(raw_path)
        if not p.exists():
            continue

        name = getattr(entry, "name", None) or p.stem

        if p.is_dir():
            stack.add_directory_pack(str(p.resolve()), name)
        elif p.is_file() and p.suffix.lower() in {".zip", ".jar"}:
            stack.add_zip_pack(str(p.resolve()))

    return stack


def precompile_stack(prefs=None) -> Dict[str, Any]:
    """
    Executes end-to-end asset precompilation via libmtk:
    1. Compiles blocks Atlas and saves all chunk PNGs + atlas_mapping.json
    2. Precompiles Standalone PBR textures + standalone_mapping.json
    3. Bakes representative/custom block models
    Returns a summary dictionary of compiled assets.
    """
    if not HAS_LIBMTK:
        raise RuntimeError("libmtk_py (Rust backend) is not installed or available.")

    stack = get_configured_pack_stack(prefs)
    if stack is None or stack.get_pack_count() == 0:
        raise ValueError("No valid enabled resource packs or JARs found in the active stack.")

    base_cache = get_cache_dir()
    atlas_dir = base_cache / "atlas"
    standalone_dir = base_cache / "standalone"
    models_dir = base_cache / "models"

    atlas_dir.mkdir(parents=True, exist_ok=True)
    standalone_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    # 1. Atlas Baking via libmtk (Pure In-Memory -> Host Disk Persistence)
    atlas_builder = libmtk_py.AtlasBuilder(4096, 4096, 0, 0)
    baked_atlas = atlas_builder.build(stack, "blocks")
    chunk_count = baked_atlas.get_chunk_count()

    # Save mapping JSON
    (atlas_dir / "atlas_mapping.json").write_text(baked_atlas.to_mapping_json(), encoding="utf-8")

    # Save Atlas chunk images
    for i in range(chunk_count):
        _, _, _, _, stem = baked_atlas.get_chunk_meta(i)
        albedo_bytes = baked_atlas.get_chunk_albedo_png_bytes(i)
        (atlas_dir / f"{stem}.png").write_bytes(albedo_bytes)

        normal_bytes = baked_atlas.get_chunk_normal_png_bytes(i)
        if normal_bytes is not None:
            (atlas_dir / f"{stem}_n.png").write_bytes(normal_bytes)

        specular_bytes = baked_atlas.get_chunk_specular_png_bytes(i)
        if specular_bytes is not None:
            (atlas_dir / f"{stem}_s.png").write_bytes(specular_bytes)

    # 2. Standalone Baking via libmtk
    sa_builder = libmtk_py.StandaloneBuilder()
    sa_res = sa_builder.build(stack, str(standalone_dir.resolve()))

    # 3. Model Baking via libmtk (Pure In-Memory ModelBaker)
    baker = libmtk_py.ModelBaker()
    core_states = [
        "minecraft:stone",
        "minecraft:oak_planks",
        "minecraft:glass",
        "minecraft:furnace[facing=north,lit=false]",
        "minecraft:furnace[facing=east,lit=true]",
        "minecraft:observer[facing=up,powered=false]",
        "minecraft:oak_stairs[facing=east,half=bottom,shape=straight]",
        "minecraft:oak_trapdoor[facing=north,half=bottom,open=false,powered=false,waterlogged=false]",
        "minecraft:torch",
        "minecraft:lantern[hanging=false,waterlogged=false]",
    ]
    baked_models_count = 0
    for state_str in core_states:
        try:
            mesh_data, textures = baker.bake_blockstate(stack, state_str, True)
            if mesh_data and mesh_data.vertex_count > 0:
                baked_models_count += 1
        except Exception:
            pass

    # Refresh cached statistics once after precompilation
    get_cache_stats(prefs, force_refresh=True)

    return {
        "success": True,
        "pack_count": stack.get_pack_count(),
        "atlas_chunks": chunk_count,
        "standalone_textures": sa_res.texture_count,
        "baked_models": baked_models_count,
        "cache_dir": str(base_cache),
    }


_cached_cache_stats: Optional[Dict[str, Any]] = None
_cached_cache_stats_path: Optional[str] = None


def get_cache_stats(prefs=None, force_refresh: bool = False) -> Dict[str, Any]:
    """
    Computes total storage footprint and file count for the asset cache.
    Results are cached in-memory to prevent UI redraw stutter during continuous render loops.
    Scans only on-demand when explicitly requested or after cache mutations.
    """
    global _cached_cache_stats, _cached_cache_stats_path
    cache_path = get_cache_dir(prefs)
    path_str = str(cache_path)

    if (
        not force_refresh
        and _cached_cache_stats is not None
        and _cached_cache_stats_path == path_str
    ):
        return _cached_cache_stats

    total_size = 0
    file_count = 0

    if cache_path.exists():
        for root, _, files in os.walk(cache_path):
            for f in files:
                fp = Path(root) / f
                try:
                    total_size += fp.stat().st_size
                    file_count += 1
                except Exception:
                    pass

    # Human-readable formatted size
    if total_size < 1024:
        size_str = f"{total_size} B"
    elif total_size < 1024 * 1024:
        size_str = f"{total_size / 1024:.1f} KB"
    elif total_size < 1024 * 1024 * 1024:
        size_str = f"{total_size / (1024 * 1024):.1f} MB"
    else:
        size_str = f"{total_size / (1024 * 1024 * 1024):.2f} GB"

    _cached_cache_stats = {
        "path": path_str,
        "size_bytes": total_size,
        "size_formatted": size_str,
        "files_count": file_count,
    }
    _cached_cache_stats_path = path_str
    return _cached_cache_stats


def clear_cache(prefs=None) -> None:
    """Empties all compiled caches in the cache directory."""
    global _cached_cache_stats, _cached_cache_stats_path
    cache_path = get_cache_dir(prefs)
    if cache_path.exists():
        for item in cache_path.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except Exception:
                pass

    _cached_cache_stats = {
        "path": str(cache_path),
        "size_bytes": 0,
        "size_formatted": "0 B",
        "files_count": 0,
    }
    _cached_cache_stats_path = str(cache_path)


def open_cache_folder(prefs=None) -> None:
    """Opens the cache directory in the host system's file explorer using Blender or OS."""
    cache_path = get_cache_dir(prefs)
    try:
        import bpy
        if hasattr(bpy.ops.wm, "path_open"):
            bpy.ops.wm.path_open(filepath=str(cache_path.resolve()))
            return
    except Exception:
        pass

    if sys.platform == "win32":
        os.startfile(str(cache_path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(cache_path)])
    else:
        subprocess.Popen(["xdg-open", str(cache_path)])

