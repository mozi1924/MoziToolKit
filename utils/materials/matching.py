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
    if detected_namespace in ("assets", "library", "ice_cube_asset_library"):
        detected_namespace = None
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
        elif (
            parts[0].endswith("_block")
            or parts[0].endswith("_texture")
            or parts[0].endswith("_cross")
            or any(k in parts[0] for k in ("tendril", "lantern", "campfire", "fire", "seagrass", "kelp", "pumpkin"))
        ):
            name = parts[1]
        else:
            if parts[0] not in ("library", "ice_cube_asset_library"):
                namespace = parts[0]
            name = parts[1]

    candidates = []
    detected_namespaces = []
    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                img_ns, key = extract_texture_provenance_from_image(node.image)
                if img_ns and img_ns not in ("assets", "library", "ice_cube_asset_library"):
                    detected_namespaces.append(img_ns)
                if key and not key.startswith("atlas_chunk_"):
                    candidates.append(key)

    if namespace == DEFAULT_NAMESPACE and detected_namespaces:
        namespace = detected_namespaces[0]

    clean_name = name.removesuffix(".png")
    if not clean_name.startswith("atlas_chunk_"):
        candidates.append(clean_name)
    return namespace, list(dict.fromkeys(candidates))


def generic_texture_candidates(mat: bpy.types.Material) -> tuple[str, list[str]]:
    return base_texture_candidates(mat)


def ice_cube_name_aliases(name: str) -> list[str]:
    aliases = []
    if "_conditional_" in name:
        aliases.append(name.replace("_conditional_", "_"))
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


