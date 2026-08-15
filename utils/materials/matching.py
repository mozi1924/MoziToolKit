"""
Source-aware Minecraft material texture-key matching.

Every importer has its own naming conventions. A matching preset isolates
those conventions so the replacement pipeline never has to guess which
importer created a material.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import bpy

from .constants import (
    ATTR_SOURCE_ORIGIN,
    ATTR_SOURCE_TEXTURE_KEY,
    DEFAULT_NAMESPACE,
)
from .atlas_layout import find_texture_id_from_atlas_uv


def without_blender_suffix(value: str) -> str:
    """Remove Blender's duplicate suffix without changing an actual name."""
    if "." in value and value.rsplit(".", 1)[1].isdigit():
        return value.rsplit(".", 1)[0]
    return value


def canonical_texture_key(namespace: str, texture_name: str) -> str:
    """Return the durable ``namespace:texture`` source identifier.

    The key intentionally does not contain a resource-pack hash: a later
    replacement pack is allowed to provide the same Minecraft resource.
    """
    namespace = (namespace or DEFAULT_NAMESPACE).strip().lower()
    texture_name = (texture_name or "").strip().lower().removesuffix(".png")
    return f"{namespace}:{texture_name}" if texture_name else ""


def split_texture_key(value: str) -> tuple[str, str]:
    """Parse a canonical key, accepting legacy texture-only values."""
    value = (value or "").strip().lower().removesuffix(".png")
    if not value:
        return DEFAULT_NAMESPACE, ""
    if ":" in value:
        namespace, texture_name = value.split(":", 1)
        return namespace or DEFAULT_NAMESPACE, texture_name
    return DEFAULT_NAMESPACE, value


def write_face_source_provenance(
    mesh: bpy.types.Mesh,
    texture_keys: list[str],
    origins: list[str] | None = None,
) -> None:
    """Write source identity only after a whole mesh conversion is validated."""
    if len(texture_keys) != len(mesh.polygons):
        raise ValueError("Source provenance must contain one entry per polygon")
    if origins is not None and len(origins) != len(mesh.polygons):
        raise ValueError("Source origins must contain one entry per polygon")

    def string_face_attribute(name: str):
        attr = mesh.attributes.get(name)
        if attr and (attr.domain != "FACE" or attr.data_type != "STRING"):
            mesh.attributes.remove(attr)
            attr = None
        return attr or mesh.attributes.new(name=name, type="STRING", domain="FACE")

    key_attr = string_face_attribute(ATTR_SOURCE_TEXTURE_KEY)
    for item, key in zip(key_attr.data, texture_keys):
        item.value = key.encode("utf-8")
    if origins is not None:
        origin_attr = string_face_attribute(ATTR_SOURCE_ORIGIN)
        for item, origin in zip(origin_attr.data, origins):
            item.value = origin.encode("utf-8")


def get_face_source_origin(mesh: bpy.types.Mesh, poly_idx: int) -> str:
    """Read an existing FACE origin without treating Mozi output as origin."""
    attr = mesh.attributes.get(ATTR_SOURCE_ORIGIN)
    if not attr or attr.domain != "FACE" or attr.data_type != "STRING" or poly_idx >= len(attr.data):
        return ""
    value = attr.data[poly_idx].value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value).strip()


def get_face_source_texture_key(mesh: bpy.types.Mesh, poly_idx: int) -> str:
    """Read an existing canonical source key, if this face already has one."""
    attr = mesh.attributes.get(ATTR_SOURCE_TEXTURE_KEY)
    if not attr or attr.domain != "FACE" or attr.data_type != "STRING" or poly_idx >= len(attr.data):
        return ""
    value = attr.data[poly_idx].value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value).strip()


def extract_texture_provenance_from_image(image: bpy.types.Image) -> tuple[str | None, str]:
    """Extract namespace (if identifiable) and clean texture name from an image datablock."""
    if not image:
        return None, ""

    filepath = (image.filepath or "").replace("\\", "/").strip()
    raw_name = Path(filepath).name if filepath else image.name

    detected_namespace = None
    if ":" in raw_name:
        parts = raw_name.split(":", 1)
        detected_namespace = parts[0].strip().lower()
        raw_name = parts[1]

    if filepath and not detected_namespace:
        parts = filepath.strip("/").split("/")
        # Check assets/<namespace>/textures/...
        for i, p in enumerate(parts):
            if p.lower() == "assets" and i + 2 < len(parts) and parts[i + 2].lower() == "textures":
                detected_namespace = parts[i + 1].lower()
                break
            elif p.lower() == "textures" and i > 0 and parts[i - 1].lower() not in (
                "assets", "resourcepacks", "resource_packs", "mcpatcher", "optifine"
            ):
                candidate_ns = parts[i - 1].lower()
                if candidate_ns not in ("minecraft", "assets"):
                    detected_namespace = candidate_ns
                break

    key = without_blender_suffix(raw_name.lower())
    if key.endswith(".png"):
        key = key[:-4]
    if len(key) > 5 and key[-5] == "_" and key[-4:].isdigit():
        key = key[:-5]
    return detected_namespace, key


