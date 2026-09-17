"""
MoziToolKit Material Replacement & Provenance Pipeline.
Executes pure Rust (libmtk) material resolution, UV remapping,
LabPBR 1.3 shader construction, and mesh attribute synchronization.
"""

from __future__ import annotations

import array
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

try:
    from ...utils.system.dependencies import ensure_sys_paths
    ensure_sys_paths()
except (ImportError, ValueError):
    try:
        from utils.system.dependencies import ensure_sys_paths
        ensure_sys_paths()
    except Exception:
        pass

try:
    import libmtk_py
    HAS_LIBMTK = True
except ImportError:
    libmtk_py = None
    HAS_LIBMTK = False

try:
    from ...bridge.assets import get_cache_dir, precompile_stack
    from ...bridge.mesh import _get_mesh
    from .builder.atlas_builder import build_atlas_chunk_material
    from .builder.standalone_builder import build_standalone_material
    from .matching.presets.registry import build_matching_context
    from .biome import (
        BiomeResolver,
        get_or_load_biome_resolver,
        compute_biome_tint_attributes,
        apply_biome_tint_attributes,
    )
    from .constants import (
        ATTR_SOURCE_TEXTURE_KEY,
        ATTR_MATERIAL_SLOT,
        ATTR_ATLAS_CHUNK_ID,
        ATTR_ATLAS_TEXTURE_ID,
        ATTR_UV_MODE,
        ATTR_UV_TILING_TRANSFORM,
        ATTR_UV_TRANSFORM,
        ATTR_UV_ROTATION,
        ATTR_BIOME_TINT_DATA,
        ATTR_BIOME_TINT_COLOR,
        ATTR_COLORMAP_UV,
    )
except (ImportError, ValueError):
    from bridge.assets import get_cache_dir, precompile_stack
    from bridge.mesh import _get_mesh
    from utils.materials.builder.atlas_builder import build_atlas_chunk_material
    from utils.materials.builder.standalone_builder import build_standalone_material
    from utils.materials.matching.presets.registry import build_matching_context
    try:
        from utils.materials.biome import (
            BiomeResolver,
            get_or_load_biome_resolver,
            compute_biome_tint_attributes,
            apply_biome_tint_attributes,
        )
        from utils.materials.constants import (
            ATTR_SOURCE_TEXTURE_KEY,
            ATTR_MATERIAL_SLOT,
            ATTR_ATLAS_CHUNK_ID,
            ATTR_ATLAS_TEXTURE_ID,
            ATTR_UV_MODE,
            ATTR_UV_TILING_TRANSFORM,
            ATTR_UV_TRANSFORM,
            ATTR_UV_ROTATION,
            ATTR_BIOME_TINT_DATA,
            ATTR_BIOME_TINT_COLOR,
            ATTR_COLORMAP_UV,
        )
    except Exception:
        pass



def ensure_stack_precompiled(prefs=None) -> Path:
    """Ensure asset caches (Atlas & Standalone) exist in persistent storage."""
    base_cache = get_cache_dir(prefs)
    atlas_mapping = base_cache / "atlas" / "atlas_mapping.json"
    standalone_mapping = base_cache / "standalone" / "standalone_mapping.json"

    if not atlas_mapping.exists() or not standalone_mapping.exists():
        precompile_stack(prefs)

    return base_cache