# Ice Cube's entity names and 26.2 naming layout aliases
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
    # Heads
    "creeper head": "entity/creeper/creeper",
    "dragon head": "entity/enderdragon/dragon",
    "piglin head": "entity/piglin/piglin",
    "player head": "entity/player/wide/steve",
    "skeleton head": "entity/skeleton/skeleton",
    "wither skeleton head": "entity/skeleton/wither_skeleton",
    "zombie head": "entity/zombie/zombie",
    "wither charge head": "entity/wither/wither_invulnerable",

    # Horse Body Skins (Ice Cube names them '... Horse Armor')
    "black horse armor": "entity/horse/horse_black",
    "brown horse armor": "entity/horse/horse_brown",
    "chestnut horse armor": "entity/horse/horse_chestnut",
    "creamy horse armor": "entity/horse/horse_creamy",
    "dark brown horse armor": "entity/horse/horse_darkbrown",
    "gray horse armor": "entity/horse/horse_gray",
    "white horse armor": "entity/horse/horse_white",

    # Cats
    "tuxedo cat": "entity/cat/cat_black",
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

    # Axolotl & Mooshroom
    "lucy axolotl": "axolotl_lucy",
    "brown mooshroom": "mooshroom_brown",
    "mooshroom": "mooshroom_red",
    "brown mooshroom mushrooms": "block/brown_mushroom",
    "red mooshroom mushrooms": "block/red_mushroom",
    "mooshroom mushrooms": "block/red_mushroom",

    # Farm Animals & Variants
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

    # Rabbits
    "black and white rabbit": "rabbit_white_splotched",
    "the killer bunny": "rabbit_caerbannog",
    "salt and pepper rabbit": "rabbit_salt",
    "toast rabbit": "rabbit_toast",

    # Llamas
    "creamy llama": "entity/llama/llama_creamy",
    "gray llama": "entity/llama/llama_gray",
    "white llama": "entity/llama/llama_white",
    "brown llama": "entity/llama/llama_brown",
    "llama decoration": "entity/equipment/llama_body/white",

    # Parrots
    "red parrot": "entity/parrot/parrot_red_blue",
    "jungle parrot": "entity/parrot/parrot_red_blue",
    "blue parrot": "entity/parrot/parrot_blue",
    "cyan parrot": "entity/parrot/parrot_cyan",
    "green parrot": "entity/parrot/parrot_green",
    "grey parrot": "entity/parrot/parrot_grey",

    # Fish & Mobs
    "small tropical fish": "entity/fish/tropical_a",
    "tropical fish a": "entity/fish/tropical_a",
    "large tropical fish": "entity/fish/tropical_b",
    "tropical fish b": "entity/fish/tropical_b",
    "m_48fb624d-1fe0-62f6-cbd5-9e84d4f37f7d": "entity/fish/pufferfish",
    "m_7417965d-36ac-0683-5e20-769f38e2593e": "entity/fish/pufferfish",
    "bogged overlay": "entity/skeleton/bogged_overlay",
    "stray overlay": "entity/skeleton/stray_overlay",
    "m_34375663-2091-1652-f671-bfe08576cfa2": "entity/skeleton/stray_overlay",
    "slime outer": "entity/slime/slime",
    "chargedcreeper": "entity/creeper/creeper_armor",
    "drownedouter": "drowned_outer_layer",
    "iron golem cracked high": "entity/iron_golem/iron_golem_crackiness_high",
    "iron golem cracked low": "entity/iron_golem/iron_golem_crackiness_low",
    "iron golem cracked medium": "entity/iron_golem/iron_golem_crackiness_medium",
    "strider saddle": "entity/equipment/strider_saddle/saddle",
    "pig saddle": "entity/equipment/pig_saddle/saddle",
    "chest": "entity/chest/normal",
    "chest left": "entity/chest/normal_left",
    "chest right": "entity/chest/normal_right",
    "ender chest": "entity/chest/ender",
    "trapped chest": "entity/chest/trapped",
    "trapped chest left": "entity/chest/trapped_left",
    "trapped chest right": "entity/chest/trapped_right",
    "conduit base": "entity/conduit/base",
    "conduit cage": "entity/conduit/cage",
    "conduit wind": "entity/conduit/wind",
    "end crystal beam": "entity/end_crystal/end_crystal_beam",
    "lead knot": "entity/lead_knot",
    "shield": "entity/shield_base",
    "shield pattern": "entity/shield_base_nopattern",
    "shulker box": "entity/shulker/shulker",
    "m_9ce7088c-085a-56ae-0fbf-05927c923b4b": "entity/shulker/spark",
    "trident": "entity/trident",
    "spyglass": "entity/spyglass",
    "bell": "entity/bell/bell_body",
    "oak boat": "entity/boat/oak",
    "raft": "entity/boat/bamboo",
    "oak hanging sign": "block/oak_hanging_sign",
    "oak sign": "block/oak_sign",
    "red bed": "block/red_bed_head_up",

    # Blocks & 26.2 Mojang Renames (e.g. chain -> iron_chain)
    "chain_all": "block/iron_chain",
    "item_chain": "item/iron_chain",
    "chain": "block/iron_chain",
    "iron_bars_all": "block/iron_bars",
    "powered_rail_on": "block/powered_rail_on",
    "glow_lichen_glow_lichen": "block/glow_lichen",
    "water_cauldron_full_content": "block/water_still",
    "lava_cauldron_content": "block/lava_still",
    "nether_portal_ns_portal": "block/nether_portal",
    "campfire_lit_log": "block/campfire_log_lit",
    "soul_campfire_lit_log": "block/soul_campfire_log_lit",
    "campfire_fire_block/campfire_fire.png": "block/campfire_fire",
    "campfire_lit_log_block/campfire_log_lit.png": "block/campfire_log_lit",
    "soul_campfire_fire_block/soul_campfire_fire.png": "block/soul_campfire_fire",
    "soul_campfire_lit_log_block/soul_campfire_log_lit.png": "block/soul_campfire_log_lit",
    "sculk_mirrored_all": "block/sculk",
    "sculk_catalyst_bloom_side": "block/sculk_catalyst_side_bloom",
    "sculk_catalyst_bloom_top": "block/sculk_catalyst_top_bloom",
    "item_clock_00": "item/clock_00",
    "item_compass_00": "item/compass_00",
    "item_recovery_compass_00": "item/recovery_compass_00",
}


