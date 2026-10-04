"""
MoziToolKit Voxel Point Cloud Bridge Module.

Manages lossless persistent 3D voxel point clouds, bidirectional conversion
with Rust libmtk_py.VoxelPointCloud, native Mask Modifier hiding/showing
with configurable weight thresholds, and user-driven voxel carving/remeshing.
"""

from __future__ import annotations

import array
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("MoziToolKit.Bridge.PointCloud")

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from .engine import get_libmtk, has_libmtk, require_libmtk

MASK_MODIFIER_NAME = "MTK_Voxel_Mask"
VOXEL_VERTEX_GROUP = "MTK_Voxel_Storage"
ATTR_BLOCK_X = "mtk_block_x"
ATTR_BLOCK_Y = "mtk_block_y"
ATTR_BLOCK_Z = "mtk_block_z"
ATTR_BLOCK_STATE = "mtk_block_state"
ATTR_BIOME = "mtk_biome"
ATTR_LIGHT = "mtk_light"


def setup_voxel_mask_modifier(
    obj: Any,
    group_name: str = VOXEL_VERTEX_GROUP,
    modifier_name: str = MASK_MODIFIER_NAME,
    initial_hidden: bool = True,
    threshold: float = 0.5,
) -> Optional[Any]:
    """
    Sets up Blender's native Mask Modifier ('MASK') on a mesh object to control
    voxel point cloud visibility via vertex group weights and threshold.
    """
    if not HAS_BPY or obj is None or obj.type != "MESH":
        return None

    mesh = obj.data
    v_count = len(mesh.vertices)
    if v_count == 0:
        return None

    # 1. Acquire or create dedicated vertex group
    vg = obj.vertex_groups.get(group_name)
    if vg is None:
        vg = obj.vertex_groups.new(name=group_name)

    # 2. Assign weight 1.0 to all points in point cloud
    vg.add(list(range(v_count)), 1.0, "REPLACE")

    # 3. Acquire or create Mask Modifier
    mod = obj.modifiers.get(modifier_name)
    if mod is None:
        mod = obj.modifiers.new(name=modifier_name, type="MASK")

    mod.vertex_group = group_name
    mod.invert_vertex_group = True if initial_hidden else False
    mod.threshold = threshold
    mod.show_viewport = True
    mod.show_render = False

    return mod


def set_voxel_mask_threshold(
    obj: Any,
    threshold: float,
    invert: Optional[bool] = None,
    modifier_name: str = MASK_MODIFIER_NAME,
) -> bool:
    """Sets the threshold (0.0 to 1.0) and optional invert state of the Mask modifier."""
    if not HAS_BPY or obj is None:
        return False
    mod = obj.modifiers.get(modifier_name)
    if mod is None or mod.type != "MASK":
        return False
    mod.threshold = max(0.0, min(1.0, float(threshold)))
    if invert is not None:
        mod.invert_vertex_group = bool(invert)
    return True


def set_voxel_cloud_visibility(
    obj: Any,
    visible: bool,
    modifier_name: str = MASK_MODIFIER_NAME,
) -> bool:
    """
    Toggles visibility of the voxel point cloud.
    When hidden (visible=False), the Mask modifier inverts the 1.0 vertex group, hiding all points.
    When shown (visible=True), points are not masked and are fully visible for user editing.
    """
    if not HAS_BPY or obj is None:
        return False
    mod = obj.modifiers.get(modifier_name)
    if mod is None or mod.type != "MASK":
        return False
    # If visible, do not invert (or disable modifier viewport effect)
    mod.invert_vertex_group = not visible
    return True


def is_voxel_cloud_visible(
    obj: Any,
    modifier_name: str = MASK_MODIFIER_NAME,
) -> bool:
    """Checks whether the voxel cloud is currently visible in the viewport."""
    if not HAS_BPY or obj is None:
        return False
    mod = obj.modifiers.get(modifier_name)
    if mod is None or mod.type != "MASK":
        return True
    return not mod.invert_vertex_group


