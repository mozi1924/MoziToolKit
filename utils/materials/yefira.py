"""
Yefira Procedural Point-Cloud Material and Geometry Nodes Integration Module.

Provides object detection, attribute mapping, atlas slot configuration,
and Geometry Nodes notification for Yefira-based procedural Minecraft worlds.
"""

from __future__ import annotations

import sys
from typing import Iterable, Optional
import bpy

from .constants import (
    ATTR_UV_ROTATION,
    ATTR_UV_TILING_TRANSFORM,
)


def is_yefira_object(obj: Optional[bpy.types.Object]) -> bool:
    """Identify whether a Blender object is a Yefira procedural point-cloud world.

    An object is recognized as Yefira if:
    1. It is a MESH object named 'Yefira_World', or
    2. It has a Geometry Nodes modifier named 'Yefira_WorldModifier', or
    3. Its mesh data contains a point-domain 'block_state' or 'mc_pos' attribute.

    Polygonal meshes or other procedural objects lacking these markers remain
    standard MoziToolKit mesh objects.
    """
    if not obj or getattr(obj, "type", None) != 'MESH' or not getattr(obj, "data", None):
        return False
    if obj.name == "Yefira_World":
        return True
    if hasattr(obj, "modifiers") and any(
        mod.type == 'NODES' and (mod.name == 'Yefira_WorldModifier' or "yefira" in mod.name.lower())
        for mod in obj.modifiers
    ):
        return True
    mesh = obj.data
    if hasattr(mesh, "attributes"):
        state_attr = mesh.attributes.get("block_state")
        if state_attr and state_attr.domain == 'POINT':
            return True
        if "mc_pos" in mesh.attributes:
            return True
    return False


def has_yefira_objects(objects: Iterable[Optional[bpy.types.Object]]) -> bool:
    """Return True if any object in the given collection is a Yefira world."""
    return any(is_yefira_object(obj) for obj in objects if obj)