def _resolve_ice_cube_armor_aliases(name: str) -> list[str]:
    """Resolve armor piece materials to modern 26.2 equipment/humanoid and legacy models/armor."""
    name_lower = name.lower()
    if not any(k in name_lower for k in ("boots", "chestplate", "helmet", "leggings")):
        return []

    mat_type = None
    for t in ("diamond", "golden", "gold", "iron", "chainmail", "netherite", "leather"):
        if t in name_lower:
            mat_type = t
            break
    if not mat_type:
        return []

    is_gold = (mat_type in ("gold", "golden"))
    canon_mat = "gold" if is_gold else mat_type
    legacy_mat = "gold" if is_gold else mat_type
    is_leggings = ("leggings" in name_lower)
    is_overlay = ("overlay" in name_lower)

    cands = []
    if is_leggings:
        if is_overlay:
            cands.extend([
                f"entity/equipment/humanoid_leggings/{canon_mat}_overlay",
                f"models/armor/{legacy_mat}_layer_2_overlay",
                f"{canon_mat}_layer_2_overlay",
            ])
        else:
            cands.extend([
                f"entity/equipment/humanoid_leggings/{canon_mat}",
                f"models/armor/{legacy_mat}_layer_2",
                f"{canon_mat}_layer_2",
            ])
    else:
        if is_overlay:
            cands.extend([
                f"entity/equipment/humanoid/{canon_mat}_overlay",
                f"models/armor/{legacy_mat}_layer_1_overlay",
                f"{canon_mat}_layer_1_overlay",
            ])
        else:
            cands.extend([
                f"entity/equipment/humanoid/{canon_mat}",
                f"models/armor/{legacy_mat}_layer_1",
                f"{canon_mat}_layer_1",
            ])
    return cands


def _resolve_ice_cube_fire_aliases(name: str) -> list[str]:
    """Resolve multipart animated fire textures to fire_0 / fire_1 stems."""
    name_lower = name.lower()
    if "campfire" in name_lower:
        return []
    if "soul_fire" in name_lower:
        if any(digit in name_lower for digit in ("1", "alt1")):
            return ["block/soul_fire_1", "soul_fire_1"]
        return ["block/soul_fire_0", "soul_fire_0"]
    elif "fire_" in name_lower or name_lower.startswith("fire"):
        if any(digit in name_lower for digit in ("1", "alt1")):
            return ["block/fire_1", "fire_1"]
        return ["block/fire_0", "fire_0"]
    return []


def _resolve_ice_cube_sculk_and_lantern_aliases(name: str) -> list[str]:
    """Resolve sculk sensor tendrils and lantern textures."""
    name_lower = name.lower()
    cands = []
    if "sculk_sensor" in name_lower:
        if "calibrated" in name_lower:
            cands.extend([
                "block/calibrated_sculk_sensor_amethyst",
                "block/calibrated_sculk_sensor_top",
                "block/calibrated_sculk_sensor_input_side",
                "calibrated_sculk_sensor_amethyst",
            ])
        elif "active" in name_lower:
            cands.extend([
                "block/sculk_sensor_tendril_active",
                "sculk_sensor_tendril_active",
                "block/sculk_sensor_tendril_inactive",
            ])
        else:
            cands.extend([
                "block/sculk_sensor_tendril_inactive",
                "sculk_sensor_tendril_inactive",
                "block/sculk_sensor_tendril_active",
            ])
    if "lantern" in name_lower:
        if "soul" in name_lower:
            cands.extend(["block/soul_lantern", "soul_lantern"])
        else:
            cands.extend(["block/lantern", "lantern"])
    return cands