def inject_voxel_point_cloud(
    cloud_obj_or_mesh: Any,
    cloud_data: Any,
    update_mask: bool = True,
    initial_hidden: bool = True,
) -> bool:
    """
    Injects a Rust VoxelPointCloud into a Blender Mesh as a pure point cloud
    with native attributes (mtk_block_x/y/z, mtk_block_state, mtk_biome, mtk_light)
    and configures the Mask modifier.
    """
    if not HAS_BPY:
        return False

    if hasattr(cloud_obj_or_mesh, "data") and cloud_obj_or_mesh.type == "MESH":
        obj = cloud_obj_or_mesh
        mesh = cloud_obj_or_mesh.data
    else:
        obj = None
        mesh = cloud_obj_or_mesh

    pt_count = len(cloud_data) if hasattr(cloud_data, "__len__") else cloud_data.len()
    if pt_count == 0:
        mesh.clear_geometry()
        return True

    # 1. Clear old topology and allocate points
    mesh.clear_geometry()
    mesh.vertices.add(pt_count)

    # 2. Inject 3D positions via zero-copy MemoryView
    pos_injected = False
    if hasattr(cloud_data, "positions_memoryview"):
        try:
            pos_mv = cloud_data.positions_memoryview()
            if hasattr(pos_mv, "cast") and pos_mv.format == "B":
                pos_mv = pos_mv.cast("f")
            mesh.vertices.foreach_set("co", pos_mv)
            pos_injected = True
        except Exception as e:
            logger.debug("Fast positions memoryview injection failed: %s", e)

    if not pos_injected:
        if hasattr(cloud_data, "positions"):
            mesh.vertices.foreach_set("co", cloud_data.positions)

    # 3. Helper to create or acquire attribute
    def _ensure_attr(name: str, attr_type: str, domain: str = "POINT") -> Optional[Any]:
        if not hasattr(mesh, "attributes"):
            return None
        attr = mesh.attributes.get(name)
        if attr is not None and (attr.data_type != attr_type or attr.domain != domain):
            mesh.attributes.remove(attr)
            attr = None
        if attr is None:
            try:
                attr = mesh.attributes.new(name=name, type=attr_type, domain=domain)
            except Exception as e:
                logger.warning("Failed creating attribute %s: %s", name, e)
                return None
        return attr

    # 4. Inject block integer coordinates: block_x, block_y, block_z
    for name, mv_fn, fallback_attr in [
        (ATTR_BLOCK_X, "block_x_memoryview", "block_x"),
        (ATTR_BLOCK_Y, "block_y_memoryview", "block_y"),
        (ATTR_BLOCK_Z, "block_z_memoryview", "block_z"),
    ]:
        attr = _ensure_attr(name, "INT", "POINT")
        if attr is not None:
            injected = False
            if hasattr(cloud_data, mv_fn):
                try:
                    mv = getattr(cloud_data, mv_fn)()
                    if hasattr(mv, "cast") and mv.format == "B":
                        mv = mv.cast("i")
                    attr.data.foreach_set("value", mv)
                    injected = True
                except Exception as e:
                    logger.debug("Fast int memoryview failed for %s: %s", name, e)
            if not injected and hasattr(cloud_data, fallback_attr):
                vals = getattr(cloud_data, fallback_attr)
                arr = array.array("i", vals)
                attr.data.foreach_set("value", arr)

    # 5. Inject String attributes: block_state, biome
    states = cloud_data.get_block_states() if hasattr(cloud_data, "get_block_states") else getattr(cloud_data, "block_states", [])
    attr_state = _ensure_attr(ATTR_BLOCK_STATE, "STRING", "POINT")
    if attr_state is not None and len(states) == pt_count:
        for i, st in enumerate(states):
            b_val = st.encode("utf-8") if isinstance(st, str) else bytes(st)
            try:
                attr_state.data[i].value = b_val
            except Exception:
                try:
                    attr_state.data[i].value = st
                except Exception:
                    pass

    biomes = cloud_data.get_biomes() if hasattr(cloud_data, "get_biomes") else getattr(cloud_data, "biomes", [])
    attr_biome = _ensure_attr(ATTR_BIOME, "STRING", "POINT")
    if attr_biome is not None and len(biomes) == pt_count:
        for i, bm in enumerate(biomes):
            b_val = bm.encode("utf-8") if isinstance(bm, str) else bytes(bm)
            try:
                attr_biome.data[i].value = b_val
            except Exception:
                try:
                    attr_biome.data[i].value = bm
                except Exception:
                    pass

    # 6. Configure Mask Modifier
    if update_mask and obj is not None:
        setup_voxel_mask_modifier(obj, initial_hidden=initial_hidden)

    mesh.update()
    return True


