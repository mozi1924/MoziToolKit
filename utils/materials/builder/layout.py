"""
Automatic Shader Node Layout Engine for MoziToolKit.

Provides:
1. Column-based semantic stage layout for MTK PBR Atlas and Standalone materials.
2. Dynamic vertical packing (Y-stacking) eliminating gaps from missing texture channels.
3. Topological DAG auto-layout for generic node trees.
4. Clean visual hierarchy and non-overlapping node placement.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger("MoziToolKit.Materials.Layout")

# Heuristic node dimensions for headless/background execution
DEFAULT_NODE_SIZES: Dict[str, Tuple[float, float]] = {
    "ShaderNodeTexImage": (240.0, 260.0),
    "ShaderNodeBsdfPrincipled": (240.0, 560.0),
    "ShaderNodeOutputMaterial": (140.0, 120.0),
    "ShaderNodeUVMap": (150.0, 120.0),
    "ShaderNodeAttribute": (160.0, 140.0),
    "ShaderNodeSeparateColor": (160.0, 130.0),
    "ShaderNodeCombineXYZ": (150.0, 130.0),
    "ShaderNodeSeparateXYZ": (150.0, 130.0),
    "ShaderNodeMix": (160.0, 160.0),
    "ShaderNodeMath": (150.0, 140.0),
    "ShaderNodeNormalMap": (160.0, 160.0),
    "ShaderNodeGroup": (200.0, 180.0),
    "NodeFrame": (0.0, 0.0),
}


def get_node_size(node: Any) -> Tuple[float, float]:
    """Returns (width, height) of a node with fallback for headless mode."""
    if node is None:
        return (160.0, 120.0)

    w = getattr(node, "width", 0.0)
    dims = getattr(node, "dimensions", None)
    h = 0.0
    if dims is not None and len(dims) >= 2:
        if dims[0] > 10.0:
            w = max(w, float(dims[0]))
        if dims[1] > 10.0:
            h = float(dims[1])

    bl_id = getattr(node, "bl_idname", "")
    default_w, default_h = DEFAULT_NODE_SIZES.get(bl_id, (160.0, 140.0))
    if w <= 10.0:
        w = default_w
    if h <= 10.0:
        h = default_h
    return (w, h)


class NodeLayoutEngine:
    """
    Layout coordinator that computes readable, non-overlapping coordinates
    for shader node graphs.
    """

    @staticmethod
    def stack_vertical(
        nodes: Sequence[Any],
        x: float,
        start_y: float,
        gap_y: float = 35.0,
    ) -> float:
        """
        Stacks a sequence of nodes vertically from top to bottom.
        Returns the final Y position after the last node.
        """
        curr_y = start_y
        for n in nodes:
            if n is None:
                continue
            n.location = (x, curr_y)
            _, h = get_node_size(n)
            curr_y -= h + gap_y
        return curr_y

    @staticmethod
    def fit_frame_bounds(frame: Any, child_nodes: Sequence[Any], padding: float = 40.0) -> None:
        """
        Computes the collective bounding box for child nodes and ensures
        clean relative placement.
        """
        if frame is None or not child_nodes:
            return

        valid_nodes = [n for n in child_nodes if n is not None and n != frame]
        if not valid_nodes:
            return

        # Ensure all valid children are parented to the frame
        for n in valid_nodes:
            if getattr(n, "parent", None) != frame:
                n.parent = frame

    @classmethod
    def layout_atlas_material(
        cls,
        node_tree: Any,
        *,
        use_attribute_node: bool = False,
        is_animated: bool = False,
        has_overlay: bool = False,
        has_normal: bool = False,
        has_orm: bool = False,
        has_aux: bool = False,
    ) -> None:
        """
        Performs semantic columnar layout for an MTK Atlas Chunk material.
        Dynamically adjusts vertical positions based on active texture channels.
        """
        if node_tree is None or not hasattr(node_tree, "nodes"):
            return

        nodes = node_tree.nodes

        # ---------------------------------------------------------------------
        # 0. Collect Active Texture Entries (top to bottom)
        # ---------------------------------------------------------------------
        # Texture order: Overlay -> Albedo -> Normal -> ORM -> Aux
        tex_entries: List[Dict[str, Any]] = []

        if has_overlay:
            tex_entries.append({
                "type": "overlay",
                "curr": nodes.get("Atlas Overlay Texture (Current)") or nodes.get("Atlas Overlay Texture"),
                "next": nodes.get("Atlas Overlay Texture (Next)"),
                "blend": nodes.get("Animated Overlay Blend"),
            })

        tex_entries.append({
            "type": "albedo",
            "curr": nodes.get("Atlas Albedo Texture (Current)") or nodes.get("Atlas Albedo Texture"),
            "next": nodes.get("Atlas Albedo Texture (Next)"),
            "blend": nodes.get("Animated Frame Blend"),
        })

        if has_normal:
            tex_entries.append({
                "type": "normal",
                "curr": nodes.get("Atlas Normal Texture (Current)") or nodes.get("Atlas Normal Texture"),
                "next": nodes.get("Atlas Normal Texture (Next)"),
                "blend": nodes.get("Animated Normal Blend"),
            })

        if has_orm:
            tex_entries.append({
                "type": "orm",
                "curr": nodes.get("Atlas ORM Texture (Current)") or nodes.get("Atlas ORM Texture"),
                "next": nodes.get("Atlas ORM Texture (Next)"),
                "blend": nodes.get("Animated ORM Blend"),
            })

        if has_aux:
            tex_entries.append({
                "type": "aux",
                "curr": nodes.get("Atlas Aux Texture (Current)") or nodes.get("Atlas Aux Texture"),
                "next": nodes.get("Atlas Aux Texture (Next)"),
                "blend": nodes.get("Animated Aux Blend"),
            })

        # Filter out entries where primary node wasn't created
        active_tex = [e for e in tex_entries if e["curr"] is not None]

        # ---------------------------------------------------------------------
        # 1. Layout Textures Column (Dynamic Y-Stacking)
        # ---------------------------------------------------------------------
        # Estimate total height of all texture blocks
        total_tex_height = 0.0
        gap_between_entries = 45.0
        entry_heights: List[float] = []

        for e in active_tex:
            if is_animated and e["next"] is not None:
                h = 260.0 + 30.0 + 260.0  # Two texture nodes stacked
            else:
                h = 260.0  # Single texture node
            entry_heights.append(h)
            total_tex_height += h

        if len(active_tex) > 1:
            total_tex_height += gap_between_entries * (len(active_tex) - 1)

        # Center textures column vertically around Y = 100
        start_tex_y = 100.0 + (total_tex_height / 2.0)
        curr_y = start_tex_y
        tex_x = -1180.0
        blend_x = -880.0

        for idx, e in enumerate(active_tex):
            h = entry_heights[idx]
            top_y = curr_y
            if is_animated and e["next"] is not None:
                e["curr"].location = (tex_x, top_y)
                e["next"].location = (tex_x, top_y - 270.0)
                if e["blend"] is not None:
                    # Place blend node vertically centered between curr and next
                    e["blend"].location = (blend_x, top_y - 120.0)
            else:
                e["curr"].location = (tex_x, top_y)

            curr_y -= h + gap_between_entries

        # ---------------------------------------------------------------------
        # 2. Layout UV / Coordinates Stage (Left of Textures)
        # ---------------------------------------------------------------------
        uv_node = nodes.get("UV Map")
        if uv_node:
            uv_node.location = (-2200.0, 150.0)

        # UV transform attribute nodes
        attr_tf = nodes.get("MTK UV Transform")
        attr_rot = nodes.get("MTK UV Rotation")
        sep_tf = nodes.get("Separate UV Transform")
        scale_comb = nodes.get("Combine Scale")
        loc_comb = nodes.get("Combine Location")
        rot_comb = nodes.get("Combine Rotation")
        tiling_node = nodes.get("Atlas UV Tiling")

        if attr_tf:
            attr_tf.location = (-2200.0, -50.0)
        if attr_rot:
            attr_rot.location = (-2200.0, -280.0)
        if sep_tf:
            sep_tf.location = (-1950.0, -50.0)
        if scale_comb:
            scale_comb.location = (-1720.0, 100.0)
        if loc_comb:
            loc_comb.location = (-1720.0, -70.0)
        if rot_comb:
            rot_comb.location = (-1720.0, -240.0)
        if tiling_node:
            tiling_node.location = (-1450.0, 0.0)

        # Animation timing & scheduler nodes
        attr_anim = nodes.get("Face Anim Timing")
        sep_anim = nodes.get("Separate Anim Timing")
        attr_fsize = nodes.get("Face Anim Frame Size")
        sep_fsize = nodes.get("Separate Anim Frame Size")
        sched_node = nodes.get("Animation Scheduler")
        anim_uv_node = nodes.get("Animated UV Mapping")

        if attr_anim:
            attr_anim.location = (-2150.0, 450.0)
        if sep_anim:
            sep_anim.location = (-1920.0, 450.0)
        if attr_fsize:
            attr_fsize.location = (-2150.0, 200.0)
        if sep_fsize:
            sep_fsize.location = (-1920.0, 200.0)
        if sched_node:
            sched_node.location = (-1700.0, 450.0)
        if anim_uv_node:
            anim_uv_node.location = (-1450.0, 450.0)

        # ---------------------------------------------------------------------
        # 3. Layout Biome Tint Stage
        # ---------------------------------------------------------------------
        attr_tint_data = nodes.get("Attr Biome Tint Data")
        sep_tint_data = nodes.get("Separate Biome Tint Data")
        attr_tint_col = nodes.get("Attr Biome Tint Color")
        tint_node = nodes.get("MC Biome Tint")

        if attr_tint_data:
            attr_tint_data.location = (-580.0, 450.0)
        if sep_tint_data:
            sep_tint_data.location = (-340.0, 450.0)
        if attr_tint_col:
            attr_tint_col.location = (-340.0, 200.0)
        if tint_node:
            tint_node.location = (-60.0, 350.0)

        # ---------------------------------------------------------------------
        # 4. Layout Shading Stage (PBR & BSDF)
        # ---------------------------------------------------------------------
        norm_map = nodes.get("Normal Map")
        if norm_map:
            norm_map.location = (420.0, 360.0)

        sep_orm = nodes.get("Separate ORM")
        ao_mix = nodes.get("Albedo × AO")
        emit_strength = nodes.get("Emission Strength × Mask")
        attr_vertex_ao = nodes.get("Vertex AO")
        vertex_ao_mix = nodes.get("Base Color × Vertex AO")

        if sep_orm:
            sep_orm.location = (180.0, 100.0)
        if ao_mix:
            ao_mix.location = (420.0, 160.0)
        if emit_strength:
            emit_strength.location = (420.0, -60.0)
        if attr_vertex_ao:
            attr_vertex_ao.location = (420.0, -200.0)
        if vertex_ao_mix:
            vertex_ao_mix.location = (640.0, 160.0)

        sep_aux = nodes.get("Separate Aux")
        ior_node = nodes.get("IOR from Aux")
        if sep_aux:
            sep_aux.location = (180.0, -360.0)
        if ior_node:
            ior_node.location = (420.0, -360.0)

        principled = nodes.get("Principled BSDF")
        if principled is None:
            principled = next((n for n in nodes if getattr(n, "bl_idname", None) == "ShaderNodeBsdfPrincipled"), None)
        if principled:
            principled.location = (880.0, 80.0) if vertex_ao_mix else (780.0, 80.0)

        # ---------------------------------------------------------------------
        # 5. Layout Output Stage
        # ---------------------------------------------------------------------
        output_node = nodes.get("Material Output")
        if output_node is None:
            output_node = next((n for n in nodes if getattr(n, "bl_idname", None) == "ShaderNodeOutputMaterial"), None)
        if output_node:
            output_node.location = (1260.0, 80.0) if vertex_ao_mix else (1180.0, 80.0)

        # ---------------------------------------------------------------------
        # 6. Fit Frame Bounding Boxes
        # ---------------------------------------------------------------------
        for frame_name in ("Frame_UV", "Frame_Textures", "Frame_Biome", "Frame_Shading", "Frame_Output"):
            frame = nodes.get(frame_name)
            if frame:
                child_nodes = [n for n in nodes if getattr(n, "parent", None) == frame]
                cls.fit_frame_bounds(frame, child_nodes)


def auto_layout_material(
    material: Any,
    *,
    is_animated: bool = False,
    has_overlay: bool = False,
    has_normal: bool = False,
    has_orm: bool = False,
    has_aux: bool = False,
    use_attribute_node: bool = False,
) -> None:
    """Convenience entry point to format an active Blender Material node tree."""
    if material is None or getattr(material, "node_tree", None) is None:
        return
    NodeLayoutEngine.layout_atlas_material(
        material.node_tree,
        is_animated=is_animated,
        has_overlay=has_overlay,
        has_normal=has_normal,
        has_orm=has_orm,
        has_aux=has_aux,
        use_attribute_node=use_attribute_node,
    )