def _resolve_ice_cube_blocks_and_plants_aliases(name: str) -> list[str]:
    """Resolve seagrass, kelp, dripstone, pumpkin, and hyphae block names."""
    name_lower = name.lower()
    cands = []
    if "tall_seagrass_bottom" in name_lower:
        cands.extend(["block/tall_seagrass_bottom", "tall_seagrass_bottom"])
    elif "tall_seagrass_top" in name_lower:
        cands.extend(["block/tall_seagrass_top", "tall_seagrass_top"])
    elif "seagrass" in name_lower:
        cands.extend(["block/seagrass", "seagrass"])
    elif "kelp_plant" in name_lower:
        cands.extend(["block/kelp_plant", "kelp_plant"])
    elif "kelp" in name_lower:
        cands.extend(["block/kelp", "kelp"])
    elif "pointed_dripstone" in name_lower:
        stem = name_lower.removesuffix("_cross").removesuffix(".001")
        if "_" in stem and stem.rsplit("_", 1)[1].isdigit():
            stem = stem.rsplit("_", 1)[0]
        cands.extend([f"block/{stem}", stem])
    elif "carved_pumpkin" in name_lower:
        if "front" in name_lower:
            cands.extend(["block/carved_pumpkin", "carved_pumpkin"])
        elif "side" in name_lower:
            cands.extend(["block/pumpkin_side", "pumpkin_side"])
        elif "top" in name_lower:
            cands.extend(["block/pumpkin_top", "pumpkin_top"])
    elif "creaking_heart" in name_lower:
        if "active" in name_lower:
            if "end" in name_lower:
                cands.extend(["block/creaking_heart_top_awake", "block/creaking_heart_top_active", "creaking_heart_top_awake"])
            else:
                cands.extend(["block/creaking_heart_awake", "block/creaking_heart_active", "creaking_heart_awake"])
        else:
            if "end" in name_lower:
                cands.extend(["block/creaking_heart_top_dormant", "block/creaking_heart_top", "creaking_heart_top_dormant"])
            else:
                cands.extend(["block/creaking_heart_dormant", "block/creaking_heart", "creaking_heart_dormant"])
    elif "crimson_hyphae" in name_lower:
        if "end" in name_lower:
            cands.extend(["block/crimson_hyphae", "block/crimson_stem_top", "crimson_hyphae", "crimson_stem_top"])
        else:
            cands.extend(["block/crimson_hyphae", "block/crimson_stem", "crimson_hyphae", "crimson_stem"])
    elif "warped_hyphae" in name_lower:
        if "end" in name_lower:
            cands.extend(["block/warped_hyphae", "block/warped_stem_top", "warped_hyphae", "warped_stem_top"])
        else:
            cands.extend(["block/warped_hyphae", "block/warped_stem", "warped_hyphae", "warped_stem"])
    elif "frosted_ice_" in name_lower:
        digits = re.findall(r"\d+", name_lower)
        if digits:
            idx = str(int(digits[-1]))
            cands.extend([f"block/frosted_ice_{idx}", f"frosted_ice_{idx}"])
    elif "prismarine_slab" in name_lower:
        cands.extend(["block/prismarine", "prismarine"])
    elif "respawn_anchor_" in name_lower:
        digits = re.findall(r"\d+", name_lower)
        if digits:
            idx = digits[0]
            cands.extend([f"block/respawn_anchor_top_{idx}", f"respawn_anchor_top_{idx}"])
        cands.extend(["block/respawn_anchor_top", "respawn_anchor_top"])
    return cands


def ice_cube_texture_candidates(mat: bpy.types.Material) -> tuple[str, list[str]]:
    namespace, candidates = base_texture_candidates(mat)
    if mat.get("mtk:source_namespace"):
        return namespace, candidates

    source_name = without_blender_suffix(mat.name.strip().lower())
    raw_name = mat.name.strip().lower()

    extra = []
    lookup_keys = list(candidates) + [source_name, raw_name]
    for key in lookup_keys:
        extra.extend(ice_cube_name_aliases(key))
        extra.extend(ice_cube_legacy_aliases(key))
        if key in ICE_CUBE_ENTITY_ALIASES:
            extra.append(ICE_CUBE_ENTITY_ALIASES[key])
        if key in ICE_CUBE_MATERIAL_NAME_ALIASES:
            extra.append(ICE_CUBE_MATERIAL_NAME_ALIASES[key])
        extra.extend(_resolve_ice_cube_armor_aliases(key))
        extra.extend(_resolve_ice_cube_fire_aliases(key))
        extra.extend(_resolve_ice_cube_sculk_and_lantern_aliases(key))
        extra.extend(_resolve_ice_cube_blocks_and_plants_aliases(key))

    for c in list(extra):
        extra.extend(ice_cube_name_aliases(c))
        extra.extend(ice_cube_legacy_aliases(c))
        if c in ICE_CUBE_ENTITY_ALIASES:
            extra.append(ICE_CUBE_ENTITY_ALIASES[c])
        if c in ICE_CUBE_MATERIAL_NAME_ALIASES:
            extra.append(ICE_CUBE_MATERIAL_NAME_ALIASES[c])

    candidates.extend(extra)
    return namespace, list(dict.fromkeys(candidates))