def write_yefira_point_atlas_attributes(mesh: bpy.types.Mesh, mapping: dict) -> None:
    """Fill Yefira's 6-direction face atlas attributes directly from Mozi's mapping.

    Writes the following POINT domain attributes:
    - ``mtk_material_id`` (INT)
    - ``mtk_tile_{face}`` (FLOAT_VECTOR for east, west, top, bottom, south, north)
    - ``mtk_chunk_{face}`` (INT)
    - ``mtk_texture_{face}`` (INT)
    - ``mtk_tint_data_{face}`` (FLOAT_COLOR: base_weight, overlay_weight, tint_weight, is_hardcoded)
    """
    state_attr = mesh.attributes.get("block_state")
    if not state_attr or state_attr.domain != 'POINT':
        return

    by_name = {
        str(entry.get("name", "")).removeprefix("minecraft:").removeprefix("block/"): entry
        for entry in mapping.get("materials", [])
        if entry.get("name")
    }
    texture_locations = mapping.get("textures", {})

    def texture_location(block_name: str) -> dict:
        """Find a flat texture entry when a block model has no face table."""
        for key in (block_name, f"minecraft:{block_name}", f"minecraft:block/{block_name}"):
            location = texture_locations.get(key)
            if isinstance(location, dict):
                return location
        return {}

    def texture_only_faces(block_name: str) -> dict:
        """Derive standard cube faces from a texture-only atlas mapping.

        SPBR maps usually retain individual textures but not Minecraft model
        JSON. Normal meshes still work because their source polygons carry
        the exact texture key; Yefira has only a logical block state, so make
        that bridge here. A differentiated model face table remains the
        authoritative source whenever present.
        """
        base = texture_location(block_name)
        side = texture_location(f"{block_name}_side") or base
        top = texture_location(f"{block_name}_top") or texture_location(f"{block_name}_end") or side
        bottom = texture_location(f"{block_name}_bottom") or texture_location(f"{block_name}_end") or top
        if block_name == "grass_block":
            bottom = texture_location("dirt") or bottom
        named_variants = any(
            texture_location(f"{block_name}{suffix}")
            for suffix in ("_side", "_top", "_bottom", "_end")
        )
        if not named_variants or not side or not top or not bottom:
            return {}
        return {"+X": side, "-X": side, "+Y": top, "-Y": bottom, "+Z": side, "-Z": side}

    def mapping_names(state: str) -> tuple[str, ...]:
        """Resolve stateful generated models before generic texture fallback."""
        block_name, _, raw_props = state.partition("[")
        block_name = block_name.removeprefix("minecraft:").removeprefix("block/")
        names = []
        if block_name.endswith("_door"):
            props = {
                key.strip(): value.strip().rstrip("]")
                for pair in raw_props.rstrip("]").split(",") if "=" in pair
                for key, value in [pair.split("=", 1)]
            }
            names.append(f"{block_name}_{'top' if props.get('half') == 'upper' else 'bottom'}")
        names.append(block_name)
        return tuple(names)

    face_specs = (
        ("east", "+X"), ("west", "-X"), ("top", "+Y"),
        ("bottom", "-Y"), ("south", "+Z"), ("north", "-Z"),
    )
    values = {name: {"tile": [], "chunk": [], "texture": [], "tint_data": [], "is_opaque": []} for name, _ in face_specs}
    material_ids = []
    is_opaque_list = []

    for item in state_attr.data:
        state = item.value.decode("utf-8", errors="replace") if isinstance(item.value, bytes) else str(item.value)
        names = mapping_names(state)
        entry = next((by_name[name] for name in names if name in by_name), None)
        material_ids.append(int(entry.get("material_id", 0)) if entry else 0)
        faces = entry.get("faces", {}) if entry else {}
        fallback_location = next((texture_location(name) for name in names if texture_location(name)), {})
        primary_name = names[0]
        explicit_locations = [faces.get(mapping_face) for _, mapping_face in face_specs]
        has_differentiated_faces = len({loc.get("texture_key") for loc in explicit_locations if isinstance(loc, dict)}) > 1
        derived_faces = texture_only_faces(primary_name) if not has_differentiated_faces else {}

        # Determine block-level opacity
        block_opaque = 1
        if entry is not None and "is_opaque" in entry:
            block_opaque = 1 if entry.get("is_opaque", True) else 0
        elif fallback_location:
            block_opaque = 1 if fallback_location.get("is_opaque", True) else 0
        is_opaque_list.append(block_opaque)

        for attr_face, mapping_face in face_specs:
            location = derived_faces.get(mapping_face) or faces.get(mapping_face) or fallback_location
            values[attr_face]["tile"].append((
                float(location.get("tile_column", 0)),
                float(location.get("tile_row", 0)), 0.0,
            ))
            values[attr_face]["chunk"].append(int(location.get("chunk_id", 0)))
            values[attr_face]["texture"].append(int(location.get("texture_id", 0)))
            values[attr_face]["tint_data"].append((
                float(location.get("default_base_tint_weight", 0.0)),
                float(location.get("default_overlay_tint_weight", 0.0)),
                float(location.get("default_tint_weight", 0.0)),
                1.0 if location.get("is_hardcoded", False) else 0.0,
            ))
            values[attr_face]["is_opaque"].append(1 if location.get("is_opaque", True) else 0)

    def point_attr(name: str, data_type: str):
        attr = mesh.attributes.get(name)
        if attr and (attr.domain != 'POINT' or attr.data_type != data_type or len(attr.data) != len(state_attr.data)):
            mesh.attributes.remove(attr)
            attr = None
        return attr or mesh.attributes.new(name=name, type=data_type, domain='POINT')

    point_attr("mtk_material_id", 'INT').data.foreach_set('value', material_ids)
    point_attr("mtk_is_opaque", 'INT').data.foreach_set('value', is_opaque_list)
    point_attr("is_opaque", 'INT').data.foreach_set('value', is_opaque_list)
    for face, _ in face_specs:
        tile_attr = point_attr(f"mtk_tile_{face}", 'FLOAT_VECTOR')
        tile_attr.data.foreach_set('vector', [component for tile in values[face]["tile"] for component in tile])
        point_attr(f"mtk_chunk_{face}", 'INT').data.foreach_set('value', values[face]["chunk"])
        point_attr(f"mtk_texture_{face}", 'INT').data.foreach_set('value', values[face]["texture"])
        point_attr(f"mtk_is_opaque_{face}", 'INT').data.foreach_set('value', values[face]["is_opaque"])
        tint_attr = point_attr(f"mtk_tint_data_{face}", 'FLOAT_COLOR')
        tint_attr.data.foreach_set('color', [component for value in values[face]["tint_data"] for component in value])


