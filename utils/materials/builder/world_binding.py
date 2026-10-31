"""Atlas chunk material binding for unified world meshes.

This is the orchestration layer; `bridge.world` only exposes the bridge-facing
entry point and metadata helpers.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from ....bridge.assets import (
    ensure_atlas_textures_extracted,
    get_cache_fingerprint,
    load_atlas_mapping_from_cache,
    load_baked_atlas_from_cache,
)
from ....bridge.material import resolve_chunk_texture_sources

logger = logging.getLogger("MoziToolKit.Materials.WorldBinding")


def _material_slot_chunk_ids(mesh: Any) -> list[int]:
    """Chunk id stored on each material slot, or -1 when unavailable."""
    result = []
    for mat in getattr(mesh, "materials", []):
        cid = mat.get("mtk_atlas_chunk_id") if mat is not None else None
        result.append(int(cid) if cid is not None else -1)
    return result


def face_chunk_ids(mesh: Any) -> Any:
    """Return per-face chunk ids, falling back to material-slot provenance.

    The face-level `mtk_atlas_chunk_id` attribute is kept stable for both
    internal and external meshes; material slots act as a fallback when it is
    absent.
    """
    import numpy as np

    num_polys = len(getattr(mesh, "polygons", []))
    attr = mesh.attributes.get("mtk_atlas_chunk_id") if hasattr(mesh, "attributes") else None
    if attr is not None and len(attr.data) == num_polys:
        raw = np.empty(num_polys, dtype=np.int32)
        attr.data.foreach_get("value", raw)
        return raw

    slot_chunks = _material_slot_chunk_ids(mesh)
    if not slot_chunks:
        raw = np.empty(num_polys, dtype=np.int32)
        mesh.polygons.foreach_get("material_index", raw)
        return raw

    slot_lut = np.asarray(slot_chunks, dtype=np.int32)
    if (slot_lut < 0).any():
        raw = np.empty(num_polys, dtype=np.int32)
        mesh.polygons.foreach_get("material_index", raw)
        return raw

    slot_indices = np.empty(num_polys, dtype=np.int32)
    mesh.polygons.foreach_get("material_index", slot_indices)
    np.clip(slot_indices, 0, len(slot_chunks) - 1, out=slot_indices)
    return slot_lut[slot_indices]


def ensure_world_materials(
    world_obj: Any,
    prefs=None,
    atlas: Optional[Any] = None,
    used_chunk_ids: Optional[Any] = None,
    dynamic_skin_atlas: Optional[Any] = None,
) -> None:
    """
    Ensures that the unified world mesh object has corresponding Atlas Chunk materials
    and shaders assigned for chunks actually present in the world geometry, hooking up
    albedo, normals, specular, emission, animated sprites, and biome tinting.
    Avoids loading textures or instantiating materials for unused atlas chunks.
    """
    try:
        import bpy
    except ImportError:
        return

    if not world_obj or world_obj.type != "MESH":
        return

    from .atlas_builder import PBR_LAYOUT_VERSION, build_atlas_chunk_material
    from .dynamic_skins import (
        DEFAULT_DYNAMIC_SKINS_CHUNK_ID,
        DYNAMIC_CHUNK_END,
        DYNAMIC_CHUNK_START,
        DYNAMIC_SKINS_IMAGE_NAME,
        build_dynamic_skins_material,
        dynamic_skins_image_name,
        dynamic_skins_material_name,
        update_dynamic_skins_image,
    )
    from . import ensure_material_node_tree
    from ..cleaner import remap_indices_lut

    atlas_dict: dict[int, Any] = {}
    if isinstance(dynamic_skin_atlas, dict):
        atlas_dict = {int(k): v for k, v in dynamic_skin_atlas.items()}
    elif dynamic_skin_atlas is not None:
        atlas_dict = {DEFAULT_DYNAMIC_SKINS_CHUNK_ID: dynamic_skin_atlas}

    for cid, buf in atlas_dict.items():
        update_dynamic_skins_image(buf, chunk_id=cid)

    mesh = world_obj.data

    # 1. Resolve which Chunk IDs are actually present in the mesh geometry
    target_chunk_ids: Optional[set[int]] = None
    if used_chunk_ids is not None:
        target_chunk_ids = {int(c) for c in used_chunk_ids}
    elif len(getattr(mesh, "polygons", [])) > 0:
        import numpy as np

        target_chunk_ids = {int(x) for x in np.unique(face_chunk_ids(mesh)).tolist()}

    # 0. Zero-cost Fast Path:
    # If the mesh has no polygons, or if target_chunk_ids is empty, nothing to bind
    if target_chunk_ids is not None and len(target_chunk_ids) == 0:
        return

    # If world_obj already has valid Atlas chunk materials assigned, check if we can fast-path:
    if target_chunk_ids is not None and len(mesh.materials) > 0:
        existing_chunk_to_slot: dict[int, int] = {}
        all_valid = True
        for s_idx, mat in enumerate(mesh.materials):
            if mat is None:
                all_valid = False
                break
            cid = mat.get("mtk_atlas_chunk_id")
            if cid is None:
                all_valid = False
                break
            if getattr(mat, "node_tree", None) is None or len(mat.node_tree.nodes) == 0:
                all_valid = False
                break
            existing_chunk_to_slot[int(cid)] = s_idx

        if all_valid and target_chunk_ids.issubset(existing_chunk_to_slot.keys()):
            for cid in target_chunk_ids:
                if DYNAMIC_CHUNK_START <= cid <= DYNAMIC_CHUNK_END:
                    skin_slot = existing_chunk_to_slot.get(cid)
                    if skin_slot is not None and skin_slot < len(mesh.materials):
                        skin_mat = mesh.materials[skin_slot]
                        if skin_mat and getattr(skin_mat, "node_tree", None):
                            tex_node = skin_mat.node_tree.nodes.get("DynamicAtlasTex")
                            if tex_node is not None:
                                img = bpy.data.images.get(dynamic_skins_image_name(cid))
                                if img is not None and (tex_node.image is None or cid in atlas_dict):
                                    tex_node.image = img
            has_chunk_attr = hasattr(mesh, "attributes") and "mtk_atlas_chunk_id" in mesh.attributes
            is_identity_mapping = all(existing_chunk_to_slot[cid] == cid for cid in target_chunk_ids)

            # Fast Path A: Single used chunk (common case for incremental/localized sync)
            if len(target_chunk_ids) == 1:
                only_cid = next(iter(target_chunk_ids))
                target_slot = existing_chunk_to_slot[only_cid]
                num_polys = len(getattr(mesh, "polygons", []))
                if num_polys == 0:
                    return
                try:
                    # Single-chunk mesh faces all map to target_slot; direct fill without reading back mesh
                    import numpy as np
                    mesh.polygons.foreach_set("material_index", np.full(num_polys, target_slot, dtype=np.int32))
                except Exception as e:
                    logger.debug("Failed setting single chunk material index: %s", e)
                return

            # Multi-chunk remapping: Fast identity copy or dictionary/LUT remapping
            if hasattr(mesh, "polygons") and len(mesh.polygons) > 0:
                try:
                    import numpy as np
                    raw_cids = face_chunk_ids(mesh)
                    if is_identity_mapping:
                        # Direct assignment when slot indices match chunk IDs identically
                        mesh.polygons.foreach_set("material_index", raw_cids.astype(np.int32, copy=False))
                    elif remap_indices_lut is not None:
                        remapped = remap_indices_lut(raw_cids, existing_chunk_to_slot, default_value=0)
                        mesh.polygons.foreach_set("material_index", remapped)
                    else:
                        remapped = np.array([existing_chunk_to_slot.get(int(cid), 0) for cid in raw_cids], dtype=np.int32)
                        mesh.polygons.foreach_set("material_index", remapped)
                except Exception as e:
                    logger.debug("Failed remapping polygon material indices in fast path: %s", e)
            return

    atlas_dir = ensure_atlas_textures_extracted(prefs)
    atlas_mapping_path = atlas_dir / "atlas_mapping.json"

    # 2. Bind Precompiled Atlas Chunk Materials for used chunks only
    active_atlas = atlas or load_baked_atlas_from_cache(prefs)
    atlas_data = None
    if active_atlas is None:
        atlas_data = load_atlas_mapping_from_cache(prefs)

    if (active_atlas is not None or atlas_data is not None or atlas_mapping_path.exists()) and build_atlas_chunk_material is not None:
        try:
            # Query chunk metadata from BakedAtlas (Rust SSOT) or fallback to mapping JSON
            chunk_meta_map: dict[int, dict[str, Any]] = {}
            if active_atlas is not None and hasattr(active_atlas, "get_chunk_info"):
                if target_chunk_ids is not None:
                    for cid in sorted(target_chunk_ids):
                        cm = active_atlas.get_chunk_info(cid)
                        if cm is not None:
                            chunk_meta_map[cid] = cm
                else:
                    all_chunks = active_atlas.get_all_chunks_info() if hasattr(active_atlas, "get_all_chunks_info") else []
                    for cm in all_chunks:
                        chunk_meta_map[cm["chunk_id"]] = cm
            else:
                if atlas_data is None and atlas_mapping_path.exists():
                    atlas_data = json.loads(atlas_mapping_path.read_text(encoding="utf-8"))
                if atlas_data is not None:
                    for idx, cm in enumerate(atlas_data.get("chunks", [])):
                        cid = cm.get("chunk_id", idx)
                        if target_chunk_ids is None or cid in target_chunk_ids:
                            chunk_meta_map[cid] = cm

            if target_chunk_ids is not None:
                for cid in target_chunk_ids:
                    if DYNAMIC_CHUNK_START <= cid <= DYNAMIC_CHUNK_END:
                        chunk_meta_map[cid] = {
                            "chunk_id": cid,
                            "is_dynamic_skins": True,
                        }

            if chunk_meta_map:
                manifest_fp = get_cache_fingerprint(prefs)

                sorted_chunks = sorted(chunk_meta_map.keys())
                chunk_to_compact_slot: dict[int, int] = {}
                compact_materials: list[Any] = []

                for slot_idx, chunk_id in enumerate(sorted_chunks):
                    cm = chunk_meta_map[chunk_id]
                    if cm.get("is_dynamic_skins") or DYNAMIC_CHUNK_START <= chunk_id <= DYNAMIC_CHUNK_END:
                        buf = atlas_dict.get(chunk_id)
                        mat = build_dynamic_skins_material(chunk_id=chunk_id, dynamic_skin_atlas_bytes=buf)
                        compact_materials.append(mat)
                        chunk_to_compact_slot[chunk_id] = slot_idx
                        continue

                    cat = cm.get("category", "blocks")
                    c_idx = cm.get("category_chunk_index", chunk_id + 1)
                    is_anim = cm.get("is_animated", False)
                    stem = cm.get("file_stem") or (f"{cat}_anim_chunk_{c_idx:03}" if is_anim else f"{cat}_chunk_{c_idx:03}")

                    chunk_width = float(cm.get("width", 4096))
                    chunk_height = float(cm.get("height", 4096))

                    # Fast path: if material already exists in Blender and fingerprint matches, reuse directly
                    mat_name = f"MTK:Atlas:{cat}:anim:{c_idx:03}" if is_anim else f"MTK:Atlas:{cat}:{c_idx:03}"
                    existing_mat = bpy.data.materials.get(mat_name)
                    is_stale_fp = bool(
                        existing_mat is not None
                        and manifest_fp
                        and existing_mat.get("mtk_stack_fingerprint") != manifest_fp
                    )
                    is_stale_layout = bool(
                        existing_mat is not None
                        and existing_mat.get("mtk_pbr_layout") != PBR_LAYOUT_VERSION
                    )
                    if (
                        existing_mat is not None
                        and not is_stale_fp
                        and not is_stale_layout
                        and getattr(existing_mat, "node_tree", None)
                        and len(existing_mat.node_tree.nodes) > 0
                        and existing_mat.get("mtk_atlas_chunk_id") == chunk_id
                    ):
                        compact_materials.append(existing_mat)
                        chunk_to_compact_slot[chunk_id] = slot_idx
                        continue

                    # World meshes are greedy-meshed per block face, so every face maps 1:1 to
                    # its atlas sprite and the UVMap can drive the texture directly. The
                    # `mtk_uv_transform` / `mtk_uv_rotation` attribute path below is reserved for
                    # imported external meshes, where UVs must be tiled in the shader
                    # (see utils/materials/pipeline.py, use_attribute_node=True).
                    enable_biome_tint = bool(cm.get("has_tint", True)) if cat == "blocks" else False
                    texture_sources = resolve_chunk_texture_sources(
                        cm,
                        atlas_dir=atlas_dir,
                        active_atlas=active_atlas,
                    )
                    mat = build_atlas_chunk_material(
                        chunk_id=chunk_id,
                        category=cat,
                        category_chunk_index=c_idx,
                        is_animated=is_anim,
                        stack_fingerprint=manifest_fp,
                        enable_biome_tint=enable_biome_tint,
                        use_attribute_node=False,
                        atlas_width=chunk_width,
                        atlas_height=chunk_height,
                        tile_width=16.0,
                        tile_height=16.0,
                        chunk_stem=stem,
                        texture_sources=texture_sources,
                    )
                    compact_materials.append(mat)
                    chunk_to_compact_slot[chunk_id] = slot_idx

                # Reconstruct mesh.materials only if slots actually changed
                curr_mats = list(mesh.materials)
                if curr_mats != compact_materials:
                    mesh.materials.clear()
                    for mat in compact_materials:
                        mesh.materials.append(mat)

                # CRITICAL: Remap polygon material_index AFTER materials are populated
                # Retrieve authoritative face chunk IDs from mtk_atlas_chunk_id attribute if available
                if hasattr(mesh, "polygons") and len(mesh.polygons) > 0:
                    num_polys = len(mesh.polygons)
                    if len(sorted_chunks) == 1:
                        try:
                            import numpy as np
                            mesh.polygons.foreach_set("material_index", np.zeros(num_polys, dtype=np.int32))
                        except Exception as e:
                            logger.debug("Failed setting single material slot 0: %s", e)
                    else:
                        try:
                            import numpy as np
                            raw_cids = face_chunk_ids(mesh)

                            if remap_indices_lut is not None:
                                remapped = remap_indices_lut(raw_cids, chunk_to_compact_slot, default_value=0)
                            else:
                                remapped = np.array([chunk_to_compact_slot.get(int(cid), 0) for cid in raw_cids], dtype=np.int32)
                            mesh.polygons.foreach_set("material_index", remapped)
                        except Exception as e:
                            logger.debug("Failed remapping polygon material indices: %s", e)
                            for idx, p in enumerate(mesh.polygons):
                                if hasattr(mesh, "attributes") and "mtk_atlas_chunk_id" in mesh.attributes:
                                    raw_cid = mesh.attributes["mtk_atlas_chunk_id"].data[idx].value
                                else:
                                    raw_cid = getattr(p, "material_index", 0)
                                p.material_index = chunk_to_compact_slot.get(int(raw_cid), 0)

                if len(mesh.materials) > 0:
                    return
        except Exception as e:
            logger.warning(f"Failed binding Atlas chunk materials: {e}")


    # 2. Fallback: Default shaded material with vertex colors / AO
    default_mat_name = "MTK:Default:AO"
    mat = bpy.data.materials.get(default_mat_name)
    if mat is None:
        mat = bpy.data.materials.new(name=default_mat_name)
        ensure_material_node_tree(mat)
        nodes = mat.node_tree.nodes
        nodes.clear()
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (200, 0)
        output = nodes.new("ShaderNodeOutputMaterial")
        output.location = (500, 0)
        mat.node_tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

        attr_node = nodes.new("ShaderNodeAttribute")
        attr_node.location = (-150, 0)
        attr_node.attribute_name = "color"
        mat.node_tree.links.new(attr_node.outputs["Color"], bsdf.inputs["Base Color"])

    mesh.materials.clear()
    mesh.materials.append(mat)



_WORLD_SESSIONS: Dict[str, Any] = {}
_WORLD_SESSION_META: Dict[str, Dict[str, Any]] = {}