JMC2OBJ_BANNER_SHORT_ALIASES = {
    "pattern_base": "entity/banner/base",
    "pattern_bs": "entity/banner/stripe_bottom",
    "pattern_ts": "entity/banner/stripe_top",
    "pattern_ls": "entity/banner/stripe_left",
    "pattern_rs": "entity/banner/stripe_right",
    "pattern_cs": "entity/banner/stripe_center",
    "pattern_ms": "entity/banner/stripe_middle",
    "pattern_drs": "entity/banner/stripe_downright",
    "pattern_dls": "entity/banner/stripe_downleft",
    "pattern_ss": "entity/banner/small_stripes",
    "pattern_cr": "entity/banner/cross",
    "pattern_sc": "entity/banner/straight_cross",
    "pattern_ld": "entity/banner/diagonal_left",
    "pattern_rud": "entity/banner/diagonal_right",
    "pattern_lud": "entity/banner/diagonal_up_left",
    "pattern_rd": "entity/banner/diagonal_up_right",
    "pattern_vh": "entity/banner/half_vertical",
    "pattern_vhr": "entity/banner/half_vertical_right",
    "pattern_hh": "entity/banner/half_horizontal",
    "pattern_hhb": "entity/banner/half_horizontal_bottom",
    "pattern_bl": "entity/banner/square_bottom_left",
    "pattern_br": "entity/banner/square_bottom_right",
    "pattern_tl": "entity/banner/square_top_left",
    "pattern_tr": "entity/banner/square_top_right",
    "pattern_bt": "entity/banner/triangle_bottom",
    "pattern_tt": "entity/banner/triangle_top",
    "pattern_bts": "entity/banner/triangles_bottom",
    "pattern_tts": "entity/banner/triangles_top",
    "pattern_mc": "entity/banner/circle",
    "pattern_mr": "entity/banner/rhombus",
    "pattern_bo": "entity/banner/border",
    "pattern_cbo": "entity/banner/curly_border",
    "pattern_bri": "entity/banner/bricks",
    "pattern_gra": "entity/banner/gradient",
    "pattern_gru": "entity/banner/gradient_up",
    "pattern_cre": "entity/banner/creeper",
    "pattern_sku": "entity/banner/skull",
    "pattern_flo": "entity/banner/flower",
    "pattern_moj": "entity/banner/mojang",
    "pattern_glb": "entity/banner/globe",
    "pattern_pig": "entity/banner/piglin",
    "pattern_flw": "entity/banner/flow",
    "pattern_gus": "entity/banner/guster",
}

JMC2OBJ_BIOME_SUFFIXES = (
    "-desert", "-forest", "-swamp", "-taiga", "-snow", "-ocean", "-jungle",
    "-badlands", "-savanna", "-dark_forest", "-birch_forest", "-plains",
    "-meadow", "-mangrove", "-cherry_grove", "-cold_ocean", "-warm_ocean",
)


def is_jmc2obj_material(mat: bpy.types.Material | None) -> bool:
    """Detect materials exported by jmc2obj via naming conventions, image paths, or metadata."""
    if not mat:
        return False
    if is_mozi_material(mat) or is_ice_cube_material(mat):
        return False
    if mat.get("mtk:source_importer") == "jmc2obj":
        return True

    name = without_blender_suffix(mat.name.strip().lower())
    if re.match(r"^(?:minecraft|jmc2obj)_(?:block|entity|item|banner|painting)-", name):
        return True
    if name.startswith("jmc2obj_"):
        return True
    if re.match(r"^[a-z0-9_]+_(?:block|entity|item)-[a-z0-9_\-]+", name):
        return True

    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                fp = (node.image.filepath or node.image.name or "").replace("\\", "/").lower()
                if "/tex/minecraft/" in fp or "tex/minecraft/" in fp or "tex/jmc2obj/" in fp:
                    return True
                img_name = without_blender_suffix(node.image.name.lower())
                if re.match(r"^(?:minecraft|jmc2obj)_(?:block|entity|item)-", img_name):
                    return True

    return False


