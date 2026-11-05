"""
MoziToolKit Scene Interchange Material Builder.

Constructs canonical Principled BSDF materials using the compact Scene Mini-Atlas
embedded in .mtkscene packages. Adheres strictly to the Canonical PBR Pipeline
(Rule 5) and Blender 4.2+ / 5.x / 6.0 standards (Rule 6).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import bpy

logger = logging.getLogger("MoziToolKit.Scene.Materials")


def bind_scene_materials(
    mesh_obj: Any,
    reader: Any,
    scene_name: str = "Scene",
    atlas: Optional[Any] = None,
    prefs: Optional[Any] = None,
    used_chunk_ids: Optional[Any] = None,
    dynamic_entity_atlases: Optional[Any] = None,
) -> List[Any]:
    """
    Reads mini-atlas texture chunks from the ScenePackageReader, creates in-memory
    Blender images, builds canonical PBR materials, and binds them to the mesh slots.
    Delegates to the authoritative ensure_world_materials pipeline.
    """
    if mesh_obj is None or reader is None:
        return []

    active_atlas = atlas
    if active_atlas is None and hasattr(reader, "read_atlas"):
        try:
            active_atlas = reader.read_atlas()
        except Exception:
            pass

    from ..materials.builder.world_binding import ensure_world_materials

    ensure_world_materials(
        mesh_obj,
        prefs=prefs,
        atlas=active_atlas,
        used_chunk_ids=used_chunk_ids,
        dynamic_entity_atlases=dynamic_entity_atlases,
        clean_unused_slots=True,
        package_reader=reader,
    )

    mesh = getattr(mesh_obj, "data", None)
    return list(getattr(mesh, "materials", [])) if mesh else []
