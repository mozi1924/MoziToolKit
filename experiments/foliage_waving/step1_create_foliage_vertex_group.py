"""
Foliage Vertex Group Generator for MoziToolKit / Minecraft World Sections.

This script identifies foliage (leaves, flowers, grass plants, crops, vines, etc.)
from the mesh's face attribute `mtk_source_texture_key` and assigns the corresponding
vertices to Vertex Groups (e.g. 'MTK_Foliage_Leaves', 'MTK_Foliage_Plants', or 'MTK_Foliage_All').

Critical Feature:
Vertices shared between foliage (leaves/plants) and rigid structures (tree logs, dirt, stone)
are explicitly EXCLUDED by default (or can be split), preventing tree trunks from being dragged/distorted!
"""

import bpy
import re

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


def classify_texture_key(key_str: str):
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
    group_prefix: str = "MTK_Foliage",
    create_subgroups: bool = True,
    protect_rigid_vertices: bool = True
):
    """
    Scans the mesh face attribute `mtk_source_texture_key` and assigns
    vertices to vertex groups.
    
    :param protect_rigid_vertices: If True, vertices shared with non-foliage
           (such as tree trunks/logs, dirt, stone) will be excluded so that
           rigid structures never move or deform with the leaves!
    """
    if obj.type != 'MESH':
        print(f"Object {obj.name} is not a mesh.")
        return {}

    mesh = obj.data
    if "mtk_source_texture_key" not in mesh.attributes:
        print(f"Mesh {mesh.name} has no 'mtk_source_texture_key' attribute.")
        return {}

    attr = mesh.attributes["mtk_source_texture_key"]
    if attr.domain != 'FACE':
        print(f"Attribute 'mtk_source_texture_key' is not on domain FACE (found {attr.domain}).")
        return {}

    leaf_verts = set()
    plant_verts = set()
    rigid_verts = set()

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
        # Exclude vertices that belong to tree trunks, branches or terrain
        leaf_verts = leaf_verts - rigid_verts
        plant_verts = plant_verts - rigid_verts

    all_foliage_verts = leaf_verts.union(plant_verts)

    def get_or_create_vg(name):
        vg = obj.vertex_groups.get(name)
        if not vg:
            vg = obj.vertex_groups.new(name=name)
        return vg

    # Clear old weights for clean update
    for name in [f"{group_prefix}_All", f"{group_prefix}_Leaves", f"{group_prefix}_Plants"]:
        vg = obj.vertex_groups.get(name)
        if vg:
            for v in mesh.vertices:
                vg.remove([v.index])

    summary = {
        "leaves_count": len(leaf_verts),
        "plants_count": len(plant_verts),
        "total_foliage_verts": len(all_foliage_verts),
        "protected_rigid_verts": len(rigid_verts)
    }

    if not all_foliage_verts:
        print(f"No foliage vertices detected on {obj.name}.")
        return summary

    vg_all = get_or_create_vg(f"{group_prefix}_All")
    vg_all.add(list(all_foliage_verts), 1.0, 'REPLACE')

    if create_subgroups:
        if leaf_verts:
            vg_leaves = get_or_create_vg(f"{group_prefix}_Leaves")
            vg_leaves.add(list(leaf_verts), 1.0, 'REPLACE')

        if plant_verts:
            vg_plants = get_or_create_vg(f"{group_prefix}_Plants")
            vg_plants.add(list(plant_verts), 1.0, 'REPLACE')

    print(f"Processed {obj.name}: {len(leaf_verts)} leaf verts (isolated from trunk), {len(plant_verts)} plant verts.")
    return summary


def run_on_selected_or_active():
    targets = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']
    if not targets and bpy.context.active_object and bpy.context.active_object.type == 'MESH':
        targets = [bpy.context.active_object]

    total_results = {}
    for obj in targets:
        res = assign_foliage_vertex_groups(obj, protect_rigid_vertices=True)
        total_results[obj.name] = res

    return total_results


if __name__ == "__main__":
    run_on_selected_or_active()
