"""
Hierarchy, masking, and object relationship management for Voxel Point Clouds.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

try:
    from ...bridge.engine import get_libmtk
    from ...bridge.point_cloud.constants import MASK_MODIFIER_NAME, VOXEL_VERTEX_GROUP
except (ImportError, ValueError):
    from bridge.engine import get_libmtk
    from bridge.point_cloud.constants import MASK_MODIFIER_NAME, VOXEL_VERTEX_GROUP

logger = logging.getLogger("MoziToolKit.Utils.PointCloud.Hierarchy")


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
    if not HAS_BPY or obj is None or getattr(obj, "type", "") != "MESH":
        return None

    mesh = obj.data
    v_count = len(getattr(mesh, "vertices", []))
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
    # Ensure object itself is not hidden in viewport so the mask can be seen
    if hasattr(obj, "hide_set"):
        try:
            obj.hide_set(False)
        except Exception:
            pass
    if hasattr(obj, "hide_viewport"):
        obj.hide_viewport = False

    mod = obj.modifiers.get(modifier_name)
    if mod is None or mod.type != "MASK":
        return False
    mod.invert_vertex_group = not visible
    return True


def is_voxel_cloud_visible(
    obj: Any,
    modifier_name: str = MASK_MODIFIER_NAME,
) -> bool:
    """Checks whether the voxel cloud is currently visible in the viewport."""
    if not HAS_BPY or obj is None:
        return False
    if hasattr(obj, "hide_get"):
        try:
            if obj.hide_get():
                return False
        except Exception:
            pass
    if getattr(obj, "hide_viewport", False):
        return False

    mod = obj.modifiers.get(modifier_name)
    if mod is None or mod.type != "MASK":
        return True
    return not mod.invert_vertex_group


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
    for child in getattr(obj, "children", []):
        if child.get("mtk_is_voxel_cloud") or child.name.endswith("_VoxelCloud"):
            return child

    return None


def get_associated_parent_mesh(cloud_or_mesh: Any) -> Optional[Any]:
    """Resolves the parent world mesh object from an associated voxel point cloud."""
    if not HAS_BPY or cloud_or_mesh is None:
        return None

    obj = cloud_or_mesh if hasattr(cloud_or_mesh, "type") else None
    if obj is None:
        return None

    # If already parent mesh (not a voxel cloud itself)
    if not obj.get("mtk_is_voxel_cloud"):
        return obj

    # Query parent hierarchy
    if obj.parent and obj.parent.type == "MESH":
        return obj.parent
    if obj.parent and getattr(obj.parent, "type", "") == "EMPTY":
        for sibling in getattr(obj.parent, "children", []):
            if sibling != obj and getattr(sibling, "type", "") == "MESH" and not sibling.get("mtk_is_voxel_cloud"):
                return sibling

    # Fallback to custom property pointer
    world_name = obj.get("mtk_world_mesh")
    if world_name and world_name in bpy.data.objects:
        cand = bpy.data.objects[world_name]
        if cand and cand.type == "MESH":
            return cand

    return None


def ensure_voxel_child_cloud(
    parent_obj: Any,
    storage: Optional[Any] = None,
    cloud_data: Optional[Any] = None,
    origin_centered: bool = True,
    initial_hidden: bool = True,
    fast_mode: bool = True,
) -> Optional[Any]:
    """
    Ensures a persistent Voxel Point Cloud mesh object is built and synchronized
    directly under the given parent mesh object as a child.
    """
    if not HAS_BPY or parent_obj is None or getattr(parent_obj, "type", "") not in ("MESH", "EMPTY"):
        return None

    mtk = get_libmtk()
    if cloud_data is None:
        if storage is None or mtk is None or not hasattr(storage, "to_point_cloud"):
            return None
        cfg = (
            mtk.MesherConfig(
                z_up_coordinates=True,
                origin_centered=origin_centered,
            )
            if hasattr(mtk, "MesherConfig")
            else None
        )
        try:
            cloud_data = storage.to_point_cloud(cfg)
        except Exception as e:
            logger.warning("Failed extracting voxel point cloud from storage: %s", e)
            return None

    if cloud_data is None:
        return None

    # 1. Acquire target collection from parent parent_obj
    target_coll = (
        parent_obj.users_collection[0]
        if parent_obj.users_collection
        else (bpy.context.scene.collection if hasattr(bpy.context, "scene") else None)
    )

    # 2. Acquire or create child point cloud object in parent's collection
    cloud_name = f"{parent_obj.name}_VoxelCloud"
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

    # 3. Enforce strict hierarchy and 1:1 absolute local transform alignment
    if cloud_obj.parent != parent_obj:
        cloud_obj.parent = parent_obj
        if hasattr(cloud_obj, "matrix_parent_inverse"):
            cloud_obj.matrix_parent_inverse.identity()
    cloud_obj.location = (0.0, 0.0, 0.0)
    cloud_obj.rotation_euler = (0.0, 0.0, 0.0)
    cloud_obj.scale = (1.0, 1.0, 1.0)

    # 4. Bind bidirectional custom properties
    cloud_obj["mtk_is_voxel_cloud"] = True
    cloud_obj["mtk_world_mesh"] = parent_obj.name
    parent_obj["mtk_voxel_cloud"] = cloud_obj.name

    # Record bounds to lock origin alignment during future user carving & remeshing
    if hasattr(cloud_data, "bounds") and cloud_data.bounds is not None:
        cloud_obj["mtk_bounds"] = list(cloud_data.bounds)

    # 5. Inject points and configure Mask modifier via bridge
    try:
        from ...bridge.point_cloud import inject_voxel_point_cloud
    except (ImportError, ValueError):
        from bridge.point_cloud import inject_voxel_point_cloud

    inject_voxel_point_cloud(
        cloud_obj,
        cloud_data,
        update_mask=True,
        initial_hidden=initial_hidden,
        fast_mode=fast_mode,
    )

    return cloud_obj
