"""Atlas chunk material binding for unified world meshes.

This is the orchestration layer; `bridge.world` only exposes the bridge-facing
entry point and metadata helpers.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

try:
    from ....bridge.assets import (
        ensure_atlas_textures_extracted,
        ensure_colormaps_extracted,
        get_cache_fingerprint,
        load_atlas_mapping_from_cache,
        load_baked_atlas_from_cache,
    )
except (ImportError, ValueError):
    from bridge.assets import (
        ensure_atlas_textures_extracted,
        ensure_colormaps_extracted,
        get_cache_fingerprint,
        load_atlas_mapping_from_cache,
        load_baked_atlas_from_cache,
    )

logger = logging.getLogger("MoziToolKit.Materials.WorldBinding")


def ensure_world_materials(
    world_obj: Any,
    prefs=None,
    atlas: Optional[Any] = None,
    used_chunk_ids: Optional[Any] = None,
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

    try:
        from .atlas_builder import build_atlas_chunk_material
        from . import ensure_material_node_tree
    except (ImportError, ValueError):
        try:
            from .atlas_builder import build_atlas_chunk_material
            from . import ensure_material_node_tree
        except (ImportError, ValueError):
            build_atlas_chunk_material = None
            ensure_material_node_tree = lambda m: getattr(m, "node_tree", None)

    try:
        from ..cleaner import remap_indices_lut
    except (ImportError, ValueError):
        try:
            from ..cleaner import remap_indices_lut
        except (ImportError, ValueError):
            remap_indices_lut = None

    mesh = world_obj.data

    # 1. Resolve which Chunk IDs are actually present in the mesh geometry
    target_chunk_ids: Optional[set[int]] = None
    if used_chunk_ids is not None:
        target_chunk_ids = {int(c) for c in used_chunk_ids}
    elif hasattr(mesh, "attributes") and "mtk_atlas_chunk_id" in mesh.attributes:
        try:
            import numpy as np
            raw_cids = np.empty(len(mesh.polygons), dtype=np.int32)
            mesh.attributes["mtk_atlas_chunk_id"].data.foreach_get("value", raw_cids)
            target_chunk_ids = {int(x) for x in np.unique(raw_cids).tolist()}
        except Exception:
            target_chunk_ids = {int(getattr(d, "value", 0)) for d in mesh.attributes["mtk_atlas_chunk_id"].data}
    elif hasattr(mesh, "polygons") and len(mesh.polygons) > 0:
        if hasattr(mesh.polygons, "foreach_get"):
            try:
                import numpy as np
                poly_mats = np.empty(len(mesh.polygons), dtype=np.int32)
                mesh.polygons.foreach_get("material_index", poly_mats)
                target_chunk_ids = {int(x) for x in np.unique(poly_mats).tolist()}
            except Exception:
                try:
                    poly_mats = [0] * len(mesh.polygons)
                    mesh.polygons.foreach_get("material_index", poly_mats)
                    target_chunk_ids = {int(x) for x in poly_mats}
                except Exception:
                    target_chunk_ids = {getattr(p, "material_index", 0) for p in mesh.polygons}
        else:
            target_chunk_ids = {getattr(p, "material_index", 0) for p in mesh.polygons}

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
            has_chunk_attr = hasattr(mesh, "attributes") and "mtk_atlas_chunk_id" in mesh.attributes
            is_identity_mapping = all(existing_chunk_to_slot[cid] == cid for cid in target_chunk_ids)

            # If identity mapping AND no separate mtk_atlas_chunk_id attribute overriding polygons,
            # then inject_face_materials_standard has already set the exact material_index.
            # We can return immediately with zero operations, zero disk reads, and zero cache hashing!
            if is_identity_mapping and not has_chunk_attr:
                return

            # Otherwise, if slot indices differ or mtk_atlas_chunk_id is present, remap polygon indices:
            if hasattr(mesh, "polygons") and len(mesh.polygons) > 0:
                num_polys = len(mesh.polygons)
                try:
                    import numpy as np
                    if has_chunk_attr:
                        raw_cids = np.empty(num_polys, dtype=np.int32)
                        mesh.attributes["mtk_atlas_chunk_id"].data.foreach_get("value", raw_cids)
                    else:
                        raw_cids = np.empty(num_polys, dtype=np.int32)
                        mesh.polygons.foreach_get("material_index", raw_cids)

                    if remap_indices_lut is not None:
                        remapped = remap_indices_lut(raw_cids, existing_chunk_to_slot, default_value=0)
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

            if chunk_meta_map:
                colormaps = ensure_colormaps_extracted(prefs)
                manifest_fp = get_cache_fingerprint(prefs)

                sorted_chunks = sorted(chunk_meta_map.keys())
                chunk_to_compact_slot: dict[int, int] = {}
                compact_materials: list[Any] = []

                for slot_idx, chunk_id in enumerate(sorted_chunks):
                    cm = chunk_meta_map[chunk_id]
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
                    if (
                        existing_mat is not None
                        and not is_stale_fp
                        and getattr(existing_mat, "node_tree", None)
                        and len(existing_mat.node_tree.nodes) > 0
                        and existing_mat.get("mtk_atlas_chunk_id") == chunk_id
                    ):
                        compact_materials.append(existing_mat)
                        chunk_to_compact_slot[chunk_id] = slot_idx
                        continue

                    albedo_file: Any = atlas_dir / f"{stem}.png"
                    normal_file: Any = atlas_dir / f"{stem}_n.png" if cm.get("has_normal") else None
                    specular_file: Any = atlas_dir / f"{stem}_s.png" if cm.get("has_specular") else None
                    overlay_file: Any = atlas_dir / f"{stem}_overlay.png" if cm.get("has_overlay") else None

                    # If file doesn't exist on disk, stream in-memory from active BakedAtlas if available
                    if not albedo_file.exists() and active_atlas is not None and hasattr(active_atlas, "get_chunk_albedo_f32"):
                        try:
                            c_order_idx = cm.get("chunk_id", chunk_id)
                            albedo_f32 = active_atlas.get_chunk_albedo_f32(c_order_idx, flip_v=True)
                            if albedo_f32 is not None:
                                albedo_file = (int(chunk_width), int(chunk_height), albedo_f32)
                            if normal_file and hasattr(active_atlas, "get_chunk_normal_f32"):
                                n_f32 = active_atlas.get_chunk_normal_f32(c_order_idx, flip_v=True)
                                if n_f32 is not None:
                                    normal_file = (int(chunk_width), int(chunk_height), n_f32)
                            if specular_file and hasattr(active_atlas, "get_chunk_specular_f32"):
                                s_f32 = active_atlas.get_chunk_specular_f32(c_order_idx, flip_v=True)
                                if s_f32 is not None:
                                    specular_file = (int(chunk_width), int(chunk_height), s_f32)
                            if overlay_file and hasattr(active_atlas, "get_chunk_overlay_f32"):
                                o_f32 = active_atlas.get_chunk_overlay_f32(c_order_idx, flip_v=True)
                                if o_f32 is not None:
                                    overlay_file = (int(chunk_width), int(chunk_height), o_f32)
                        except Exception:
                            pass

                    # World meshes are greedy-meshed per block face, so every face maps 1:1 to
                    # its atlas sprite and the UVMap can drive the texture directly. The
                    # `mtk_uv_transform` / `mtk_uv_rotation` attribute path below is reserved for
                    # imported external meshes, where UVs must be tiled in the shader
                    # (see utils/materials/pipeline.py, use_attribute_node=True).
                    mat = build_atlas_chunk_material(
                        chunk_id=chunk_id,
                        albedo_path=albedo_file,
                        normal_path=normal_file,
                        specular_path=specular_file,
                        overlay_path=overlay_file,
                        colormaps=colormaps,
                        category=cat,
                        category_chunk_index=c_idx,
                        is_animated=is_anim,
                        stack_fingerprint=manifest_fp,
                        use_attribute_node=False,
                        atlas_width=chunk_width,
                        atlas_height=chunk_height,
                        tile_width=16.0,
                        tile_height=16.0,
                        chunk_stem=stem,
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
                    try:
                        import numpy as np
                        if hasattr(mesh, "attributes") and "mtk_atlas_chunk_id" in mesh.attributes:
                            raw_cids = np.empty(num_polys, dtype=np.int32)
                            mesh.attributes["mtk_atlas_chunk_id"].data.foreach_get("value", raw_cids)
                        else:
                            raw_cids = np.empty(num_polys, dtype=np.int32)
                            mesh.polygons.foreach_get("material_index", raw_cids)

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