def jmc2obj_texture_candidates(mat: bpy.types.Material) -> tuple[str, list[str]]:
    """Extract candidate texture keys for materials exported by jmc2obj."""
    namespace, base_cands = base_texture_candidates(mat)
    if mat.get("mtk:source_namespace"):
        return namespace, base_cands

    candidates: list[str] = []
    source_name = without_blender_suffix(mat.name.strip().lower())
    raw_names = [source_name]

    # Collect raw names from image nodes as well
    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                fp = (node.image.filepath or "").replace("\\", "/").strip()
                if fp:
                    # Check for tex/<namespace>/<category>/<name>.png
                    norm_fp = fp.lower()
                    if "/tex/" in norm_fp or norm_fp.startswith("tex/"):
                        idx = norm_fp.find("tex/")
                        rel_path = fp[idx + 4:]
                        if rel_path.lower().endswith(".png"):
                            rel_path = rel_path[:-4]
                        # rel_path is e.g. "minecraft/block/stone" or "minecraft/entity/chest/normal"
                        if "/" in rel_path:
                            ns, tex_path = rel_path.split("/", 1)
                            namespace = ns.lower()
                            candidates.append(tex_path)
                            if "/" in tex_path:
                                candidates.append(tex_path.split("/", 1)[1])
                                candidates.append(tex_path.rsplit("/", 1)[1])
                img_key = normalized_image_key(node.image)
                if img_key and img_key not in raw_names:
                    raw_names.append(img_key)

    for item in raw_names:
        # Strip blender suffix if any
        stem = without_blender_suffix(item)

        # Detect namespace and path from jmc2obj format: e.g. minecraft_block-stone
        cur_ns = namespace
        path_part = stem
        if "_" in stem:
            prefix, rest = stem.split("_", 1)
            if prefix in ("minecraft", "jmc2obj") or not prefix.startswith("mtk"):
                cur_ns = prefix if prefix != "jmc2obj" else DEFAULT_NAMESPACE
                path_part = rest

        # Check jmc2obj special banner aliases
        if path_part.startswith("banner-"):
            banner_sub = path_part[len("banner-"):]
            if banner_sub in JMC2OBJ_BANNER_SHORT_ALIASES:
                candidates.append(JMC2OBJ_BANNER_SHORT_ALIASES[banner_sub])

        # Check jmc2obj special redstone aliases
        if path_part.startswith("block-redstone_dust_"):
            if "dot" in path_part:
                candidates.extend(["block/redstone_dust_dot", "redstone_dust_dot"])
            elif "line" in path_part:
                candidates.extend(["block/redstone_dust_line0", "block/redstone_dust_line", "redstone_dust_line0"])

        # Convert jmc2obj '-' to '/' for folder hierarchy
        if "-" in path_part:
            # Check for biome suffix stripping first: e.g. block-grass_block_top-desert
            for b_suffix in JMC2OBJ_BIOME_SUFFIXES:
                if path_part.endswith(b_suffix):
                    stripped_path = path_part[:-len(b_suffix)]
                    converted_stripped = stripped_path.replace("-", "/")
                    candidates.append(converted_stripped + b_suffix)
                    candidates.append(converted_stripped)
                    if "/" in converted_stripped:
                        candidates.append(converted_stripped.split("/", 1)[1] + b_suffix)
                        candidates.append(converted_stripped.split("/", 1)[1])
                    break

            converted = path_part.replace("-", "/")
            candidates.append(converted)
            if "/" in converted:
                candidates.append(converted.split("/", 1)[1])
                candidates.append(converted.rsplit("/", 1)[1])
        else:
            candidates.append(path_part)

    # Add base candidates from nodes/name
    candidates.extend(base_cands)

    return namespace, list(dict.fromkeys(c for c in candidates if c))


def is_ice_cube_internal_face_material(mat: bpy.types.Material | None) -> bool:
    """Return whether Ice Cube marks this slot as intentionally invisible or procedural."""
    if not is_ice_cube_material(mat):
        return False
    name = without_blender_suffix(mat.name.strip().lower())
    return (
        bool(re.fullmatch(r"internal_face_deletion(?:_[0-9]+)?", name))
        or name in ("dots stroke", "enchantmentglintnode")
        or name.startswith("item_template_spawn_egg")
    )


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
JMC2OBJ_PRESET = MaterialMatchPreset(
    identifier="jmc2obj",
    description="jmc2obj exported material names, texture paths, and block/entity aliases",
    detects=is_jmc2obj_material,
    extract_keys=jmc2obj_texture_candidates,
)
GENERIC_PRESET = MaterialMatchPreset(
    identifier="generic",
    description="Literal image and material-name matching",
    detects=lambda _mat: True,
    extract_keys=generic_texture_candidates,
)
MATCH_PRESETS = (ICE_CUBE_PRESET, JMC2OBJ_PRESET, GENERIC_PRESET)


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