def normalized_image_key(image: bpy.types.Image) -> str:
    """Return an image datablock's basename as a resource-pack texture key."""
    _ns, key = extract_texture_provenance_from_image(image)
    return key


def detect_material_mode(mat: bpy.types.Material | None) -> str:
    """Detect whether a material is Standalone, Atlas Chunk, Unified Atlas, or Generic."""
    if not mat:
        return "GENERIC"

    if "mtk:atlas_chunk_id" in mat:
        return "ATLAS_CHUNK"

    if mat.node_tree and "mtk:atlas_mapping" in mat.node_tree:
        if mat.name.startswith("mtk:") and "atlas_chunk" in mat.name:
            return "ATLAS_CHUNK"
        return "ATLAS_UNIFIED"

    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.name == "MC Atlas UV Decoder" or (node.type == "GROUP" and node.node_tree and node.node_tree.name == "MC_Atlas_UV_Decoder"):
                return "ATLAS_UNIFIED"

    if "mtk:source_texture" in mat or "mtk:source_namespace" in mat or mat.name.startswith("mtk:"):
        source_tex = str(mat.get("mtk:source_texture", ""))
        if source_tex.startswith("atlas_chunk_"):
            return "ATLAS_CHUNK"
        return "STANDALONE"

    return "GENERIC"


def is_mozi_material(mat: bpy.types.Material | None) -> bool:
    """Check if a material was created by MoziToolKit."""
    if not mat:
        return False
    if mat.name.startswith("mtk:"):
        return True
    if any(k.startswith("mtk:") for k in mat.keys()):
        return True
    if mat.node_tree and any(k.startswith("mtk:") for k in mat.node_tree.keys()):
        return True
    return False


def get_atlas_mapping_from_material(mat: bpy.types.Material | None) -> dict | None:
    """Extract and parse atlas_mapping JSON dictionary stored on a material's node tree."""
    if not mat or not mat.node_tree or "mtk:atlas_mapping" not in mat.node_tree:
        return None
    raw = mat.node_tree["mtk:atlas_mapping"]
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def base_texture_candidates(mat: bpy.types.Material) -> tuple[str, list[str]]:
    """Extract literal image and material-name candidates shared by all presets."""
    if not mat:
        return "", []
    if mat.get("mtk:source_namespace") and mat.get("mtk:source_texture"):
        source_tex = str(mat["mtk:source_texture"])
        if not source_tex.startswith("atlas_chunk_"):
            return str(mat["mtk:source_namespace"]), [source_tex]

    name = without_blender_suffix(mat.name.strip().lower())
    namespace = DEFAULT_NAMESPACE
    if ":" in name:
        parts = name.split(":")
        if len(parts) >= 3 and parts[0] == "mtk":
            namespace = parts[1]
            name = parts[2]
        else:
            namespace, name = parts[0], parts[1]
    elif "/" in name and not name.startswith("//"):
        parts = name.split("/", 1)
        if parts[0] in ("assets", "textures", "block", "item", "entity"):
            name = parts[1]
        else:
            namespace, name = parts[0], parts[1]

    candidates = []
    detected_namespaces = []
    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                img_ns, key = extract_texture_provenance_from_image(node.image)
                if img_ns:
                    detected_namespaces.append(img_ns)
                if key and not key.startswith("atlas_chunk_"):
                    candidates.append(key)

    if namespace == DEFAULT_NAMESPACE and detected_namespaces:
        namespace = detected_namespaces[0]

    if not name.startswith("atlas_chunk_"):
        candidates.append(name)
    return namespace, list(dict.fromkeys(candidates))


def generic_texture_candidates(mat: bpy.types.Material) -> tuple[str, list[str]]:
    return base_texture_candidates(mat)


def ice_cube_name_aliases(name: str) -> list[str]:
    aliases = []
    for suffix in ("_all", "_side", "_end", "_top", "_bottom", "_front", "_back",
                   "_up", "_down", "_north", "_south", "_east", "_west"):
        if name.endswith(suffix):
            stem = name[:-len(suffix)]
            aliases.append(stem)
            if suffix == "_all" and stem.endswith("_block"):
                aliases.append(stem[:-len("_block")])
            break
    return aliases


def ice_cube_legacy_aliases(name: str) -> list[str]:
    aliases = []
    if name.startswith("item_"):
        aliases.append(name[len("item_"):])
    if name.endswith("_on_front"):
        aliases.append(f"{name[:-len('_on_front')]}_front_on")
    if "_lit_log" in name:
        aliases.append(name.replace("_lit_log", "_log_lit"))
    return aliases


