"""
Template Asset Collection Manager for Minecraft Props and Non-Cube Models.
Manages the 'MC_Block_Templates' collection in Blender used by Geometry Nodes.
Generates procedural non-cube models and entity blocks with fake-user persistence.
"""

from __future__ import annotations

import hashlib
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
EXTRACTED_TEMPLATE_MESH_VERSION = 2


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


def ensure_baked_block_template(
    collection: bpy.types.Collection,
    block_state: str,
    baked_model,
) -> Optional[bpy.types.Object]:
    """Return a persistent Geometry Nodes template for an extracted block model.

    A blockstate includes its variant and multipart choices, so two states of the
    same block can legitimately require different geometry.  The digest keeps
    the Blender object name short, valid and stable while the full state is
    retained as a custom property for inspection.

    ``baked_model`` is deliberately duck-typed here to avoid making the live
    sync package depend on the baker at import time.
    """
    if not baked_model or not getattr(baked_model, "elements", None):
        return None

    digest = hashlib.sha1(block_state.encode("utf-8")).hexdigest()[:16]
    signature_source = f"v{EXTRACTED_TEMPLATE_MESH_VERSION}:{baked_model.elements!r}"
    model_signature = hashlib.sha1(signature_source.encode("utf-8")).hexdigest()
    name = f"mc_model_{digest}"
    obj = bpy.data.objects.get(name)
    if obj is None or obj.get("yefira:model_signature") != model_signature:
        # Import lazily: template_catalog is also loaded in light-weight paths
        # where the model baker has no configured resource source.
        from ..mc_baker.mesh_generator import build_blender_mesh_from_baked_model

        mesh = build_blender_mesh_from_baked_model(
            baked_model,
            mesh_name=f"{name}_mesh",
            origin_centered=True,
        )
        attach_yefira_template_attributes(mesh)
        if obj is None:
            obj = bpy.data.objects.new(name, mesh)
            obj.use_fake_user = True
        else:
            old_mesh = obj.data
            obj.data = mesh
            if old_mesh and old_mesh.users == 0:
                bpy.data.meshes.remove(old_mesh)
        obj["yefira:block_state"] = block_state
        obj["yefira:model_source"] = "minecraft_json"
        obj["yefira:model_signature"] = model_signature

    if obj.name not in collection.objects:
        collection.objects.link(obj)
    return obj


class TemplateCatalog:
    """Catalog of MC_Block_Templates collection indices with fallback resolution."""

    def __init__(self, context: Optional[bpy.types.Context] = None) -> None:
        self._context = context
        self._cached_names: Optional[tuple[str, ...]] = None
        self._cached_map: Dict[str, int] = {}

    def get_index_map(self) -> Dict[str, int]:
        col = get_or_create_template_collection(self._context or bpy.context)
        names = tuple(obj.name for obj in col.objects)
        if self._cached_names != names:
            self._cached_names = names
            self._cached_map = get_template_index_map(col)
        return self._cached_map

    def get_index(self, template_name: str) -> int:
        idx_map = self.get_index_map()
        return idx_map.get(template_name, idx_map.get(template_name.lower(), 0))


template_catalog = TemplateCatalog()


def attach_yefira_template_attributes(mesh: bpy.types.Mesh, is_cross_plant: bool = False) -> None:
    """
    Attach Yefira Geometry Nodes required template attributes:
    - CUBE_FACE_NORMAL (FLOAT_VECTOR, FACE)
    - LOCAL_FACE_ID (INT, FACE)
    - LOCAL_UV (FLOAT_VECTOR, CORNER)
    Cleans up any legacy template attributes if present.
    """
    for legacy_name in LEGACY_TEMPLATE_ATTRIBUTE_NAMES:
        attr = mesh.attributes.get(legacy_name)
        if attr is not None:
            mesh.attributes.remove(attr)

    norm_attr = mesh.attributes.get(CUBE_FACE_NORMAL)
    if not norm_attr or norm_attr.data_type != 'FLOAT_VECTOR' or norm_attr.domain != 'FACE' or len(norm_attr.data) != len(mesh.polygons):
        if norm_attr:
            mesh.attributes.remove(norm_attr)
        norm_attr = mesh.attributes.new(name=CUBE_FACE_NORMAL, type="FLOAT_VECTOR", domain="FACE")

    fid_attr = mesh.attributes.get(LOCAL_FACE_ID)
    if not fid_attr or fid_attr.data_type != 'INT' or fid_attr.domain != 'FACE' or len(fid_attr.data) != len(mesh.polygons):
        if fid_attr:
            mesh.attributes.remove(fid_attr)
        fid_attr = mesh.attributes.new(name=LOCAL_FACE_ID, type="INT", domain="FACE")

    luv_attr = mesh.attributes.get(LOCAL_UV)
    if not luv_attr or luv_attr.data_type != 'FLOAT_VECTOR' or luv_attr.domain != 'CORNER' or len(luv_attr.data) != len(mesh.loops):
        if luv_attr:
            mesh.attributes.remove(luv_attr)
        luv_attr = mesh.attributes.new(name=LOCAL_UV, type="FLOAT_VECTOR", domain="CORNER")

    mesh.update()

    uv_layer = mesh.uv_layers.active

    for poly in mesh.polygons:
        fn = poly.normal
        norm_vec = (0.0, 1.0, 0.0) if is_cross_plant else (fn.x, fn.y, fn.z)
        norm_attr.data[poly.index].vector = norm_vec

        # Map normal to 0..5 face ID
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
            if uv_layer and not is_cross_plant:
                uv = uv_layer.data[loop_idx].uv
                luv_vec = (uv.x, uv.y, 0.0)
            else:
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
                    u, v = 1.0 - (v_co.x + 0.5), v_co.z + 0.5
                elif fid == 5:  # West
                    u, v = v_co.y + 0.5, v_co.z + 0.5
                else:
                    u, v = 0.5, 0.5
                luv_vec = (max(0.0, min(1.0, u)), max(0.0, min(1.0, v)), 0.0)
            luv_attr.data[loop_idx].vector = luv_vec

    mesh.update()

