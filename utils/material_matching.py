"""Source-aware Minecraft material texture-key matching.

Every importer has its own naming conventions.  A matching preset isolates
those conventions so the replacement pipeline never has to guess which
importer created a material.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import bpy


import json
from .atlas_layout import find_texture_id_from_atlas_uv


def without_blender_suffix(value: str) -> str:
    """Remove Blender's duplicate suffix without changing an actual name."""
    if "." in value and value.rsplit(".", 1)[1].isdigit():
        return value.rsplit(".", 1)[0]
    return value


def normalized_image_key(image: bpy.types.Image) -> str:
    """Return an image datablock's basename as a resource-pack texture key."""
    raw_name = Path(image.filepath).name if image.filepath else image.name
    if ":" in raw_name:
        raw_name = raw_name.split(":", 1)[0]
    key = without_blender_suffix(raw_name.lower())
    if key.endswith(".png"):
        key = key[:-4]
    if len(key) > 5 and key[-5] == "_" and key[-4:].isdigit():
        key = key[:-5]
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
            if node.name == "MC Atlas UV Decoder" or node.type == "GROUP" and node.node_tree and node.node_tree.name == "MC_Atlas_UV_Decoder":
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
    namespace = "minecraft"
    if ":" in name:
        parts = name.split(":")
        if len(parts) >= 3 and parts[0] == "mtk":
            namespace = parts[1]
            name = parts[2]
        else:
            namespace, name = parts[0], parts[1]

    candidates = []
    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                key = normalized_image_key(node.image)
                if key and not key.startswith("atlas_chunk_"):
                    candidates.append(key)
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


# Ice Cube's entity names predate Mojang's 26.2 naming layout.  Every entry
# below was checked against the vanilla 26.2 Fabric JAR; this table is never
# used by generic/JMC2Obj/Mineways materials.
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


def extract_material_texture_keys(mat: bpy.types.Material) -> tuple[str, list[str]]:
    """Extract candidates using the preset detected from material metadata."""
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
        return "minecraft", [], None

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
                        return "minecraft", [tex_name], loc

                for anim in mapping.get("animations", []):
                    if int(anim.get("chunk_id", -1)) == chunk_id and int(anim.get("texture_id", -1)) == texture_id:
                        loc = mapping.get("textures", {}).get(anim["name"])
                        return "minecraft", [anim["name"]], loc or anim

    # Standalone or Generic fallback
    namespace, candidates = extract_material_texture_keys(slot_mat)
    return namespace, candidates, None

