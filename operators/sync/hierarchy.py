"""
Hierarchical management for the Single Unified World Mesh in Blender.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple
import bpy

try:
    from ...bridge.mesh import inject_mesh_data
    from ...bridge.assets import get_cache_dir
    from ...utils.materials.builder.atlas_builder import build_atlas_chunk_material
except (ImportError, ValueError):
    from bridge.mesh import inject_mesh_data
    from bridge.assets import get_cache_dir
    try:
        from utils.materials.builder.atlas_builder import build_atlas_chunk_material
    except (ImportError, ValueError):
        build_atlas_chunk_material = None

logger = logging.getLogger("MoziToolKit.Sync.Hierarchy")

DEFAULT_WORLD_OBJECT_NAME = "Yefira_World"


def is_yefira_world_object(obj: Optional[bpy.types.Object]) -> bool:
    """Checks if an object is tagged as the Yefira Live Sync world container."""
    if not obj:
        return False
    return bool(obj.get("mtk:is_yefira_world")) or obj.name == DEFAULT_WORLD_OBJECT_NAME


def ensure_world_materials(world_obj: bpy.types.Object, prefs=None) -> None:
    """
    Ensures that the unified world mesh has materials assigned.
    If precompiled Atlas cache exists, builds and assigns the Atlas Chunk materials.
    Otherwise, creates a clean default material showing vertex colors and lighting.
    """
    if not world_obj or world_obj.type != "MESH":
        return

    mesh = world_obj.data
    cache_dir = get_cache_dir(prefs)
    atlas_dir = cache_dir / "atlas"
    atlas_mapping_path = atlas_dir / "atlas_mapping.json"

    # 1. If Atlas is precompiled, bind Atlas chunk materials
    if atlas_mapping_path.exists() and build_atlas_chunk_material is not None:
        try:
            import json
            atlas_data = json.loads(atlas_mapping_path.read_text(encoding="utf-8"))
            chunk_meta_list = atlas_data.get("chunks", [])

            colormaps_dir = cache_dir / "colormaps"
            colormaps = {}
            if colormaps_dir.exists():
                for cm in ("grass", "foliage", "dry_foliage"):
                    p = colormaps_dir / f"{cm}.png"
                    if p.exists():
                        colormaps[cm] = p

            manifest_path = cache_dir / "cache_manifest.json"
            manifest_fp = None
            if manifest_path.exists():
                try:
                    manifest_fp = json.loads(manifest_path.read_text(encoding="utf-8")).get("fingerprint")
                except Exception:
                    pass

            for idx, cm in enumerate(chunk_meta_list):
                chunk_id = cm.get("chunk_id", idx)
                cat = cm.get("category", "blocks")
                c_idx = cm.get("category_chunk_index", chunk_id + 1)
                is_anim = cm.get("is_animated", False)
                stem = f"{cat}_anim_chunk_{c_idx:03}" if is_anim else f"{cat}_chunk_{c_idx:03}"

                albedo_file = atlas_dir / f"{stem}.png"
                normal_file = atlas_dir / f"{stem}_n.png" if cm.get("has_normal") else None
                specular_file = atlas_dir / f"{stem}_s.png" if cm.get("has_specular") else None
                overlay_file = atlas_dir / f"{stem}_overlay.png" if cm.get("has_overlay") else None
                chunk_width = float(cm.get("width", 4096))
                chunk_height = float(cm.get("height", 4096))

                mat = build_atlas_chunk_material(
                    chunk_id=chunk_id,
                    albedo_path=albedo_file,
                    normal_path=normal_file,
                    specular_path=specular_file,
                    overlay_path=overlay_file,
                    colormaps=colormaps,
                    category=cat,
                    category_chunk_index=c_idx,
                    is_animated=is_anim,
                    stack_fingerprint=manifest_fp,
                    atlas_width=chunk_width,
                    atlas_height=chunk_height,
                    tile_width=16.0,
                    tile_height=16.0,
                )

                if chunk_id < len(mesh.materials):
                    if mesh.materials[chunk_id] != mat:
                        mesh.materials[chunk_id] = mat
                else:
                    while len(mesh.materials) < chunk_id:
                        mesh.materials.append(None)
                    mesh.materials.append(mat)

            if len(mesh.materials) > 0:
                return
        except Exception as e:
            logger.warning(f"Failed to bind precompiled Atlas materials: {e}")

    # 2. Fallback: Default shaded material with vertex colors / AO
    default_mat_name = "MTK:LiveSync:Default"
    mat = bpy.data.materials.get(default_mat_name)
    if mat is None:
        mat = bpy.data.materials.new(name=default_mat_name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        nodes.clear()
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (200, 0)
        output = nodes.new("ShaderNodeOutputMaterial")
        output.location = (500, 0)
        mat.node_tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

        # Hook vertex color attribute for AO
        attr_node = nodes.new("ShaderNodeAttribute")
        attr_node.location = (-150, 0)
        attr_node.attribute_name = "color"
        mat.node_tree.links.new(attr_node.outputs["Color"], bsdf.inputs["Base Color"])

    if len(mesh.materials) == 0:
        mesh.materials.append(mat)
    elif mesh.materials[0] is None:
        mesh.materials[0] = mat


def get_or_create_world_mesh_object(
    context: Optional[bpy.types.Context] = None,
    target_name: str = DEFAULT_WORLD_OBJECT_NAME,
) -> bpy.types.Object:
    """
    Acquires or creates the single unified mesh object representing the synchronized world.
    """
    ctx = context or getattr(bpy, "context", None)

    # 1. Check active object if it is a valid Yefira world mesh
    active = getattr(ctx, "active_object", None) if ctx else None
    if active and is_yefira_world_object(active) and active.type == "MESH":
        return active

    # 2. Check by exact name
    if target_name in bpy.data.objects:
        obj = bpy.data.objects[target_name]
        if obj.type == "MESH":
            obj["mtk:is_yefira_world"] = True
            return obj

    # 3. Check any existing object tagged with mtk:is_yefira_world
    for obj in bpy.data.objects:
        if is_yefira_world_object(obj) and obj.type == "MESH":
            return obj

    # 4. Create new unified mesh object
    mesh = bpy.data.meshes.new(target_name)
    world_obj = bpy.data.objects.new(target_name, mesh)
    world_obj["mtk:is_yefira_world"] = True
    world_obj.location = (0.0, 0.0, 0.0)

    # Link to active collection
    col = getattr(ctx, "collection", None) if ctx else None
    if col is None and hasattr(bpy.context, "scene") and hasattr(bpy.context.scene, "collection"):
        col = bpy.context.scene.collection
    if col:
        col.objects.link(world_obj)

    logger.info(f"Created single unified world mesh object: {world_obj.name}")
    return world_obj


def update_world_mesh(world_obj: bpy.types.Object, mesh_data: Any) -> Tuple[int, int]:
    """
    Injects processed geometry buffer into the single world mesh object using high-throughput
    zero-copy bridge methods.
    Returns (vertex_count, face_count).
    """
    if not world_obj or world_obj.type != "MESH":
        return 0, 0

    mesh = world_obj.data
    inject_mesh_data(
        mesh_data,
        mesh,
        update_topology=True,
        update_normals=True,
    )

    ensure_world_materials(world_obj)

    v_count = len(mesh.vertices)
    f_count = len(mesh.polygons)
    return v_count, f_count
