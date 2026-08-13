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


def base_texture_candidates(mat: bpy.types.Material) -> tuple[str, list[str]]:
    """Extract literal image and material-name candidates shared by all presets."""
    if not mat:
        return "", []
    if mat.get("mtk:source_namespace") and mat.get("mtk:source_texture"):
        return str(mat["mtk:source_namespace"]), [str(mat["mtk:source_texture"])]

    name = without_blender_suffix(mat.name.strip().lower())
    namespace = "minecraft"
    if ":" in name:
        namespace, name = name.split(":", 1)

    candidates = []
    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                key = normalized_image_key(node.image)
                if key:
                    candidates.append(key)
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
