"""Small, name-based building blocks for Blender shader-node templates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re

import bpy


def ensure_group(name: str, version: int) -> bpy.types.NodeTree:
    """Return a versioned ShaderNodeTree, clearing only stale Mozi templates."""
    group = bpy.data.node_groups.get(name)
    if group is None:
        group = bpy.data.node_groups.new(name=name, type="ShaderNodeTree")
    elif group.get("mozi_template_version") != version or not group.get("mozi_template_complete"):
        group.nodes.clear()
        group.interface.clear()
    else:
        return group
    group["mozi_template_version"] = version
    group["mozi_template_complete"] = False
    return group


def finalize_group(group: bpy.types.NodeTree) -> bpy.types.NodeTree:
    """Mark a group reusable only after all nodes and links were created."""
    group["mozi_template_complete"] = True
    return group


def add_sockets(group: bpy.types.NodeTree, sockets: Iterable[tuple[str, str, str, object]]) -> None:
    """Add interface sockets from ``(name, direction, type, default)`` entries."""
    for name, direction, socket_type, default in sockets:
        socket = group.interface.new_socket(name=name, in_out=direction, socket_type=socket_type)
        if default is not None:
            socket.default_value = default


def node(
    nodes: bpy.types.Nodes,
    node_type: str,
    name: str,
    *,
    location: tuple[float, float] = (0, 0),
    label: str | None = None,
    properties: Mapping[str, object] | None = None,
    inputs: Mapping[str, object] | None = None,
    outputs: Mapping[str, object] | None = None,
) -> bpy.types.Node:
    """Create a node using stable property and socket names, never indices."""
    created = nodes.new(node_type)
    created.name = name
    created.label = label if label is not None else name
    created.location = location
    for attribute, value in (properties or {}).items():
        setattr(created, attribute, value)
    for socket_name, value in (inputs or {}).items():
        input_socket(created, socket_name).default_value = value
    for socket_name, value in (outputs or {}).items():
        created.outputs[socket_name].default_value = value
    return created


_SOCKET_SELECTOR = re.compile(r"^(.*)\[(\d+)\]$")


def input_socket(created: bpy.types.Node, selector: str) -> bpy.types.NodeSocket:
    """Resolve ``Name`` or ``Name[index]`` without relying on API indices.

    Blender gives several Math inputs the identical visible name ``Value``.
    ``Value[1]`` selects the second socket with that name, retaining a stable
    and readable graph specification across node types and Blender sessions.
    """
    match = _SOCKET_SELECTOR.fullmatch(selector)
    name, occurrence = (match.group(1), int(match.group(2))) if match else (selector, 0)
    matches = [socket for socket in created.inputs if socket.name == name]
    if occurrence >= len(matches):
        raise KeyError(f"{created.name!r} has no input socket {selector!r}")
    return matches[occurrence]


def link(
    links: bpy.types.NodeLinks,
    source: bpy.types.Node,
    source_socket: str,
    target: bpy.types.Node,
    target_socket: str,
) -> None:
    """Connect sockets by their semantic names."""
    links.new(source.outputs[source_socket], input_socket(target, target_socket))