_attach_template_attributes = attach_yefira_template_attributes


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
    BOX_FACES = [
        (0, 3, 2, 1),  # Bottom (-Z)
        (4, 5, 6, 7),  # Top (+Z)
        (0, 1, 5, 4),  # South (-Y)
        (1, 2, 6, 5),  # East (+X)
        (2, 3, 7, 6),  # North (+Y)
        (3, 0, 4, 7),  # West (-X)
    ]
    mesh.from_pydata(verts, [], BOX_FACES)
    _attach_template_attributes(mesh)
    return mesh


def _create_torch_mesh(name: str) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(name)
    w, h = 0.0625, 0.625
    verts = [
        (-w, -w, -0.5), (w, -w, -0.5), (w, w, -0.5), (-w, w, -0.5),
        (-w, -w, -0.5 + h), (w, -w, -0.5 + h), (w, w, -0.5 + h), (-w, w, -0.5 + h),
    ]
    BOX_FACES = [
        (0, 3, 2, 1),  # Bottom (-Z)
        (4, 5, 6, 7),  # Top (+Z)
        (0, 1, 5, 4),  # South (-Y)
        (1, 2, 6, 5),  # East (+X)
        (2, 3, 7, 6),  # North (+Y)
        (3, 0, 4, 7),  # West (-X)
    ]
    mesh.from_pydata(verts, [], BOX_FACES)
    _attach_template_attributes(mesh)
    return mesh


def _create_lantern_mesh(name: str) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(name)
    w = 0.2
    verts = [
        (-w, -w, -0.5), (w, -w, -0.5), (w, w, -0.5), (-w, w, -0.5),
        (-w, -w, 0.0), (w, -w, 0.0), (w, w, 0.0), (-w, w, 0.0),
    ]
    BOX_FACES = [
        (0, 3, 2, 1),  # Bottom (-Z)
        (4, 5, 6, 7),  # Top (+Z)
        (0, 1, 5, 4),  # South (-Y)
        (1, 2, 6, 5),  # East (+X)
        (2, 3, 7, 6),  # North (+Y)
        (3, 0, 4, 7),  # West (-X)
    ]
    mesh.from_pydata(verts, [], BOX_FACES)
    _attach_template_attributes(mesh)
    return mesh


def _create_fence_mesh(name: str) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(name)
    w = 0.125
    verts = [
        (-w, -w, -0.5), (w, -w, -0.5), (w, w, -0.5), (-w, w, -0.5),
        (-w, -w, 0.5), (w, -w, 0.5), (w, w, 0.5), (-w, w, 0.5),
    ]
    BOX_FACES = [
        (0, 3, 2, 1),  # Bottom (-Z)
        (4, 5, 6, 7),  # Top (+Z)
        (0, 1, 5, 4),  # South (-Y)
        (1, 2, 6, 5),  # East (+X)
        (2, 3, 7, 6),  # North (+Y)
        (3, 0, 4, 7),  # West (-X)
    ]
    mesh.from_pydata(verts, [], BOX_FACES)
    _attach_template_attributes(mesh)
    return mesh


def _create_carpet_mesh(name: str) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(name)
    verts = [
        (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
        (-0.5, -0.5, -0.4375), (0.5, -0.5, -0.4375), (0.5, 0.5, -0.4375), (-0.5, 0.5, -0.4375),
    ]
    BOX_FACES = [
        (0, 3, 2, 1),  # Bottom (-Z)
        (4, 5, 6, 7),  # Top (+Z)
        (0, 1, 5, 4),  # South (-Y)
        (1, 2, 6, 5),  # East (+X)
        (2, 3, 7, 6),  # North (+Y)
        (3, 0, 4, 7),  # West (-X)
    ]
    mesh.from_pydata(verts, [], BOX_FACES)
    _attach_template_attributes(mesh)
    return mesh
