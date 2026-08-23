"""
Template Collection Updater for MoziToolKit and Yefira.
Bakes and updates meshes in 'MC_Block_Templates' directly from a resource pack or JAR
and attaches Geometry Nodes required attributes (CUBE_FACE_NORMAL, LOCAL_FACE_ID, LOCAL_UV).
"""

from __future__ import annotations
import bpy
import bmesh
from mathutils import Vector
from pathlib import Path
from typing import Optional, Union

from .state_baker import StateBaker
from .mesh_generator import build_blender_mesh_from_baked_model

TEMPLATE_COLLECTION_NAME = "MC_Block_Templates"

# Core template definitions: (Object Name, Canonical BlockState String, is_cross_plant)
DEFAULT_TEMPLATE_DEFINITIONS: list[tuple[str, str, bool]] = [
    ("stairs_straight", "minecraft:oak_stairs[facing=east,half=bottom,shape=straight]", False),
    ("stairs_inner", "minecraft:oak_stairs[facing=east,half=bottom,shape=inner_left]", False),
    ("stairs_outer", "minecraft:oak_stairs[facing=east,half=bottom,shape=outer_left]", False),
    ("slab_bottom", "minecraft:stone_slab[type=bottom]", False),
    ("slab_top", "minecraft:stone_slab[type=top]", False),
    ("fence", "minecraft:oak_fence[east=false,north=true,south=true,waterlogged=false,west=false]", False),
    ("fence_cross", "minecraft:oak_fence[east=true,north=true,south=true,waterlogged=false,west=true]", False),
    ("fence_gate", "minecraft:oak_fence_gate[facing=north,in_wall=false,open=false,powered=false]", False),
    ("door_lower", "minecraft:oak_door[facing=north,half=lower,hinge=left,open=false,powered=false]", False),
    ("door_upper", "minecraft:oak_door[facing=north,half=upper,hinge=left,open=false,powered=false]", False),
    ("trapdoor", "minecraft:oak_trapdoor[facing=north,half=bottom,open=false,powered=false,waterlogged=false]", False),
    ("lantern", "minecraft:lantern[hanging=false,waterlogged=false]", False),
    ("lantern_hanging", "minecraft:lantern[hanging=true,waterlogged=false]", False),
    ("chain", "minecraft:iron_chain[axis=y,waterlogged=false]", False),
    ("iron_bars", "minecraft:iron_bars[east=true,north=true,south=false,waterlogged=false,west=false]", False),
    ("glass_pane", "minecraft:glass_pane[east=true,north=true,south=false,waterlogged=false,west=false]", False),
    ("torch", "minecraft:torch", False),
    ("wall_torch", "minecraft:wall_torch[facing=north]", False),
    ("cross_plant", "minecraft:short_grass", True),
    ("flower", "minecraft:dandelion", True),
    ("carpet", "minecraft:white_carpet", False),
    ("bell", "minecraft:bell[attachment=floor,facing=north,powered=false]", False),
    ("anvil", "minecraft:anvil[facing=north]", False),
    ("grindstone", "minecraft:grindstone[face=floor,facing=north]", False),
    ("campfire", "minecraft:campfire[facing=north,lit=true,signal_fire=false,waterlogged=false]", False),
]


def attach_yefira_template_attributes(mesh: bpy.types.Mesh, is_cross_plant: bool = False) -> None:
    """
    Attach Yefira Geometry Nodes required attributes:
    - CUBE_FACE_NORMAL (FLOAT_VECTOR, FACE)
    - LOCAL_FACE_ID (INT, FACE)
    - LOCAL_UV (FLOAT_VECTOR, CORNER)
    """
    norm_attr = mesh.attributes.get("Cube_Face_Normal")
    if not norm_attr:
        norm_attr = mesh.attributes.new(name="Cube_Face_Normal", type="FLOAT_VECTOR", domain="FACE")

    fid_attr = mesh.attributes.get("Local_Face_ID")
    if not fid_attr:
        fid_attr = mesh.attributes.new(name="Local_Face_ID", type="INT", domain="FACE")

    luv_attr = mesh.attributes.get("Local_UV")
    if not luv_attr:
        luv_attr = mesh.attributes.new(name="Local_UV", type="FLOAT_VECTOR", domain="CORNER")

    uv_layer = mesh.uv_layers.active

    for poly in mesh.polygons:
        fn = poly.normal
        norm_attr.data[poly.index].vector = (0.0, 1.0, 0.0) if is_cross_plant else (fn.x, fn.y, fn.z)

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

        # Copy UV from UVMap into Local_UV attribute
        for loop_idx in poly.loop_indices:
            if uv_layer:
                uv = uv_layer.data[loop_idx].uv
                luv_attr.data[loop_idx].vector = (uv.x, uv.y, 0.0)
            else:
                vi = mesh.loops[loop_idx].vertex_index
                v_co = mesh.vertices[vi].co
                luv_attr.data[loop_idx].vector = (v_co.x + 0.5, v_co.z + 0.5, 0.0)

    mesh.update()


def update_mc_block_templates_from_pack(
    pack_path_or_baker: Union[str, Path, StateBaker],
    collection_name: str = TEMPLATE_COLLECTION_NAME,
    context: Optional[bpy.types.Context] = None
) -> int:
    """
    Bake and update all meshes in the specified template collection directly from resource pack / JAR.
    Returns the count of successfully updated template objects.
    """
    if isinstance(pack_path_or_baker, StateBaker):
        baker = pack_path_or_baker
    else:
        baker = StateBaker(jar_path=pack_path_or_baker)

    if collection_name in bpy.data.collections:
        col = bpy.data.collections[collection_name]
    else:
        col = bpy.data.collections.new(collection_name)
        ctx = context or bpy.context
        if ctx and hasattr(ctx, "scene") and ctx.scene:
            ctx.scene.collection.children.link(col)
        col.hide_render = True
        col.hide_viewport = True

    updated_count = 0

    for obj_name, state_str, is_cross in DEFAULT_TEMPLATE_DEFINITIONS:
        try:
            baked = baker.bake_block_state(state_str)
            mesh = build_blender_mesh_from_baked_model(
                baked_model=baked,
                mesh_name=f"Template_{obj_name}_Mesh",
                origin_centered=True
            )
            mesh.use_fake_user = True
            attach_yefira_template_attributes(mesh, is_cross_plant=is_cross)

            obj = bpy.data.objects.get(obj_name)
            if not obj:
                obj = bpy.data.objects.new(obj_name, mesh)
                obj.use_fake_user = True
                col.objects.link(obj)
            else:
                old_mesh = obj.data
                obj.data = mesh
                if old_mesh and old_mesh.users == 0:
                    bpy.data.meshes.remove(old_mesh)

            updated_count += 1
        except Exception as e:
            print(f"[MC_Block_Templates] Warning: Failed to bake template {obj_name} ({state_str}): {e}")

    return updated_count
