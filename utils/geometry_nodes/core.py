"""Core utilities and lifecycle helpers for Geometry Nodes node trees in MoziToolKit."""

from __future__ import annotations

from typing import Any, Optional, Tuple
import bpy


def ensure_socket(
    tree: bpy.types.NodeTree,
    name: str,
    in_out: str,
    socket_type: str,
    default_value: Any = None,
    min_value: Optional[float | int] = None,
    max_value: Optional[float | int] = None,
) -> bpy.types.NodeSocket:
    """Create or retrieve an interface socket on a node tree (Blender 4.0+ compliant)."""
    for item in tree.interface.items_tree:
        if item.item_type == "SOCKET" and item.name == name and item.in_out == in_out:
            if default_value is not None and hasattr(item, "default_value"):
                try:
                    item.default_value = default_value
                except Exception:
                    pass
            if min_value is not None and hasattr(item, "min_value"):
                item.min_value = min_value
            if max_value is not None and hasattr(item, "max_value"):
                item.max_value = max_value
            return item

    socket = tree.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)
    if default_value is not None and hasattr(socket, "default_value"):
        try:
            socket.default_value = default_value
        except Exception:
            pass
    if min_value is not None and hasattr(socket, "min_value"):
        socket.min_value = min_value
    if max_value is not None and hasattr(socket, "max_value"):
        socket.max_value = max_value
    return socket


def ensure_gn_group(
    name: str,
    version: int,
) -> Tuple[bpy.types.GeometryNodeTree, bool]:
    """
    Get or allocate a versioned GeometryNodeTree datablock.
    Returns (tree, needs_build). If needs_build is False, the group is already complete and up-to-date.
    """
    tree = bpy.data.node_groups.get(name)
    if tree and tree.get("mozi_group_version") == version and tree.get("mozi_built"):
        return tree, False

    if not tree:
        tree = bpy.data.node_groups.new(name=name, type="GeometryNodeTree")
    else:
        tree.nodes.clear()
        tree.interface.clear()

    tree["mozi_group_version"] = version
    tree["mozi_built"] = False
    return tree, True


def finalize_group(tree: bpy.types.NodeTree) -> bpy.types.NodeTree:
    """Mark a node group as fully built and ready for caching/reuse."""
    tree["mozi_built"] = True
    return tree


def prune_unlinked_nodes(tree: bpy.types.GeometryNodeTree) -> None:
    """
    Remove construction leftovers that do not contribute to group output.
    Walks upstream from Group Output nodes to preserve necessary field and geometry dependencies.
    """
    required = {node for node in tree.nodes if node.bl_idname == "NodeGroupOutput"}
    stack = list(required)
    while stack:
        node = stack.pop()
        for input_socket in node.inputs:
            for node_link in input_socket.links:
                if node_link.from_node not in required:
                    required.add(node_link.from_node)
                    stack.append(node_link.from_node)
    for node in list(tree.nodes):
        if node not in required:
            tree.nodes.remove(node)