# Ice Cube's entity names predate Mojang's 26.2 naming layout.
ICE_CUBE_ENTITY_ALIASES = {
    "aggressive_panda": "panda_aggressive",
    "brown_panda": "panda_brown",
    "lazy_panda": "panda_lazy",
    "playful_panda": "panda_playful",
    "weak_panda": "panda_weak",
    "worried_panda": "panda_worried",
    "white_splotched": "rabbit_white_splotched",
    "caerbannog": "rabbit_caerbannog",
    "salt": "rabbit_salt",
    "toast": "rabbit_toast",
    "elder_guardian": "guardian_elder",
    "drowned_outer": "drowned_outer_layer",
    "magma_cube": "magmacube",
    "polar_bear": "polarbear",
    "snow_fox": "fox_snow",
}

ICE_CUBE_MATERIAL_NAME_ALIASES = {
    "british shorthair cat": "cat_british_shorthair",
    "calico cat": "cat_calico",
    "jellie cat": "cat_jellie",
    "persian cat": "cat_persian",
    "ragdoll cat": "cat_ragdoll",
    "red cat": "cat_red",
    "siamese cat": "cat_siamese",
    "tabby cat": "cat_tabby",
    "white cat": "cat_white",
    "black cat": "cat_black",
    "lucy axolotl": "axolotl_lucy",
    "brown mooshroom": "mooshroom_brown",
    "mooshroom": "mooshroom_red",
    "cold chicken": "chicken_cold",
    "warm chicken": "chicken_warm",
    "temperate cow": "cow_temperate",
    "cold cow": "cow_cold",
    "warm cow": "cow_warm",
    "temperate frog": "frog_temperate",
    "cold frog": "frog_cold",
    "warm frog": "frog_warm",
    "temperate pig": "pig_temperate",
    "cold pig": "pig_cold",
    "warm pig": "pig_warm",
}


def ice_cube_texture_candidates(mat: bpy.types.Material) -> tuple[str, list[str]]:
    namespace, candidates = base_texture_candidates(mat)
    if mat.get("mtk:source_namespace"):
        return namespace, candidates

    source_name = without_blender_suffix(mat.name.strip().lower())
    candidates.extend(ice_cube_name_aliases(source_name))
    original_candidates = list(dict.fromkeys(candidates))
    for candidate in original_candidates:
        candidates.extend(ice_cube_legacy_aliases(candidate))
        if candidate in ICE_CUBE_ENTITY_ALIASES:
            candidates.append(ICE_CUBE_ENTITY_ALIASES[candidate])
    if source_name in ICE_CUBE_MATERIAL_NAME_ALIASES:
        candidates.append(ICE_CUBE_MATERIAL_NAME_ALIASES[source_name])
    return namespace, list(dict.fromkeys(candidates))


def is_ice_cube_internal_face_material(mat: bpy.types.Material | None) -> bool:
    """Return whether Ice Cube marks this slot as intentionally invisible.

    Ice Cube creates duplicate slots such as ``internal_face_deletion.001``.
    They can retain an image node from a previously copied material, so image
    based fallback matching must never turn them into visible leaves or other
    textures.
    """
    if not is_ice_cube_material(mat):
        return False
    name = without_blender_suffix(mat.name.strip().lower())
    return bool(re.fullmatch(r"internal_face_deletion(?:_[0-9]+)?", name))


def is_ice_cube_material(mat: bpy.types.Material) -> bool:
    """Recognize Ice Cube's persistent library metadata."""
    return bool(mat) and (
        "flip_fluid_material_library" in mat
        or "ice_cube.material_id" in mat
    )


@dataclass(frozen=True)
class MaterialMatchPreset:
    identifier: str
    description: str
    detects: Callable[[bpy.types.Material], bool]
    extract_keys: Callable[[bpy.types.Material], tuple[str, list[str]]]


ICE_CUBE_PRESET = MaterialMatchPreset(
    identifier="ice_cube",
    description="Ice Cube Asset Library material names and entity aliases",
    detects=is_ice_cube_material,
    extract_keys=ice_cube_texture_candidates,
)
GENERIC_PRESET = MaterialMatchPreset(
    identifier="generic",
    description="Literal image and material-name matching",
    detects=lambda _mat: True,
    extract_keys=generic_texture_candidates,
)
MATCH_PRESETS = (ICE_CUBE_PRESET, GENERIC_PRESET)


def get_material_match_preset(mat: bpy.types.Material) -> MaterialMatchPreset:
    return next(preset for preset in MATCH_PRESETS if preset.detects(mat))


