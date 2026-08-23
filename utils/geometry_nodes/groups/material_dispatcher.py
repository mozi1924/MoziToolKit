"""
Reusable Geometry Node Group: Multi-Chunk Material Dispatcher.
Decouples material data-block binding from the pure geometry pipeline.
Assigns chunk materials conditionally via native Set Material chains.
"""

from __future__ import annotations

from typing import Dict, Optional
import bpy
from ..core import ensure_gn_group, ensure_socket, finalize_group
from ...live_sync.constants import MTK_ATLAS_CHUNK_ID

GROUP_NAME_MATERIAL_DISPATCHER = "Yefira_Material_Dispatcher"
MATERIAL_DISPATCHER_VERSION = 1


def get_or_create_material_dispatcher_group(
    chunk_mats: Dict[int, bpy.types.Material],
) -> bpy.types.GeometryNodeTree:
    """
    Construct or update the independent Yefira_Material_Dispatcher node group.
    
    Inputs:
        - Geometry (NodeSocketGeometry)
    Outputs:
        - Geometry (NodeSocketGeometry)
        
    Chain Structure:
        Chunk 0 (Base): Unconditional Set Material across entire mesh.
        Chunk 1+ (Overrides): Set Material with Selection (mtk_atlas_chunk_id == cid).
    """
    sorted_chunk_ids = sorted(chunk_mats.keys()) if chunk_mats else [0]
    signature_key = ",".join(f"{cid}:{chunk_mats[cid].name if chunk_mats.get(cid) else 'None'}" for cid in sorted_chunk_ids)

    tree, needs_build = ensure_gn_group(GROUP_NAME_MATERIAL_DISPATCHER, MATERIAL_DISPATCHER_VERSION)
    
    if not needs_build and tree.get("mozi_dispatcher_signature") == signature_key:
        return tree

    tree.nodes.clear()
    ensure_socket(tree, "Geometry", "INPUT", "NodeSocketGeometry")
    ensure_socket(tree, "Geometry", "OUTPUT", "NodeSocketGeometry")

    nodes, links = tree.nodes, tree.links
    gin = nodes.new("NodeGroupInput")
    gin.location = (-300, 0)
    gout = nodes.new("NodeGroupOutput")

    last_geo = gin.outputs["Geometry"]
    x_pos = 0

    if not chunk_mats:
        gout.location = (200, 0)
        links.new(last_geo, gout.inputs["Geometry"])
        tree["mozi_dispatcher_signature"] = signature_key
        return finalize_group(tree)

    # Base chunk (0) sets default material across all faces
    if 0 in chunk_mats and chunk_mats[0]:
        set_mat0 = nodes.new("GeometryNodeSetMaterial")
        set_mat0.name = "Set Material (Chunk 0)"
        set_mat0.inputs["Material"].default_value = chunk_mats[0]
        set_mat0.location = (x_pos, 0)
        links.new(last_geo, set_mat0.inputs["Geometry"])
        last_geo = set_mat0.outputs["Geometry"]
        x_pos += 200

    # Overrides for specialized chunks (Chunk 1, Chunk 2, ...)
    other_chunk_ids = [cid for cid in sorted_chunk_ids if cid > 0 and chunk_mats.get(cid)]
    if other_chunk_ids:
        read_chunk_id = nodes.new("GeometryNodeInputNamedAttribute")
        read_chunk_id.data_type = "INT"
        read_chunk_id.inputs["Name"].default_value = MTK_ATLAS_CHUNK_ID
        read_chunk_id.location = (0, -220)

        for cid in other_chunk_ids:
            mat_obj = chunk_mats[cid]
            if not mat_obj:
                continue

            cmp_chunk = nodes.new("FunctionNodeCompare")
            cmp_chunk.data_type = "INT"
            cmp_chunk.operation = "EQUAL"
            cmp_chunk.inputs["B"].default_value = cid
            cmp_chunk.location = (x_pos, -220)
            links.new(read_chunk_id.outputs["Attribute"], cmp_chunk.inputs["A"])

            set_mat = nodes.new("GeometryNodeSetMaterial")
            set_mat.name = f"Set Material (Chunk {cid})"
            set_mat.inputs["Material"].default_value = mat_obj
            set_mat.location = (x_pos, 0)
            links.new(last_geo, set_mat.inputs["Geometry"])
            links.new(cmp_chunk.outputs["Result"], set_mat.inputs["Selection"])

            last_geo = set_mat.outputs["Geometry"]
            x_pos += 200

    gout.location = (x_pos + 100, 0)
    links.new(last_geo, gout.inputs["Geometry"])

    tree["mozi_dispatcher_signature"] = signature_key
    tree["mozi_role"] = "material_dispatcher"
    return finalize_group(tree)
