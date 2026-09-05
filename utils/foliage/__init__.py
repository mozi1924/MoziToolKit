"""
Foliage Wiggle Utilities Package for MoziToolKit.
"""

from .foliage_classifier import (
    classify_texture_key,
    assign_foliage_vertex_groups,
    GROUP_NAME_ALL,
    GROUP_NAME_LEAVES,
    GROUP_NAME_PLANTS,
    TARGET_SCOPE_ALL,
    TARGET_SCOPE_LEAVES,
    TARGET_SCOPE_PLANTS,
    TARGET_SCOPE_ITEMS,
    SCOPE_TO_GROUP,
)
try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

if HAS_BPY:
    from .geo_node_builder import (
        NODE_GROUP_NAME,
        MODIFIER_NAME,
        get_or_create_foliage_node_group,
        apply_foliage_modifier,
    )
else:
    NODE_GROUP_NAME = "MTK_Foliage_Wiggle"
    MODIFIER_NAME = "MTK_Foliage_Wiggle"
    get_or_create_foliage_node_group = None
    apply_foliage_modifier = None

__all__ = [
    "classify_texture_key",
    "assign_foliage_vertex_groups",
    "GROUP_NAME_ALL",
    "GROUP_NAME_LEAVES",
    "GROUP_NAME_PLANTS",
    "TARGET_SCOPE_ALL",
    "TARGET_SCOPE_LEAVES",
    "TARGET_SCOPE_PLANTS",
    "TARGET_SCOPE_ITEMS",
    "SCOPE_TO_GROUP",
    "NODE_GROUP_NAME",
    "MODIFIER_NAME",
    "get_or_create_foliage_node_group",
    "apply_foliage_modifier",
]