def replace_materials(
    mesh_or_obj: Any,
    mode: str = "ATLAS",
    origin: str = "AUTO",
    biome: str = "PLAINS",
    prefs: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Executes end-to-end material replacement on a Blender mesh object using libmtk Rust backend.

    Args:
        mesh_or_obj: A `bpy.types.Object` (type MESH) or `bpy.types.Mesh`.
        mode: Material mode - "ATLAS" or "STANDALONE".
        origin: Format heuristic - "AUTO", "MINEWAYS", "JMC2OBJ", "ICE_CUBE", "GENERIC".
        biome: Biome preset name (e.g. "PLAINS", "BADLANDS", "DESERT").
        prefs: Add-on preferences reference.

    Returns:
        Summary dict containing processed face count, material slots, unmapped count, etc.
    """
    if not HAS_BPY:
        raise RuntimeError("Blender (bpy) is required to execute replace_materials.")
    if not HAS_LIBMTK:
        raise RuntimeError("libmtk_py (Rust backend) is not installed or available.")

    mesh = _get_mesh(mesh_or_obj)
    if mesh is None or len(mesh.polygons) == 0:
        return {"success": False, "message": "Mesh has no geometry or polygons."}

    base_cache = ensure_stack_precompiled(prefs)
    atlas_dir = base_cache / "atlas"
    standalone_dir = base_cache / "standalone"
    colormaps_dir = base_cache / "colormaps"

    atlas_mapping_path = atlas_dir / "atlas_mapping.json"
    standalone_mapping_path = standalone_dir / "standalone_mapping.json"

    if not atlas_mapping_path.exists():
        raise FileNotFoundError(f"Atlas mapping missing at {atlas_mapping_path}")

    atlas_json_str = atlas_mapping_path.read_text(encoding="utf-8")
    atlas_data = json.loads(atlas_json_str)
    baked_atlas = libmtk_py.BakedAtlas.from_mapping_json(atlas_json_str)

    # Discover Colormaps
    colormaps: Dict[str, Path] = {}
    if colormaps_dir.exists():
        for cm_name in ("grass", "foliage", "dry_foliage"):
            p = colormaps_dir / f"{cm_name}.png"
            if p.exists():
                colormaps[cm_name] = p

    manifest_path = base_cache / "cache_manifest.json"
    manifest_fingerprint = None
    if manifest_path.exists():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_fingerprint = manifest_data.get("fingerprint")
        except Exception:
            pass

    # 1. Extract Face Materials & UVs
    num_polys = len(mesh.polygons)
    num_loops = len(mesh.loops)

    # Active UV layer
    uv_layer = mesh.uv_layers.active or (mesh.uv_layers[0] if len(mesh.uv_layers) > 0 else None)
    if uv_layer is None:
        uv_layer = mesh.uv_layers.new(name="UVMap")

    loop_uvs = array.array("f", [0.0]) * (num_loops * 2)
    uv_layer.data.foreach_get("uv", loop_uvs)

    # Check if provenance attribute already exists on the mesh
    prov_attr = mesh.attributes.get("mtk_source_texture_key") if hasattr(mesh, "attributes") else None
    existing_prov_keys: Optional[List[str]] = None
    if prov_attr is not None and len(prov_attr.data) == num_polys:
        existing_prov_keys = [
            elem.value.decode("utf-8") if isinstance(elem.value, (bytes, bytearray)) else str(elem.value)
            for elem in prov_attr.data
        ]

    face_materials: List[str] = []
    face_loop_ranges: List[Tuple[int, int]] = []

    for idx, poly in enumerate(mesh.polygons):
        mat_name = "default"
        # If the material slot is an MTK chunk or missing, and provenance key exists, use provenance key
        if poly.material_index < len(mesh.materials):
            mat_slot = mesh.materials[poly.material_index]
            if mat_slot:
                mat_name = mat_slot.name

        if (
            mat_name.startswith("MTK:Atlas:")
            or mat_name.startswith("MTK_Atlas_Chunk_")
            or mat_name.startswith("MTK:")
            or mat_name.startswith("MTK_")
            or mat_name == "default"
        ) and existing_prov_keys:
            candidate = existing_prov_keys[idx]
            if candidate and candidate != "mozi:fallback":
                mat_name = candidate

        face_materials.append(mat_name)
        face_loop_ranges.append((poly.loop_start, poly.loop_total))

    # 2. Build Matching Context (Aliases & GridAtlasSpec)
    unique_names = list(dict.fromkeys(face_materials))
    alias_map, grid_spec = build_matching_context(unique_names, origin=origin)

    # 3. Fast Parallel Rust Remapping
    remap_result = libmtk_py.MaterialResolver.remap_mesh_multi_uvs(
        list(loop_uvs),
        face_materials,
        face_loop_ranges,
        baked_atlas,
        alias_map,
        grid_spec,
    )

    face_chunk_ids: List[int] = remap_result["face_chunk_ids"]
    face_texture_ids: List[int] = remap_result["face_texture_ids"]
    face_uv_transforms: List[List[float]] = remap_result["face_uv_transforms"]
    face_uv_modes: List[int] = remap_result["face_uv_modes"]
    face_is_overlay: List[bool] = remap_result["face_is_overlay"]
    unmapped_count: int = remap_result["unmapped_faces"]

    # Build reverse lookup for source texture key
    sprites_dict = atlas_data.get("sprites", {})
    id_to_key: Dict[int, str] = {}
    for key, sp in sprites_dict.items():
        tid = sp.get("texture_id")
        if tid is not None:
            id_to_key[int(tid)] = key

    face_source_keys: List[str] = []
    for i, tex_id in enumerate(face_texture_ids):
        resolved_key = id_to_key.get(tex_id)
        if not resolved_key and existing_prov_keys and existing_prov_keys[i] and existing_prov_keys[i] != "mozi:fallback":
            resolved_key = existing_prov_keys[i]
        face_source_keys.append(resolved_key or "mozi:fallback")

    # 4. Assign Materials & Update Slots
    mode_upper = mode.strip().upper()
    poly_mat_indices = array.array("H", [0]) * num_polys

    if mode_upper == "ATLAS":
        # Atlas Mode: 1 Material per Chunk
        unique_chunks = sorted(list(set(face_chunk_ids)))
        chunk_to_slot: Dict[int, int] = {}
        mesh.materials.clear()

        # Lookup chunk metadata from JSON
        chunk_meta_list = atlas_data.get("chunks", [])
        chunk_meta_map: Dict[int, Dict[str, Any]] = {
            c.get("chunk_id", idx): c for idx, c in enumerate(chunk_meta_list)
        }

        for slot_idx, chunk_id in enumerate(unique_chunks):
            cm = chunk_meta_map.get(chunk_id, {})
            cat = cm.get("category", "blocks")
            c_idx = cm.get("category_chunk_index", chunk_id + 1)
            is_anim = cm.get("is_animated", False)
            stem = f"{cat}_anim_chunk_{c_idx:03}" if is_anim else f"{cat}_chunk_{c_idx:03}"

            albedo_file = atlas_dir / f"{stem}.png"
            normal_file = atlas_dir / f"{stem}_n.png" if cm.get("has_normal") else None
            specular_file = atlas_dir / f"{stem}_s.png" if cm.get("has_specular") else None
            overlay_file = atlas_dir / f"{stem}_overlay.png" if cm.get("has_overlay") else None
            chunk_width = float(cm.get("width", 1024))
            chunk_height = float(cm.get("height", 512))

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
                stack_fingerprint=manifest_fingerprint,
                atlas_width=chunk_width,
                atlas_height=chunk_height,
                tile_width=16.0,
                tile_height=16.0,
            )
            mesh.materials.append(mat)
            chunk_to_slot[chunk_id] = slot_idx

        # Assign face material indices
        for i, cid in enumerate(face_chunk_ids):
            poly_mat_indices[i] = chunk_to_slot.get(cid, 0)

        # Write remapped Atlas UVs
        atlas_uvs = remap_result["atlas_uvs"]
        uv_layer.data.foreach_set("uv", array.array("f", atlas_uvs))

    else:
        # Standalone Mode: 1 Material per unique block texture
        sa_mapping_str = standalone_mapping_path.read_text(encoding="utf-8")
        sa_data = json.loads(sa_mapping_str)
        sa_textures = sa_data.get("textures", {})

        unique_keys = list(dict.fromkeys(face_source_keys))
        key_to_slot: Dict[str, int] = {}
        mesh.materials.clear()

        for slot_idx, key in enumerate(unique_keys):
            tex_entry = sa_textures.get(key)
            if tex_entry:
                files = tex_entry.get("files", {})
                albedo_p = standalone_dir / files.get("albedo", "textures/mtk_fallback.png")
                normal_p = (standalone_dir / files["normal"]) if "normal" in files else None
                specular_p = (standalone_dir / files["specular"]) if "specular" in files else None
                overlay_p = (standalone_dir / files["overlay"]) if "overlay" in files else None
                is_anim = tex_entry.get("is_animated", False)
            else:
                albedo_p = standalone_dir / "textures" / "mtk_fallback.png"
                normal_p = None
                specular_p = None
                overlay_p = None
                is_anim = False

            mat = build_standalone_material(
                texture_key=key,
                albedo_path=albedo_p,
                normal_path=normal_p,
                specular_path=specular_p,
                overlay_path=overlay_p,
                colormaps=colormaps,
                is_animated=is_anim,
                stack_fingerprint=manifest_fingerprint,
            )
            mesh.materials.append(mat)
            key_to_slot[key] = slot_idx

        # Assign face material indices
        for i, key in enumerate(face_source_keys):
            poly_mat_indices[i] = key_to_slot.get(key, 0)

        # Write normalized Local UVs
        local_uvs = remap_result["local_uvs"]
        uv_layer.data.foreach_set("uv", array.array("f", local_uvs))

    # Apply polygon material indices
    mesh.polygons.foreach_set("material_index", poly_mat_indices)

    # 5. Inject Custom Attributes for Provenance & Shader Nodes
    _inject_face_attribute_string(mesh, "mtk_source_texture_key", face_source_keys)
    _inject_face_attribute_int(mesh, "mtk_material_slot", list(poly_mat_indices))
    _inject_face_attribute_int(mesh, "mtk_atlas_chunk_id", face_chunk_ids)
    _inject_face_attribute_int(mesh, "mtk_atlas_texture_id", [int(x) for x in face_texture_ids])
    _inject_face_attribute_int(mesh, "mtk_uv_mode", [0 if mode_upper == "ATLAS" else 1] * num_polys)

    # Pack UV transform [scale_u, scale_v, offset_u, offset_v]
    flat_transforms: List[float] = []
    for tf in face_uv_transforms:
        flat_transforms.extend(tf)
    _inject_face_attribute_float4(mesh, "mtk_uv_tiling_transform", flat_transforms)
    _inject_face_attribute_float4(mesh, "mtk_uv_transform", flat_transforms)

    face_uv_rotations: List[float] = remap_result.get("face_uv_rotations", [0.0] * num_polys)
    _inject_face_attribute_float(mesh, "mtk_uv_rotation", face_uv_rotations)

    # 6. Compute & Inject Biome Tint Attributes (Instant load from prebaked cache in < 0.2ms)
    biome_resolver = get_or_load_biome_resolver(cache_dir=base_cache, prefs=prefs)

    is_custom = biome.upper() == "CUSTOM"
    if is_custom:
        custom_temp = float(getattr(mesh_or_obj, "mtk_biome_temp", mesh_or_obj.get("mtk_biome_temp", 0.8) if hasattr(mesh_or_obj, "get") else 0.8))
        custom_humidity = float(getattr(mesh_or_obj, "mtk_biome_humidity", mesh_or_obj.get("mtk_biome_humidity", 0.4) if hasattr(mesh_or_obj, "get") else 0.4))
        has_custom_grass = bool(getattr(mesh_or_obj, "mtk_biome_use_custom_grass", mesh_or_obj.get("mtk_biome_use_custom_grass", False) if hasattr(mesh_or_obj, "get") else False))
        has_custom_foliage = bool(getattr(mesh_or_obj, "mtk_biome_use_custom_foliage", mesh_or_obj.get("mtk_biome_use_custom_foliage", False) if hasattr(mesh_or_obj, "get") else False))
        has_custom_dry_foliage = bool(getattr(mesh_or_obj, "mtk_biome_use_custom_dry_foliage", mesh_or_obj.get("mtk_biome_use_custom_dry_foliage", False) if hasattr(mesh_or_obj, "get") else False))
        custom_grass = list(getattr(mesh_or_obj, "mtk_biome_grass_color", mesh_or_obj.get("mtk_biome_grass_color", (0.28, 0.51, 0.10, 1.0)) if hasattr(mesh_or_obj, "get") else (0.28, 0.51, 0.10, 1.0)))
        custom_foliage = list(getattr(mesh_or_obj, "mtk_biome_foliage_color", mesh_or_obj.get("mtk_biome_foliage_color", (0.18, 0.41, 0.03, 1.0)) if hasattr(mesh_or_obj, "get") else (0.18, 0.41, 0.03, 1.0)))
        custom_dry_foliage = list(getattr(mesh_or_obj, "mtk_biome_dry_foliage_color", mesh_or_obj.get("mtk_biome_dry_foliage_color", (0.37, 0.18, 0.06, 1.0)) if hasattr(mesh_or_obj, "get") else (0.37, 0.18, 0.06, 1.0)))
        custom_water = list(getattr(mesh_or_obj, "mtk_biome_water_color", mesh_or_obj.get("mtk_biome_water_color", (0.05, 0.18, 0.78, 1.0)) if hasattr(mesh_or_obj, "get") else (0.05, 0.18, 0.78, 1.0)))
    else:
        custom_temp = None
        custom_humidity = None
        has_custom_grass = False
        has_custom_foliage = False
        has_custom_dry_foliage = False
        custom_grass = None
        custom_foliage = None
        custom_dry_foliage = None
        custom_water = None

    packed_tint_data, tint_colors, colormap_uvs = compute_biome_tint_attributes(
        face_source_keys,
        biome_preset=biome,
        resolver=biome_resolver,
        custom_temp=custom_temp,
        custom_humidity=custom_humidity,
        custom_grass=custom_grass,
        custom_foliage=custom_foliage,
        custom_dry_foliage=custom_dry_foliage,
        custom_water=custom_water,
        has_custom_grass=has_custom_grass,
        has_custom_foliage=has_custom_foliage,
        has_custom_dry_foliage=has_custom_dry_foliage,
    )
    apply_biome_tint_attributes(mesh, packed_tint_data, tint_colors, colormap_uvs)

    if hasattr(mesh_or_obj, "__setitem__"):
        try:
            mesh_or_obj["mtk:biome_preset"] = biome
        except Exception:
            pass

    mesh.update()

    return {
        "success": True,
        "mode": mode_upper,
        "biome": biome,
        "face_count": num_polys,
        "materials_count": len(mesh.materials),
        "unmapped_faces": unmapped_count,
    }


def restore_materials_from_provenance(
    mesh_or_obj: Any,
    mode: str = "ATLAS",
    biome: Optional[str] = None,
    prefs: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Reconstructs Blender material slots, nodes, and assignments purely from mesh face provenance attributes.
    Bypasses UV remapping, texture matching, and pack parsing entirely.

    Args:
        mesh_or_obj: Blender mesh or object with mtk_source_texture_key attributes.
        mode: Target reconstruction mode ("ATLAS" or "STANDALONE").
        biome: Optional biome preset to restore. Defaults to object property or "PLAINS".
        prefs: Add-on preferences reference.
    """
    if not HAS_BPY:
        raise RuntimeError("Blender (bpy) is required to execute restore_materials_from_provenance.")
    if not HAS_LIBMTK:
        raise RuntimeError("libmtk_py (Rust backend) is not installed or available.")

    mesh = _get_mesh(mesh_or_obj)
    if mesh is None or len(mesh.polygons) == 0:
        return {"success": False, "message": "Mesh has no geometry or polygons."}

    num_polys = len(mesh.polygons)
    base_cache = ensure_stack_precompiled(prefs)
    atlas_dir = base_cache / "atlas"
    standalone_dir = base_cache / "standalone"
    colormaps_dir = base_cache / "colormaps"

    colormaps: Dict[str, Path] = {}
    if colormaps_dir.exists():
        for cm_name in ("grass", "foliage", "dry_foliage"):
            p = colormaps_dir / f"{cm_name}.png"
            if p.exists():
                colormaps[cm_name] = p

    manifest_path = base_cache / "cache_manifest.json"
    manifest_fingerprint = None
    if manifest_path.exists():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_fingerprint = manifest_data.get("fingerprint")
        except Exception:
            pass

    src_attr = mesh.attributes.get("mtk_source_texture_key") if hasattr(mesh, "attributes") else None
    if src_attr is None:
        return {"success": False, "message": "Mesh lacks required mtk_source_texture_key attribute for provenance."}

    face_source_keys = [
        elem.value.decode("utf-8", errors="replace") if isinstance(elem.value, (bytes, bytearray)) else str(elem.value)
        for elem in src_attr.data
    ]

    chunk_attr = mesh.attributes.get("mtk_atlas_chunk_id")
    face_chunk_ids = [elem.value for elem in chunk_attr.data] if chunk_attr else [0] * num_polys

    effective_biome = biome
    if not effective_biome and hasattr(mesh_or_obj, "get"):
        effective_biome = mesh_or_obj.get("mtk:biome_preset", "PLAINS")
    if not effective_biome:
        effective_biome = "PLAINS"

    mode_upper = mode.strip().upper()
    poly_mat_indices = array.array("H", [0]) * num_polys

    if mode_upper == "ATLAS":
        atlas_mapping_path = atlas_dir / "atlas_mapping.json"
        if not atlas_mapping_path.exists():
            raise FileNotFoundError(f"Atlas mapping missing at {atlas_mapping_path}")

        atlas_data = json.loads(atlas_mapping_path.read_text(encoding="utf-8"))
        chunks_map: Dict[int, Dict[str, Any]] = {c["chunk_id"]: c for c in atlas_data.get("chunks", [])}

        unique_chunks = sorted(list(set(face_chunk_ids)))
        chunk_to_slot: Dict[int, int] = {}
        mesh.materials.clear()

        for slot_idx, c_id in enumerate(unique_chunks):
            chunk_info = chunks_map.get(c_id, {})
            cat = chunk_info.get("category", "blocks")
            c_idx = chunk_info.get("category_chunk_index", 1)
            is_anim = chunk_info.get("is_animated", False)
            stem = f"{cat}_anim_chunk_{c_idx:03}" if is_anim else f"{cat}_chunk_{c_idx:03}"

            albedo_file = atlas_dir / f"{stem}.png"
            normal_file = (atlas_dir / f"{stem}_n.png") if chunk_info.get("has_normal") else None
            specular_file = (atlas_dir / f"{stem}_s.png") if chunk_info.get("has_specular") else None
            overlay_file = (atlas_dir / f"{stem}_overlay.png") if chunk_info.get("has_overlay") else None

            mat = build_atlas_chunk_material(
                chunk_id=c_id,
                albedo_path=albedo_file,
                normal_path=normal_file,
                specular_path=specular_file,
                overlay_path=overlay_file,
                colormaps=colormaps,
                category=cat,
                category_chunk_index=c_idx,
                is_animated=is_anim,
                stack_fingerprint=manifest_fingerprint,
            )
            mesh.materials.append(mat)
            chunk_to_slot[c_id] = slot_idx

        for i, c_id in enumerate(face_chunk_ids):
            poly_mat_indices[i] = chunk_to_slot.get(c_id, 0)
    else:
        # Standalone Reconstruction
        sa_mapping_path = standalone_dir / "standalone_mapping.json"
        if not sa_mapping_path.exists():
            raise FileNotFoundError(f"Standalone mapping missing at {sa_mapping_path}")

        sa_data = json.loads(sa_mapping_path.read_text(encoding="utf-8"))
        tex_entries = sa_data.get("textures", {})

        unique_keys = list(dict.fromkeys(face_source_keys))
        tex_to_slot: Dict[str, int] = {}
        mesh.materials.clear()

        for slot_idx, tex_key in enumerate(unique_keys):
            if not tex_key:
                continue
            tex_entry = tex_entries.get(tex_key)
            if tex_entry:
                files = tex_entry.get("files", {})
                albedo_p = standalone_dir / files.get("albedo", "textures/mtk_fallback.png")
                normal_p = (standalone_dir / files["normal"]) if "normal" in files else None
                specular_p = (standalone_dir / files["specular"]) if "specular" in files else None
                overlay_p = (standalone_dir / files["overlay"]) if "overlay" in files else None
                is_anim = tex_entry.get("is_animated", False)
            else:
                albedo_p = standalone_dir / "textures" / "mtk_fallback.png"
                normal_p = None
                specular_p = None
                overlay_p = None
                is_anim = False

            mat = build_standalone_material(
                texture_key=tex_key,
                albedo_path=albedo_p,
                normal_path=normal_p,
                specular_path=specular_p,
                overlay_path=overlay_p,
                colormaps=colormaps,
                is_animated=is_anim,
                stack_fingerprint=manifest_fingerprint,
            )
            mesh.materials.append(mat)
            tex_to_slot[tex_key] = slot_idx

        for i, t_key in enumerate(face_source_keys):
            poly_mat_indices[i] = tex_to_slot.get(t_key, 0)

    mesh.polygons.foreach_set("material_index", poly_mat_indices)
    _inject_face_attribute_int(mesh, "mtk_material_slot", list(poly_mat_indices))

    # Re-apply or verify biome attributes (Instant load from prebaked cache in < 0.2ms)
    biome_resolver = get_or_load_biome_resolver(cache_dir=base_cache, prefs=prefs)

    is_custom = effective_biome.upper() == "CUSTOM"
    if is_custom:
        custom_temp = float(getattr(mesh_or_obj, "mtk_biome_temp", mesh_or_obj.get("mtk_biome_temp", 0.8) if hasattr(mesh_or_obj, "get") else 0.8))
        custom_humidity = float(getattr(mesh_or_obj, "mtk_biome_humidity", mesh_or_obj.get("mtk_biome_humidity", 0.4) if hasattr(mesh_or_obj, "get") else 0.4))
        has_custom_grass = bool(getattr(mesh_or_obj, "mtk_biome_use_custom_grass", mesh_or_obj.get("mtk_biome_use_custom_grass", False) if hasattr(mesh_or_obj, "get") else False))
        has_custom_foliage = bool(getattr(mesh_or_obj, "mtk_biome_use_custom_foliage", mesh_or_obj.get("mtk_biome_use_custom_foliage", False) if hasattr(mesh_or_obj, "get") else False))
        has_custom_dry_foliage = bool(getattr(mesh_or_obj, "mtk_biome_use_custom_dry_foliage", mesh_or_obj.get("mtk_biome_use_custom_dry_foliage", False) if hasattr(mesh_or_obj, "get") else False))
        custom_grass = list(getattr(mesh_or_obj, "mtk_biome_grass_color", mesh_or_obj.get("mtk_biome_grass_color", (0.28, 0.51, 0.10, 1.0)) if hasattr(mesh_or_obj, "get") else (0.28, 0.51, 0.10, 1.0)))
        custom_foliage = list(getattr(mesh_or_obj, "mtk_biome_foliage_color", mesh_or_obj.get("mtk_biome_foliage_color", (0.18, 0.41, 0.03, 1.0)) if hasattr(mesh_or_obj, "get") else (0.18, 0.41, 0.03, 1.0)))
        custom_dry_foliage = list(getattr(mesh_or_obj, "mtk_biome_dry_foliage_color", mesh_or_obj.get("mtk_biome_dry_foliage_color", (0.37, 0.18, 0.06, 1.0)) if hasattr(mesh_or_obj, "get") else (0.37, 0.18, 0.06, 1.0)))
        custom_water = list(getattr(mesh_or_obj, "mtk_biome_water_color", mesh_or_obj.get("mtk_biome_water_color", (0.05, 0.18, 0.78, 1.0)) if hasattr(mesh_or_obj, "get") else (0.05, 0.18, 0.78, 1.0)))
    else:
        custom_temp = None
        custom_humidity = None
        has_custom_grass = False
        has_custom_foliage = False
        has_custom_dry_foliage = False
        custom_grass = None
        custom_foliage = None
        custom_dry_foliage = None
        custom_water = None

    packed_tint_data, tint_colors, colormap_uvs = compute_biome_tint_attributes(
        face_source_keys,
        biome_preset=effective_biome,
        resolver=biome_resolver,
        custom_temp=custom_temp,
        custom_humidity=custom_humidity,
        custom_grass=custom_grass,
        custom_foliage=custom_foliage,
        custom_dry_foliage=custom_dry_foliage,
        custom_water=custom_water,
        has_custom_grass=has_custom_grass,
        has_custom_foliage=has_custom_foliage,
        has_custom_dry_foliage=has_custom_dry_foliage,
    )
    apply_biome_tint_attributes(mesh, packed_tint_data, tint_colors, colormap_uvs)

    if hasattr(mesh_or_obj, "__setitem__"):
        try:
            mesh_or_obj["mtk:biome_preset"] = effective_biome
        except Exception:
            pass

    mesh.update()

    return {
        "success": True,
        "restored_faces": num_polys,
        "biome": effective_biome,
        "materials_count": len(mesh.materials),
    }


def _inject_face_attribute_string(mesh: Any, name: str, values: List[str]) -> None:
    """Helper to inject a Face-domain String attribute."""
    if not hasattr(mesh, "attributes"):
        return
    attr = mesh.attributes.get(name)
    if attr is None:
        try:
            attr = mesh.attributes.new(name=name, type="STRING", domain="FACE")
        except Exception:
            return
    if len(attr.data) == len(values):
        for i, val in enumerate(values):
            b_val = val.encode("utf-8") if isinstance(val, str) else bytes(val)
            try:
                attr.data[i].value = b_val
            except Exception:
                try:
                    attr.data[i].value = val
                except Exception:
                    pass


def _inject_face_attribute_int(mesh: Any, name: str, values: List[int]) -> None:
    """Helper to inject a Face-domain Int attribute."""
    if not hasattr(mesh, "attributes"):
        return
    attr = mesh.attributes.get(name)
    if attr is None:
        try:
            attr = mesh.attributes.new(name=name, type="INT", domain="FACE")
        except Exception:
            return
    if len(attr.data) == len(values):
        attr.data.foreach_set("value", array.array("i", values))


def _inject_face_attribute_float(mesh: Any, name: str, values: List[float]) -> None:
    """Helper to inject a Face-domain Float attribute."""
    if not hasattr(mesh, "attributes"):
        return
    attr = mesh.attributes.get(name)
    if attr is None:
        try:
            attr = mesh.attributes.new(name=name, type="FLOAT", domain="FACE")
        except Exception:
            return
    if len(attr.data) == len(values):
        attr.data.foreach_set("value", array.array("f", values))


def _inject_face_attribute_float4(mesh: Any, name: str, flat_values: List[float]) -> None:
    """Helper to inject a Face-domain Float4/Color attribute."""
    if not hasattr(mesh, "attributes"):
        return
    attr = mesh.attributes.get(name)
    if attr is None:
        try:
            attr = mesh.attributes.new(name=name, type="FLOAT_COLOR", domain="FACE")
        except Exception:
            return
    if len(attr.data) * 4 == len(flat_values):
        attr.data.foreach_set("color", array.array("f", flat_values))