def extract_voxel_point_cloud(cloud_obj_or_mesh: Any) -> Optional[Any]:
    """
    Extracts a live Rust VoxelPointCloud from a Blender Point Mesh.
    Captures user modifications (deleted vertices, carved cavities) with zero overhead.
    """
    if not HAS_BPY:
        return None

    mtk = require_libmtk("extract_voxel_point_cloud")

    if hasattr(cloud_obj_or_mesh, "data") and getattr(cloud_obj_or_mesh, "type", "") == "MESH":
        obj = cloud_obj_or_mesh
        mesh = cloud_obj_or_mesh.data
    else:
        obj = None
        mesh = cloud_obj_or_mesh

    v_count = len(mesh.vertices)
    if v_count == 0:
        return mtk.VoxelPointCloud.new() if hasattr(mtk, "VoxelPointCloud") else None

    # Check required attributes
    if not hasattr(mesh, "attributes"):
        return None

    attr_x = mesh.attributes.get(ATTR_BLOCK_X)
    attr_y = mesh.attributes.get(ATTR_BLOCK_Y)
    attr_z = mesh.attributes.get(ATTR_BLOCK_Z)
    attr_state = mesh.attributes.get(ATTR_BLOCK_STATE)

    if not (attr_x and attr_y and attr_z and attr_state):
        logger.warning("Mesh lacks required voxel point cloud attributes (%s, %s, %s, %s)",
                       ATTR_BLOCK_X, ATTR_BLOCK_Y, ATTR_BLOCK_Z, ATTR_BLOCK_STATE)
        return None

    # Extract 3D positions
    pos_arr = array.array("f", [0.0] * (v_count * 3))
    mesh.vertices.foreach_get("co", pos_arr)

    # Extract integer block coordinates
    bx_arr = array.array("i", [0] * v_count)
    by_arr = array.array("i", [0] * v_count)
    bz_arr = array.array("i", [0] * v_count)
    attr_x.data.foreach_get("value", bx_arr)
    attr_y.data.foreach_get("value", by_arr)
    attr_z.data.foreach_get("value", bz_arr)

    # Extract string block states
    block_states: List[str] = []
    for elem in attr_state.data:
        val = elem.value
        if isinstance(val, (bytes, bytearray)):
            block_states.append(val.decode("utf-8", errors="replace"))
        else:
            block_states.append(str(val))

    # Extract biomes if available
    attr_biome = mesh.attributes.get(ATTR_BIOME)
    biomes: Optional[List[str]] = None
    if attr_biome and len(attr_biome.data) == v_count:
        b_list: List[str] = []
        for elem in attr_biome.data:
            val = elem.value
            if isinstance(val, (bytes, bytearray)):
                b_list.append(val.decode("utf-8", errors="replace"))
            else:
                b_list.append(str(val))
        biomes = b_list

    # Extract bounds if stored on object
    bounds = None
    if obj is not None and "mtk_bounds" in obj:
        try:
            raw_b = obj["mtk_bounds"]
            if len(raw_b) == 6:
                bounds = [int(x) for x in raw_b]
        except Exception:
            pass

    return mtk.VoxelPointCloud.from_arrays(
        list(pos_arr),
        list(bx_arr),
        list(by_arr),
        list(bz_arr),
        block_states,
        biomes,
        None,
        bounds,
    )


def get_associated_voxel_cloud(mesh_or_obj: Any) -> Optional[Any]:
    """Resolves the associated Voxel Point Cloud object from a world mesh object or vice versa."""
    if not HAS_BPY or mesh_or_obj is None:
        return None

    obj = mesh_or_obj if hasattr(mesh_or_obj, "type") else None
    if obj is None:
        return None

    # If obj is already a voxel cloud
    if obj.get("mtk_is_voxel_cloud"):
        return obj

    # Query from object custom property pointer
    cloud_name = obj.get("mtk_voxel_cloud")
    if cloud_name and cloud_name in bpy.data.objects:
        cand = bpy.data.objects[cloud_name]
        if cand and cand.type == "MESH":
            return cand

    # Query by convention: f"{obj.name}_VoxelCloud"
    conv_name = f"{obj.name}_VoxelCloud"
    if conv_name in bpy.data.objects:
        cand = bpy.data.objects[conv_name]
        if cand and cand.type == "MESH":
            return cand

    # Query children
    for child in obj.children:
        if child.get("mtk_is_voxel_cloud") or child.name.endswith("_VoxelCloud"):
            return child

    return None