def get_material_animation_info(mat: bpy.types.Material | None) -> dict | None:
    """Return animation frame dimensions if mat is an animated material, else None.

    Returns a dictionary with keys:
    - 'frame_width': float
    - 'frame_height': float
    - 'img_width': float
    - 'img_height': float
    - 'total_frames': int
    """
    if not mat or not mat.use_nodes or not mat.node_tree:
        return None

    # 1. Check for MC_Animated_UV_Mapping node group
    for n in mat.node_tree.nodes:
        if n.type == "GROUP" and n.node_tree and "UV_Mapping" in n.node_tree.name:
            fw = float(n.inputs["Frame Width"].default_value) if "Frame Width" in n.inputs else 16.0
            fh = float(n.inputs["Frame Height"].default_value) if "Frame Height" in n.inputs else 16.0
            iw = float(n.inputs["Image Width"].default_value) if "Image Width" in n.inputs else 16.0
            ih = float(n.inputs["Image Height"].default_value) if "Image Height" in n.inputs else 16.0
            if ih > fh and fh > 0:
                return {
                    "frame_width": fw,
                    "frame_height": fh,
                    "img_width": iw,
                    "img_height": ih,
                    "total_frames": max(1, int(round(ih / fh))),
                }

    # 2. Check for MC .mcmeta Scheduler node group with images
    sched_node = next(
        (n for n in mat.node_tree.nodes if n.type == "GROUP" and n.node_tree and "Scheduler" in n.node_tree.name),
        None,
    )
    if sched_node and "Total Frames" in sched_node.inputs:
        tf = int(round(sched_node.inputs["Total Frames"].default_value))
        if tf > 1:
            for n in mat.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image and n.image.size[0] > 0 and n.image.size[1] > 0:
                    iw = float(n.image.size[0])
                    ih = float(n.image.size[1])
                    fh = max(1.0, ih / tf)
                    fw = iw
                    return {
                        "frame_width": fw,
                        "frame_height": fh,
                        "img_width": iw,
                        "img_height": ih,
                        "total_frames": tf,
                    }

    # 3. Check for vertical animation strip ratio heuristic on image nodes
    for n in mat.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image and n.image.size[0] > 0 and n.image.size[1] > 0:
            iw, ih = int(n.image.size[0]), int(n.image.size[1])
            if ih > iw and ih % iw == 0:
                tf = ih // iw
                return {
                    "frame_width": float(iw),
                    "frame_height": float(iw),
                    "img_width": float(iw),
                    "img_height": float(ih),
                    "total_frames": tf,
                }

    return None


def get_texture_info_animation_info(tex_info: dict | None, img: bpy.types.Image | None = None) -> dict | None:
    """Return animation frame dimensions for a texture_info dict if animated, else None.

    Returns a dictionary with keys:
    - 'frame_width': float
    - 'frame_height': float
    - 'img_width': float
    - 'img_height': float
    - 'total_frames': int
    """
    if not tex_info or not isinstance(tex_info, dict):
        return None

    mcmeta = tex_info.get("albedo_mcmeta")
    albedo_path = tex_info.get("albedo")

    iw, ih = 0, 0
    if img and img.size[0] > 0 and img.size[1] > 0:
        iw, ih = int(img.size[0]), int(img.size[1])
    elif albedo_path and Path(albedo_path).exists():
        if bpy and hasattr(bpy, "data"):
            resolved_albedo = str(Path(albedo_path).resolve())
            for existing in bpy.data.images:
                if existing.filepath and str(Path(bpy.path.abspath(existing.filepath)).resolve()) == resolved_albedo:
                    if existing.size[0] > 0 and existing.size[1] > 0:
                        iw, ih = int(existing.size[0]), int(existing.size[1])
                        break
        if iw <= 0 or ih <= 0:
            try:
                from PIL import Image
                with Image.open(albedo_path) as pil_img:
                    iw, ih = pil_img.size
            except Exception:
                pass

    if iw <= 0 or ih <= 0:
        return None

    fw = iw
    fh = iw
    is_anim = False
    if mcmeta and isinstance(mcmeta, dict):
        fw = int(mcmeta.get("width") or iw)
        fh = int(mcmeta.get("height") or fw)
        frames = mcmeta.get("frames", [])
        total_frames = ih // fh if fh > 0 else 1
        if total_frames > 1 or (isinstance(frames, list) and len(frames) > 1):
            is_anim = True
    elif ih > iw and ih % iw == 0:
        is_anim = True
        fw = iw
        fh = iw

    if is_anim and ih > fh and fh > 0:
        return {
            "frame_width": float(fw),
            "frame_height": float(fh),
            "img_width": float(iw),
            "img_height": float(ih),
            "total_frames": max(1, ih // fh),
        }
    return None

