"""
jmc2obj format adapter, material naming conventions, and block/entity aliases.
"""

from __future__ import annotations

import re
import bpy
from .base import ImporterAdapter, base_texture_candidates, normalized_image_key
from .ice_cube import is_ice_cube_material
from ..constants import DEFAULT_NAMESPACE
from ..provenance import without_blender_suffix, is_mozi_material


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
                    norm_fp = fp.lower()
                    if "/tex/" in norm_fp or norm_fp.startswith("tex/"):
                        idx = norm_fp.find("tex/")
                        rel_path = fp[idx + 4:]
                        if rel_path.lower().endswith(".png"):
                            rel_path = rel_path[:-4]
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
        stem = without_blender_suffix(item)
        cur_ns = namespace
        path_part = stem
        if "_" in stem:
            prefix, rest = stem.split("_", 1)
            if prefix in ("minecraft", "jmc2obj") or not prefix.startswith("mtk"):
                cur_ns = prefix if prefix != "jmc2obj" else DEFAULT_NAMESPACE
                path_part = rest

        # Banner aliases
        if path_part.startswith("banner-"):
            banner_sub = path_part[len("banner-"):]
            if banner_sub in JMC2OBJ_BANNER_SHORT_ALIASES:
                candidates.append(JMC2OBJ_BANNER_SHORT_ALIASES[banner_sub])

        # Redstone aliases
        if path_part.startswith("block-redstone_dust_"):
            if "dot" in path_part:
                candidates.extend(["block/redstone_dust_dot", "redstone_dust_dot"])
            elif "line" in path_part:
                candidates.extend(["block/redstone_dust_line0", "block/redstone_dust_line", "redstone_dust_line0"])

        # Convert jmc2obj '-' to '/' for folder hierarchy
        if "-" in path_part:
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


class Jmc2objAdapter(ImporterAdapter):
    """jmc2obj exported material names, texture paths, and block/entity aliases."""

    identifier = "jmc2obj"
    description = "jmc2obj exported material names, texture paths, and block/entity aliases"

    def detect(self, mat: bpy.types.Material | None) -> bool:
        return is_jmc2obj_material(mat)

    def extract_keys(self, mat: bpy.types.Material) -> tuple[str, list[str]]:
        return jmc2obj_texture_candidates(mat)