def material_source_origin(mat: bpy.types.Material | None) -> str:
    """Classify an external material without conflating it with Mozi mode."""
    if is_mozi_material(mat):
        return "mozi"
    return get_material_match_preset(mat).identifier if mat else "generic"


def extract_material_texture_keys(mat: bpy.types.Material) -> tuple[str, list[str]]:
    """Extract candidates using the preset detected from material metadata."""
    if is_ice_cube_internal_face_material(mat):
        return DEFAULT_NAMESPACE, []
    return get_material_match_preset(mat).extract_keys(mat)


def extract_face_texture_info(
    mesh: bpy.types.Mesh,
    poly_idx: int,
    slot_mat: bpy.types.Material | None,
    atlas_mapping: dict | None = None,
) -> tuple[str, list[str], dict | None]:
    """
    Extract the source (namespace, candidate_keys_list, atlas_location_or_None) for a specific polygon.
    Handles Standalone materials, Atlas Chunk materials, Unified Atlas materials, and Generic materials.
    """
    if not slot_mat:
        return DEFAULT_NAMESPACE, [], None

    # FACE provenance is the authoritative identity across Standalone and
    # Atlas.  It survives material-slot consolidation and must win over
    # mutable UV coordinates or material names.  For an Atlas material we
    # still continue into its mapping: the returned location is required to
    # invert atlas UVs during a later Standalone conversion.
    provenance = None
    source_attr = mesh.attributes.get(ATTR_SOURCE_TEXTURE_KEY)
    if source_attr and source_attr.domain == "FACE" and source_attr.data_type == "STRING" and poly_idx < len(source_attr.data):
        raw_key = source_attr.data[poly_idx].value
        if isinstance(raw_key, bytes):
            raw_key = raw_key.decode("utf-8", errors="replace")
        namespace, texture_name = split_texture_key(raw_key)
        if texture_name:
            provenance = (namespace, [texture_name])

    mat_mode = detect_material_mode(slot_mat)
    if mat_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED"):
        mapping = atlas_mapping or get_atlas_mapping_from_material(slot_mat)
        if mapping:
            chunk_attr = mesh.attributes.get("atlas_chunk_id")
            tex_attr = mesh.attributes.get("atlas_texture_id")

            chunk_id = None
            texture_id = None
            if chunk_attr and poly_idx < len(chunk_attr.data):
                val = chunk_attr.data[poly_idx].value
                if val >= 0:
                    chunk_id = int(val)
            if tex_attr and poly_idx < len(tex_attr.data):
                val = tex_attr.data[poly_idx].value
                if val >= 0:
                    texture_id = int(val)

            if chunk_id is None and "mtk:atlas_chunk_id" in slot_mat:
                chunk_id = int(slot_mat["mtk:atlas_chunk_id"])

            chunks = {int(c["chunk_id"]): c for c in mapping.get("chunks", [])}
            current_chunk = chunks.get(chunk_id) if chunk_id is not None else None

            # Fallback: calculate from UV if texture_id is missing or attribute was lost
            if texture_id is None and current_chunk is not None:
                uv_layer = mesh.uv_layers.active_render or mesh.uv_layers.active
                if uv_layer and poly_idx < len(mesh.polygons):
                    poly = mesh.polygons[poly_idx]
                    if poly.loop_indices:
                        u_coords = [uv_layer.data[li].uv.x for li in poly.loop_indices]
                        v_coords = [uv_layer.data[li].uv.y for li in poly.loop_indices]
                        u_center = sum(u_coords) / len(u_coords)
                        v_center = sum(v_coords) / len(v_coords)
                        anims_in_chunk = [a for a in mapping.get("animations", []) if int(a.get("chunk_id", -1)) == chunk_id]
                        texture_id = find_texture_id_from_atlas_uv(u_center, v_center, current_chunk, anims_in_chunk)

            # Find matching texture in mapping
            if chunk_id is not None and texture_id is not None:
                for tex_name, loc in mapping.get("textures", {}).items():
                    if loc and int(loc.get("chunk_id", -1)) == chunk_id and int(loc.get("texture_id", -1)) == texture_id:
                        namespace, texture_name = split_texture_key(loc.get("texture_key", tex_name))
                        return (*provenance, loc) if provenance else (namespace, [texture_name], loc)

                for anim in mapping.get("animations", []):
                    if int(anim.get("chunk_id", -1)) == chunk_id and int(anim.get("texture_id", -1)) == texture_id:
                        loc = mapping.get("textures", {}).get(anim["name"])
                        namespace, texture_name = split_texture_key((loc or anim).get("texture_key", anim["name"]))
                        return (*provenance, loc or anim) if provenance else (namespace, [texture_name], loc or anim)

    if provenance:
        return *provenance, None

    # Standalone or Generic fallback
    namespace, candidates = extract_material_texture_keys(slot_mat)
    return namespace, candidates, None
