"""
Foliage Classification and Vertex Group utilities for MoziToolKit.

Identifies foliage (leaves, flowers, grass plants, crops, vines, etc.)
from face attributes (e.g. `mtk_source_texture_key`) and creates/populates
vertex groups while protecting rigid structures (logs, terrain) from distortion.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Dict, Optional, Set, Tuple

if TYPE_CHECKING:
    import bpy

LEAF_KEYWORDS = [
    "leaves", "leaf", "azalea_leaves", "cherry_leaves", "mangrove_leaves"
]

PLANT_KEYWORDS = [
    r"\bgrass\b",
    r"\btall_grass",
    r"\bfern\b",
    r"\blarge_fern\b",
    r"\bflower\b",
    r"dandelion", "poppy", "orchid", "allium", "azure_bluet",
    r"tulip", "daisy", "cornflower", "lily_of_the_valley", "wither_rose",
    r"sunflower", "lilac", "rose_bush", "peony",
    r"wheat_", "carrots_", "potatoes_", "beetroots_", "melon_stem", "pumpkin_stem",
    r"sapling", "vine", "cave_vines", "twisting_vines", "weeping_vines",
    r"sugar_cane", "bamboo", "kelp", "seagrass", "hanging_roots", "spore_blossom",
    r"sweet_berry_bush", "pitcher_crop", "torchflower"
]

EXCLUDE_KEYWORDS = [
    "grass_block", "dirt_path", "podzol", "mycelium"
]

GROUP_NAME_ALL = "MTK_Foliage_All"
GROUP_NAME_LEAVES = "MTK_Foliage_Leaves"
GROUP_NAME_PLANTS = "MTK_Foliage_Plants"

TARGET_SCOPE_ALL = "ALL"
TARGET_SCOPE_LEAVES = "LEAVES"
TARGET_SCOPE_PLANTS = "PLANTS"

TARGET_SCOPE_ITEMS = [
    (TARGET_SCOPE_ALL, "All Foliage (Leaves & Plants)", "Apply wind wiggle to both leaves and plants/flowers"),
    (TARGET_SCOPE_LEAVES, "Leaves Only", "Apply wind wiggle only to tree leaves"),
    (TARGET_SCOPE_PLANTS, "Plants & Flowers Only", "Apply wind wiggle only to ground plants, grass, and flowers"),
]

SCOPE_TO_GROUP = {
    TARGET_SCOPE_ALL: GROUP_NAME_ALL,
    TARGET_SCOPE_LEAVES: GROUP_NAME_LEAVES,
    TARGET_SCOPE_PLANTS: GROUP_NAME_PLANTS,
}


def classify_texture_key(key_str: str) -> Optional[str]:
    """
    Returns 'LEAF', 'PLANT', or None based on the texture key path.
    """
    key_str = key_str.lower()
    
    for exc in EXCLUDE_KEYWORDS:
        if exc in key_str:
            return None

    for kw in LEAF_KEYWORDS:
        if kw in key_str:
            return 'LEAF'

    for pattern in PLANT_KEYWORDS:
        if re.search(pattern, key_str):
            return 'PLANT'

    return None


def assign_foliage_vertex_groups(
    obj: bpy.types.Object,
    protect_rigid_vertices: bool = True
) -> Dict[str, int]:
    """
    Scans the mesh face attribute `mtk_source_texture_key` and creates/populates:
    - MTK_Foliage_All
    - MTK_Foliage_Leaves
    - MTK_Foliage_Plants

    Returns summary dictionary with counts.
    """
    if not obj or obj.type != 'MESH' or not obj.data:
        return {}

    mesh = obj.data
    if "mtk_source_texture_key" not in mesh.attributes:
        return {}

    attr = mesh.attributes["mtk_source_texture_key"]
    if attr.domain != 'FACE':
        return {}

    leaf_verts: Set[int] = set()
    plant_verts: Set[int] = set()
    rigid_verts: Set[int] = set()

    for poly_idx, poly in enumerate(mesh.polygons):
        raw_val = attr.data[poly_idx].value
        if isinstance(raw_val, bytes):
            key_str = raw_val.decode('utf-8', errors='ignore')
        else:
            key_str = str(raw_val)

        category = classify_texture_key(key_str)
        if category == 'LEAF':
            leaf_verts.update(poly.vertices)
        elif category == 'PLANT':
            plant_verts.update(poly.vertices)
        else:
            rigid_verts.update(poly.vertices)

    if protect_rigid_vertices:
        leaf_verts = leaf_verts - rigid_verts
        plant_verts = plant_verts - rigid_verts

    all_foliage_verts = leaf_verts.union(plant_verts)

    def get_or_create_vg(name: str):
        vg = obj.vertex_groups.get(name)
        if not vg:
            vg = obj.vertex_groups.new(name=name)
        return vg

    # Clear existing assignments in these groups
    for name in (GROUP_NAME_ALL, GROUP_NAME_LEAVES, GROUP_NAME_PLANTS):
        vg = obj.vertex_groups.get(name)
        if vg:
            for v in mesh.vertices:
                vg.remove([v.index])

    summary = {
        "leaves_count": len(leaf_verts),
        "plants_count": len(plant_verts),
        "total_foliage_verts": len(all_foliage_verts),
        "rigid_verts": len(rigid_verts),
    }

    if not all_foliage_verts:
        return summary

    vg_all = get_or_create_vg(GROUP_NAME_ALL)
    vg_all.add(list(all_foliage_verts), 1.0, 'REPLACE')

    if leaf_verts:
        vg_leaves = get_or_create_vg(GROUP_NAME_LEAVES)
        vg_leaves.add(list(leaf_verts), 1.0, 'REPLACE')

    if plant_verts:
        vg_plants = get_or_create_vg(GROUP_NAME_PLANTS)
        vg_plants.add(list(plant_verts), 1.0, 'REPLACE')

    return summary
