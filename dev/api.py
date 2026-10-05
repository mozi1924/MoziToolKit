"""
MoziToolKit Dev API.
Headless programmatic interface for Agent MCP execution, automated testing,
and visual benchmarking inside a running Blender instance.
"""

from typing import Any, Dict, Optional
import time

from .loader import get_engine_status
from .. import bridge


def get_diagnostics() -> Dict[str, Any]:
    """Returns runtime diagnostic information including native engine status and cache state."""
    info = get_engine_status()
    try:
        cache_stats = bridge.get_cache_stats()
        info["cache"] = cache_stats
    except Exception as e:
        info["cache_error"] = str(e)

    info["debug_world_available"] = bridge.is_debug_world_available()
    return info


def load_debug_world(
    context=None,
    name: str = "MTK_Debug_World",
    enable_ao: bool = True,
    mesh_fluids: bool = True,
    weld_vertices: bool = True,
    origin_centered: bool = True,
    reuse_existing: bool = True,
    prefs=None,
) -> Any:
    """
    Instantly meshes and loads the embedded Minecraft debug world (32,539 blocks)
    into the active Blender scene with full model resolution, atlas UV remapping,
    and Atlas chunk PBR materials. Returns the created/updated bpy.types.Object.
    """
    obj, stats = bridge.create_debug_world_object(
        context=context,
        name=name,
        enable_ao=enable_ao,
        mesh_fluids=mesh_fluids,
        weld_vertices=weld_vertices,
        origin_centered=origin_centered,
        reuse_existing=reuse_existing,
        prefs=prefs,
    )
    return obj


def run_mesher_benchmark(
    iterations: int = 3,
    with_models: bool = True,
    num_threads: Optional[int] = None,
    prefs=None,
) -> Dict[str, Any]:
    """
    Benchmarks raw meshing throughput for the 32k-block debug world.
    When with_models is True (default), runs full block model baking + atlas UV remapping.
    Returns timing statistics and polygon generation rate.
    """
    if not bridge.is_debug_world_available():
        raise RuntimeError("Native libmtk_py embedded debug world is unavailable.")

    if prefs is None:
        try:
            from ..utils.system.dependencies import get_prefs
            prefs = get_prefs()
        except Exception:
            pass

    storage = bridge.load_debug_world_storage()

    durations = []
    mesh_data = None
    for _ in range(iterations):
        m, elapsed_ms = bridge.generate_debug_world_mesh(
            storage=storage,
            with_models=with_models,
            prefs=prefs,
            num_threads=num_threads,
        )
        durations.append(elapsed_ms)
        mesh_data = m

    avg_ms = sum(durations) / len(durations)
    quads = mesh_data.quad_count if mesh_data else 0
    verts = mesh_data.vertex_count if mesh_data else 0

    quads_per_sec = (quads / (avg_ms / 1000.0)) if avg_ms > 0 else 0

    return {
        "iterations": iterations,
        "with_models": with_models,
        "avg_ms": round(avg_ms, 2),
        "min_ms": round(min(durations), 2),
        "max_ms": round(max(durations), 2),
        "quad_count": quads,
        "vertex_count": verts,
        "quads_per_second": int(quads_per_sec),
    }


def clear_material_cache(prefs=None) -> int:
    """Clears all precompiled material and model caches via bridge."""
    return bridge.clear_cache(prefs)


def precompile_material_cache(prefs=None, num_threads: Optional[int] = None) -> Dict[str, Any]:
    """Precompiles and rebuilds complete material atlas, standalone textures, and model caches via bridge."""
    return bridge.precompile_stack(prefs, num_threads=num_threads)