def sync_voxel_point_cloud_for_world(
    world_obj: Any,
    storage: Optional[Any] = None,
    cloud_data: Optional[Any] = None,
    origin_centered: bool = True,
    initial_hidden: bool = True,
) -> Optional[Any]:
    """Synchronizes or creates a companion Voxel Point Cloud object for a given world mesh.

    The point cloud is parented directly to `world_obj` with (0,0,0) local transform
    and placed in the exact same collection as `world_obj` (no separate collection),
    allowing 1:1 spatial alignment between world mesh blocks and voxel points.
    Accepts either an unmeshed `storage` (from which cloud points are extracted) or
    a pre-extracted `cloud_data` (VoxelPointCloud).
    """
    if not HAS_BPY or world_obj is None or getattr(world_obj, "type", "") != "MESH":
        return None

    mtk = get_libmtk()
    if cloud_data is None:
        if storage is None or mtk is None or not hasattr(storage, "to_point_cloud"):
            return None
        cfg = mtk.MesherConfig(
            z_up_coordinates=True,
            origin_centered=origin_centered,
        ) if hasattr(mtk, "MesherConfig") else None
        try:
            cloud_data = storage.to_point_cloud(cfg)
        except Exception as e:
            logger.warning("Failed extracting voxel point cloud from storage: %s", e)
            return None

    if cloud_data is None:
        return None

    # 2. Acquire target collection from parent world_obj
    target_coll = world_obj.users_collection[0] if world_obj.users_collection else (
        bpy.context.scene.collection if hasattr(bpy.context, "scene") else None
    )

    # 3. Acquire or create companion point cloud object in parent's collection
    cloud_name = f"{world_obj.name}_VoxelCloud"
    cloud_obj = bpy.data.objects.get(cloud_name)
    if cloud_obj is None or cloud_obj.type != "MESH":
        cloud_mesh = bpy.data.meshes.new(cloud_name)
        cloud_obj = bpy.data.objects.new(cloud_name, cloud_mesh)
        if target_coll is not None:
            target_coll.objects.link(cloud_obj)
        elif hasattr(bpy.context.scene, "collection"):
            bpy.context.scene.collection.objects.link(cloud_obj)
    else:
        # Ensure it is linked to target_coll
        if target_coll is not None and cloud_obj.name not in target_coll.objects:
            target_coll.objects.link(cloud_obj)

    # Clean up legacy separate collection if present and empty
    legacy_coll = bpy.data.collections.get("MTK_Voxel_Storage")
    if legacy_coll is not None:
        try:
            for o in list(legacy_coll.objects):
                legacy_coll.objects.unlink(o)
            bpy.data.collections.remove(legacy_coll)
        except Exception:
            pass

    # 4. Set hierarchy and 1:1 absolute transform alignment
    if cloud_obj.parent != world_obj:
        cloud_obj.parent = world_obj
        if hasattr(cloud_obj, "matrix_parent_inverse"):
            cloud_obj.matrix_parent_inverse.identity()
    cloud_obj.location = (0.0, 0.0, 0.0)
    cloud_obj.rotation_euler = (0.0, 0.0, 0.0)
    cloud_obj.scale = (1.0, 1.0, 1.0)

    cloud_obj["mtk_is_voxel_cloud"] = True
    cloud_obj["mtk_world_mesh"] = world_obj.name
    world_obj["mtk_voxel_cloud"] = cloud_obj.name

    # Record bounds to lock origin alignment during future user carving & remeshing
    if hasattr(cloud_data, "bounds") and cloud_data.bounds is not None:
        cloud_obj["mtk_bounds"] = list(cloud_data.bounds)

    # 5. Inject points and configure Mask modifier
    inject_voxel_point_cloud(cloud_obj, cloud_data, update_mask=True, initial_hidden=initial_hidden)

    return cloud_obj