def setup_yefira_point_cloud_attributes(
    mesh: bpy.types.Mesh,
    mapping_data: dict,
    primary_mat: Optional[bpy.types.Material] = None,
    chunk_0: Optional[dict] = None,
) -> None:
    """Initialize tiling, rotation, atlas dimensions, and 6-direction attributes on a point-cloud mesh."""
    if len(mesh.vertices) == 0:
        return

    num_verts = len(mesh.vertices)

    # 1. Ensure ATTR_UV_TILING_TRANSFORM exists
    tiling_attr = mesh.attributes.get(ATTR_UV_TILING_TRANSFORM)
    if not tiling_attr or tiling_attr.data_type != 'FLOAT_COLOR' or tiling_attr.domain != 'POINT' or len(tiling_attr.data) != num_verts:
        if tiling_attr:
            mesh.attributes.remove(tiling_attr)
        tiling_attr = mesh.attributes.new(name=ATTR_UV_TILING_TRANSFORM, type='FLOAT_COLOR', domain='POINT')
    flat_colors = [c for _ in range(num_verts) for c in (1.0, 1.0, 0.0, 0.0)]
    tiling_attr.data.foreach_set('color', flat_colors)

    # 2. Ensure ATTR_UV_ROTATION exists
    rot_attr = mesh.attributes.get(ATTR_UV_ROTATION)
    if not rot_attr or rot_attr.data_type != 'FLOAT' or rot_attr.domain != 'POINT' or len(rot_attr.data) != num_verts:
        if rot_attr:
            mesh.attributes.remove(rot_attr)
        rot_attr = mesh.attributes.new(name=ATTR_UV_ROTATION, type='FLOAT', domain='POINT')
    rot_attr.data.foreach_set('value', [0.0] * num_verts)

    # 3. Write atlas metadata attributes to point domain
    chunk_0 = chunk_0 or {}
    mat_props = primary_mat or {}
    atlas_metadata = {
        "mtk_atlas_width": float(chunk_0.get("width", mat_props.get("mtk_atlas_width", 1024.0))),
        "mtk_atlas_height": float(chunk_0.get("height", mat_props.get("mtk_atlas_height", 1024.0))),
        "mtk_tile_size": float(chunk_0.get("tile_size", mat_props.get("mtk_tile_size", 16.0))),
        "mtk_tiles_per_row": float(chunk_0.get("tiles_per_row", mat_props.get("mtk_tiles_per_row", 64))),
    }
    for attr_name, attr_value in atlas_metadata.items():
        attr = mesh.attributes.get(attr_name)
        if not attr or attr.data_type != 'FLOAT' or attr.domain != 'POINT' or len(attr.data) != num_verts:
            if attr:
                mesh.attributes.remove(attr)
            attr = mesh.attributes.new(name=attr_name, type='FLOAT', domain='POINT')
        attr.data.foreach_set('value', [attr_value] * num_verts)

    # 4. Fill 6-direction face attributes
    write_yefira_point_atlas_attributes(mesh, mapping_data)


def notify_yefira_update(obj: Optional[bpy.types.Object] = None) -> None:
    """Notify the Yefira addon to refresh point cloud attributes and rebuild geometry nodes."""
    try:
        if hasattr(bpy.ops, "yefira") and hasattr(bpy.ops.yefira, "rebuild_world"):
            bpy.ops.yefira.rebuild_world()
            return
    except Exception:
        pass

    try:
        if "yefira_blender.operators.main_operators" in sys.modules:
            from yefira_blender.operators.main_operators import trigger_point_cloud_update
            trigger_point_cloud_update(bpy.context)
        elif "yefira_blender.nodes.world_tree" in sys.modules and obj:
            from yefira_blender.nodes.world_tree import setup_world_geometry_nodes
            setup_world_geometry_nodes(obj)
    except Exception:
        pass


def apply_yefira_atlas_materials(
    obj: bpy.types.Object,
    yefira_atlas_materials: dict[int, bpy.types.Material],
    mapping_data: dict,
    chunks_by_id: Optional[dict[int, dict]] = None,
) -> bool:
    """Apply Atlas materials and point cloud attributes to a Yefira procedural world object.

    Configures dense material slot indices (0..max_chunk_id), enables fake user,
    populates all directional and dimension point attributes, and signals Yefira
    to rebuild its Geometry Nodes setup.
    """
    if not yefira_atlas_materials:
        return False

    primary_mat = yefira_atlas_materials.get(0) or next(iter(yefira_atlas_materials.values()), None)
    if not primary_mat:
        return False

    # Chunk IDs are the Geometry Nodes material indices. Give the point-cloud
    # a dense, deterministic slot table matching chunk IDs 0..max_chunk_id.
    obj.data.materials.clear()
    max_chunk_id = max(yefira_atlas_materials.keys())
    for chunk_id in range(max_chunk_id + 1):
        chunk_material = yefira_atlas_materials.get(chunk_id)
        if chunk_material is None:
            raise RuntimeError(f"Atlas mapping is missing material chunk {chunk_id}")
        chunk_material.use_fake_user = True
        obj.data.materials.append(chunk_material)

    # Update modifier Set Material node if standard GeometryNodeSetMaterial is present
    for mod in obj.modifiers:
        if mod.type == 'NODES' and mod.node_group:
            for n in mod.node_group.nodes:
                if n.type == 'SET_MATERIAL' and "Material" in n.inputs:
                    n.inputs["Material"].default_value = primary_mat

    # Signal Yefira addon operators / nodes setup
    notify_yefira_update(obj)

    # Configure mesh point-cloud attributes
    chunk_0 = (chunks_by_id or {}).get(0, {})
    setup_yefira_point_cloud_attributes(
        mesh=obj.data,
        mapping_data=mapping_data,
        primary_mat=primary_mat,
        chunk_0=chunk_0,
    )

    return True
