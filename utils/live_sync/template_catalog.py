"""
Template Asset Collection Manager for Minecraft Props and Non-Cube Models.
Manages the 'MC_Block_Templates' collection in Blender used by Geometry Nodes.
Generates procedural non-cube models and entity blocks with fake-user persistence.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional
import bpy

from .constants import (
    CUBE_FACE_NORMAL,
    LEGACY_TEMPLATE_ATTRIBUTE_NAMES,
    LOCAL_FACE_ID,
    LOCAL_UV,
)

logger = logging.getLogger("MoziToolKit.LiveSync")

TEMPLATE_COLLECTION_NAME = "MC_Block_Templates"


def get_or_create_template_collection(context: Optional[bpy.types.Context] = None) -> bpy.types.Collection:
    """Find or create the 'MC_Block_Templates' collection in the active scene."""
    if context is None:
        context = bpy.context

    if TEMPLATE_COLLECTION_NAME in bpy.data.collections:
        col = bpy.data.collections[TEMPLATE_COLLECTION_NAME]
    else:
        col = bpy.data.collections.new(TEMPLATE_COLLECTION_NAME)
        if hasattr(context, "scene") and context.scene and context.scene.collection:
            context.scene.collection.children.link(col)
        col.hide_render = True
        col.hide_viewport = True

    _populate_default_templates(col)
    return col


def get_template_index_map(col: bpy.types.Collection) -> Dict[str, int]:
    """
    Return mapping of template object name -> integer index in collection.
    Geometry Nodes 'Collection Info' with 'Pick Instance' uses 0-based indexing matching col.objects.
    """
    mapping: Dict[str, int] = {}
    obj_names = [obj.name for obj in col.objects]

    for idx, obj in enumerate(col.objects):
        mapping[obj.name] = idx
        mapping[obj.name.lower()] = idx

    def register_alias(alias_key: str, target_name: str):
        if target_name in mapping:
            target_idx = mapping[target_name]
            mapping[alias_key] = target_idx
            mapping[alias_key.lower()] = target_idx

    for obj_name in obj_names:
        low = obj_name.lower()
        if "stairs" in low:
            register_alias("stairs", obj_name)
            register_alias("stairs_straight", obj_name)
        elif "slab" in low:
            register_alias("slab", obj_name)
            register_alias("slab_bottom", obj_name)
        elif "bed_head" in low:
            register_alias("bed_head", obj_name)
        elif "bed_foot" in low:
            register_alias("bed_foot", obj_name)
        elif "door_lower" in low or "door_bottom" in low:
            register_alias("door_lower", obj_name)
            register_alias("door_bottom", obj_name)
        elif "door_upper" in low or "door_top" in low:
            register_alias("door_upper", obj_name)
            register_alias("door_top", obj_name)
        elif "chest" in low:
            register_alias("chest", obj_name)
        elif "plant" in low or "cross" in low:
            register_alias("cross_plant", obj_name)
            register_alias("flower", obj_name)
        elif "torch" in low:
            register_alias("torch", obj_name)
        elif "trapdoor" in low:
            register_alias("trapdoor", obj_name)
        elif "carpet" in low:
            register_alias("carpet", obj_name)
        elif "fence" in low:
            register_alias("fence", obj_name)
        elif "wall" in low:
            register_alias("wall", obj_name)
        elif "lantern" in low:
            register_alias("lantern", obj_name)

    return mapping


class TemplateCatalog:
    """Catalog of MC_Block_Templates collection indices with fallback resolution."""

    def __init__(self, context: Optional[bpy.types.Context] = None) -> None:
        self._context = context

    def get_index_map(self) -> Dict[str, int]:
        col = get_or_create_template_collection(self._context or bpy.context)
        return get_template_index_map(col)

    def get_index(self, template_name: str) -> int:
        idx_map = self.get_index_map()
        return idx_map.get(template_name, idx_map.get(template_name.lower(), 0))


template_catalog = TemplateCatalog()


def _attach_template_attributes(mesh: bpy.types.Mesh, is_cross_plant: bool = False) -> None:
    """Attach face-normal, ID and UV fields to a template mesh."""
    for name in LEGACY_TEMPLATE_ATTRIBUTE_NAMES:
        attr = mesh.attributes.get(name)
        if attr is not None:
            mesh.attributes.remove(attr)

    norm_attr = mesh.attributes.get(CUBE_FACE_NORMAL)
    if not norm_attr:
        norm_attr = mesh.attributes.new(name=CUBE_FACE_NORMAL, type="FLOAT_VECTOR", domain="FACE")

    fid_attr = mesh.attributes.get(LOCAL_FACE_ID)
    if not fid_attr:
        fid_attr = mesh.attributes.new(name=LOCAL_FACE_ID, type="INT", domain="FACE")

    luv_attr = mesh.attributes.get(LOCAL_UV)
    if not luv_attr:
        luv_attr = mesh.attributes.new(name=LOCAL_UV, type="FLOAT_VECTOR", domain="CORNER")

    mesh.update()

    for poly in mesh.polygons:
        fn = poly.normal
        norm_attr.data[poly.index].vector = (0.0, 1.0, 0.0) if is_cross_plant else (fn.x, fn.y, fn.z)
        if is_cross_plant:
            fid = 2  # North
        elif fn.z > 0.5:
            fid = 0  # Top (+Z)
        elif fn.z < -0.5:
            fid = 1  # Bottom (-Z)
        elif fn.y > 0.5:
            fid = 2  # North (+Y)
        elif fn.y < -0.5:
            fid = 3  # South (-Y)
        elif fn.x > 0.5:
            fid = 4  # East (+X)
        elif fn.x < -0.5:
            fid = 5  # West (-X)
        else:
            fid = 3
        fid_attr.data[poly.index].value = fid

        for loop_idx in poly.loop_indices:
            vi = mesh.loops[loop_idx].vertex_index
            v_co = mesh.vertices[vi].co

            if fid == 0:  # Top
                u, v = v_co.x + 0.5, v_co.y + 0.5
            elif fid == 1:  # Bottom
                u, v = v_co.x + 0.5, 1.0 - (v_co.y + 0.5)
            elif fid == 2:  # North
                u, v = 1.0 - (v_co.x + 0.5), v_co.z + 0.5
            elif fid == 3:  # South
                u, v = v_co.x + 0.5, v_co.z + 0.5
            elif fid == 4:  # East
                u, v = 1.0 - (v_co.y + 0.5), v_co.z + 0.5
            elif fid == 5:  # West
                u, v = v_co.y + 0.5, v_co.z + 0.5
            else:
                u, v = 0.5, 0.5

            luv_attr.data[loop_idx].vector = (max(0.0, min(1.0, u)), max(0.0, min(1.0, v)), 0.0)


def _populate_default_templates(col: bpy.types.Collection) -> None:
    """Create basic default procedural template models if they do not yet exist."""
    templates = [
        ("cross_plant", _create_cross_plant_mesh),
        ("stairs_straight", _create_stairs_mesh),
        ("slab_bottom", _create_slab_mesh),
        ("torch", _create_torch_mesh),
        ("lantern", _create_lantern_mesh),
        ("fence", _create_fence_mesh),
        ("carpet", _create_carpet_mesh),
    ]

    for name, creator_fn in templates:
        if name not in col.objects:
            obj = bpy.data.objects.get(name)
            if not obj:
                mesh = creator_fn(name)
                obj = bpy.data.objects.new(name, mesh)
                obj.use_fake_user = True
            if obj.name not in col.objects:
                col.objects.link(obj)


def _create_cross_plant_mesh(name: str) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(name)
    verts = [
        (-0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (0.5, 0.5, 0.5), (-0.5, -0.5, 0.5),
        (-0.5, 0.5, -0.5), (0.5, -0.5, -0.5), (0.5, -0.5, 0.5), (-0.5, 0.5, 0.5),
    ]
    faces = [(0, 1, 2, 3), (4, 5, 6, 7)]
    mesh.from_pydata(verts, [], faces)
    _attach_template_attributes(mesh, is_cross_plant=True)
    return mesh


def _create_stairs_mesh(name: str) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(name)
    verts = [
        (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
        (-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.0, 0.0), (-0.5, 0.0, 0.0),
        (-0.5, 0.0, 0.5), (0.5, 0.0, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
    ]
    faces = [
        (0, 1, 5, 4), (4, 5, 6, 7), (7, 6, 9, 8), (8, 9, 10, 11),
        (11, 10, 2, 3), (0, 4, 7, 8, 11, 3), (1, 2, 10, 9, 6, 5), (0, 3, 2, 1)
    ]
    mesh.from_pydata(verts, [], faces)
    _attach_template_attributes(mesh)
    return mesh


def _create_slab_mesh(name: str) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(name)
    verts = [
        (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
        (-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0),
    ]
    faces = [
        (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
        (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0),
    ]
    mesh.from_pydata(verts, [], faces)
    _attach_template_attributes(mesh)
    return mesh


def _create_torch_mesh(name: str) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(name)
    w, h = 0.0625, 0.625
    verts = [
        (-w, -w, -0.5), (w, -w, -0.5), (w, w, -0.5), (-w, w, -0.5),
        (-w, -w, -0.5 + h), (w, -w, -0.5 + h), (w, w, -0.5 + h), (-w, w, -0.5 + h),
    ]
    faces = [
        (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
        (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0),
    ]
    mesh.from_pydata(verts, [], faces)
    _attach_template_attributes(mesh)
    return mesh


def _create_lantern_mesh(name: str) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(name)
    w = 0.2
    verts = [
        (-w, -w, -0.5), (w, -w, -0.5), (w, w, -0.5), (-w, w, -0.5),
        (-w, -w, 0.0), (w, -w, 0.0), (w, w, 0.0), (-w, w, 0.0),
    ]
    faces = [
        (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
        (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0),
    ]
    mesh.from_pydata(verts, [], faces)
    _attach_template_attributes(mesh)
    return mesh


def _create_fence_mesh(name: str) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(name)
    w = 0.125
    verts = [
        (-w, -w, -0.5), (w, -w, -0.5), (w, w, -0.5), (-w, w, -0.5),
        (-w, -w, 0.5), (w, -w, 0.5), (w, w, 0.5), (-w, w, 0.5),
    ]
    faces = [
        (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
        (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0),
    ]
    mesh.from_pydata(verts, [], faces)
    _attach_template_attributes(mesh)
    return mesh


def _create_carpet_mesh(name: str) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(name)
    verts = [
        (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
        (-0.5, -0.5, -0.4375), (0.5, -0.5, -0.4375), (0.5, 0.5, -0.4375), (-0.5, 0.5, -0.4375),
    ]
    faces = [
        (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
        (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0),
    ]
    mesh.from_pydata(verts, [], faces)
    _attach_template_attributes(mesh)
    return mesh
