"""
Operators for Voxel Point Cloud Management, Mask Modifier Visibility,
and User-Driven Carving / Remeshing.
"""

from __future__ import annotations

import logging
import bpy
from bpy.props import BoolProperty, FloatProperty

logger = logging.getLogger("MoziToolKit.Operators.VoxelCloud")

try:
    from ..bridge.point_cloud import (
        extract_voxel_point_cloud,
        get_associated_voxel_cloud,
        inject_voxel_point_cloud,
        is_voxel_cloud_visible,
        set_voxel_cloud_visibility,
        set_voxel_mask_threshold,
    )
    from ..bridge.world import (
        ensure_world_materials,
        get_world_pipeline_assets,
        mesh_voxel_storage,
    )
    from ..bridge.mesh import inject_mesh_data
    from ..utils.system import get_prefs, register_menu_item
except (ImportError, ValueError):
    from bridge.point_cloud import (
        extract_voxel_point_cloud,
        get_associated_voxel_cloud,
        inject_voxel_point_cloud,
        is_voxel_cloud_visible,
        set_voxel_cloud_visibility,
        set_voxel_mask_threshold,
    )
    from bridge.world import (
        ensure_world_materials,
        get_world_pipeline_assets,
        mesh_voxel_storage,
    )
    from bridge.mesh import inject_mesh_data
    from utils.system import get_prefs, register_menu_item


def _resolve_world_and_cloud_objects(context) -> tuple[Optional[bpy.types.Object], Optional[bpy.types.Object]]:
    """Resolves (world_mesh_obj, voxel_cloud_obj) from current context selection."""
    active = context.active_object
    if active is None or active.type != "MESH":
        return None, None

    if active.get("mtk_is_voxel_cloud"):
        cloud_obj = active
        world_name = active.get("mtk_world_mesh") or active.parent.name if active.parent else None
        world_obj = bpy.data.objects.get(world_name) if world_name else None
        return world_obj, cloud_obj

    cloud_obj = get_associated_voxel_cloud(active)
    return active, cloud_obj


@register_menu_item(views=["object", "mesh"], label="Toggle Voxel Point Cloud Visibility")
class MOZI_OT_toggle_voxel_cloud(bpy.types.Operator):
    """Toggle visibility of the associated voxel storage point cloud using the Mask modifier."""

    bl_idname = "mozi.toggle_voxel_cloud"
    bl_label = "Toggle Voxel Cloud Visibility"
    bl_options = {"REGISTER", "UNDO"}

    enter_edit_mode: BoolProperty(
        name="Enter Edit Mode",
        description="Automatically switch to Edit Mode on the voxel cloud to select and delete blocks",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        world_obj, cloud_obj = _resolve_world_and_cloud_objects(context)
        return cloud_obj is not None

    def execute(self, context):
        world_obj, cloud_obj = _resolve_world_and_cloud_objects(context)
        if cloud_obj is None:
            self.report({"WARNING"}, "No associated Voxel Point Cloud found for active object.")
            return {"CANCELLED"}

        currently_visible = is_voxel_cloud_visible(cloud_obj)
        new_state = not currently_visible

        set_voxel_cloud_visibility(cloud_obj, new_state)

        if new_state:
            # Shown: optionally select and enter Edit Mode for carving
            if self.enter_edit_mode:
                context.view_layer.objects.active = cloud_obj
                cloud_obj.select_set(True)
                if world_obj:
                    world_obj.select_set(False)
                try:
                    bpy.ops.object.mode_set(mode="EDIT")
                    # Enable X-Ray in 3D viewport so interior block points are easily selectable
                    if hasattr(context, "space_data") and hasattr(context.space_data, "shading"):
                        context.space_data.shading.show_xray = True
                except Exception:
                    pass
            self.report({"INFO"}, f"Voxel Cloud '{cloud_obj.name}' is now visible (Mask unmasked).")
        else:
            # Hidden: return to Object Mode
            if context.mode != "OBJECT":
                try:
                    bpy.ops.object.mode_set(mode="OBJECT")
                except Exception:
                    pass
            if world_obj:
                context.view_layer.objects.active = world_obj
                world_obj.select_set(True)
                if cloud_obj:
                    cloud_obj.select_set(False)
            self.report({"INFO"}, f"Voxel Cloud '{cloud_obj.name}' is now masked and hidden.")

        return {"FINISHED"}


@register_menu_item(views=["object", "mesh"], label="Remesh from Voxel Cloud")
class MOZI_OT_remesh_from_voxel_cloud(bpy.types.Operator):
    """
    Reconstructs the surface mesh from the persistent Voxel Point Cloud.
    Applies any user block deletions (carved caves, mining pits) and updates topology, AO, and materials.
    """

    bl_idname = "mozi.remesh_from_voxel_cloud"
    bl_label = "Remesh from Voxel Cloud"
    bl_options = {"REGISTER", "UNDO"}

    enable_ao: BoolProperty(
        name="Smooth AO",
        description="Calculate 4-corner ambient occlusion lighting",
        default=True,
    )

    mesh_fluids: BoolProperty(
        name="Mesh Fluids",
        description="Reconstruct physically-accurate water and lava fluid geometry",
        default=True,
    )

    weld_vertices: BoolProperty(
        name="Weld Vertices",
        description="Weld adjacent coplanar vertices into manifold topology",
        default=True,
    )

    origin_centered: BoolProperty(
        name="Origin Centered",
        description="Center mesh coordinate bounds relative to selection bottom center",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        world_obj, cloud_obj = _resolve_world_and_cloud_objects(context)
        return cloud_obj is not None and world_obj is not None

    def execute(self, context):
        world_obj, cloud_obj = _resolve_world_and_cloud_objects(context)
        if world_obj is None or cloud_obj is None:
            self.report({"WARNING"}, "Both world mesh and associated voxel cloud are required.")
            return {"CANCELLED"}

        # Ensure object mode before reading geometry
        saved_mode = context.mode
        if saved_mode != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass

        # 1. Extract live VoxelPointCloud from cloud object
        cloud_data = extract_voxel_point_cloud(cloud_obj)
        if cloud_data is None:
            self.report({"ERROR"}, "Failed to extract voxel point cloud data from companion object.")
            return {"CANCELLED"}

        pt_count = len(cloud_data)
        if pt_count == 0:
            world_obj.data.clear_geometry()
            self.report({"INFO"}, "Voxel cloud is empty; cleared world mesh.")
            return {"FINISHED"}

        # 2. Reconstruct VoxelStorage purely from point cloud
        storage = cloud_data.to_storage()

        # 3. Meshing pipeline assets
        prefs = get_prefs(context)
        model_db, atlas, biome_resolver = get_world_pipeline_assets(prefs)

        # 4. Mesh the voxel volume
        try:
            mesh_data, elapsed_ms = mesh_voxel_storage(
                storage=storage,
                model_db=model_db,
                atlas=atlas,
                biome_resolver=biome_resolver,
                prefs=prefs,
                enable_ao=self.enable_ao,
                mesh_fluids=self.mesh_fluids,
                weld_vertices=self.weld_vertices,
                origin_centered=self.origin_centered,
            )
        except Exception as e:
            self.report({"ERROR"}, f"Remeshing failed: {e}")
            return {"CANCELLED"}

        # 5. Inject geometry back into world mesh
        inject_mesh_data(
            world_obj.data,
            mesh_data,
            update_topology=True,
            update_normals=True,
        )

        # 6. Ensure materials
        used_chunk_ids = mesh_data.used_materials() if hasattr(mesh_data, "used_materials") else None
        ensure_world_materials(world_obj, prefs=prefs, atlas=atlas, used_chunk_ids=used_chunk_ids)

        # 7. Restore active selection
        context.view_layer.objects.active = world_obj
        world_obj.select_set(True)
        if cloud_obj != world_obj:
            cloud_obj.select_set(False)

        poly_count = len(world_obj.data.polygons)
        self.report(
            {"INFO"},
            f"Remeshed from {pt_count} voxel points -> {poly_count} polygons in {elapsed_ms:.1f}ms."
        )
        return {"FINISHED"}


@register_menu_item(views=["object", "mesh"], label="Rematerialize from Voxel Cloud")
class MOZI_OT_rematerialize_from_voxel_cloud(bpy.types.Operator):
    """
    Reconstructs and binds updated Atlas Chunk materials and UVs directly from
    voxel point cloud blockstates after asset rebaking.
    """

    bl_idname = "mozi.rematerialize_from_voxel_cloud"
    bl_label = "Rematerialize from Voxel Cloud"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        world_obj, cloud_obj = _resolve_world_and_cloud_objects(context)
        return cloud_obj is not None and world_obj is not None

    def execute(self, context):
        # Simply triggers full remesh with current precompiled atlas assets
        bpy.ops.mozi.remesh_from_voxel_cloud("INVOKE_DEFAULT")
        return {"FINISHED"}


OPERATOR_CLASSES = (
    MOZI_OT_toggle_voxel_cloud,
    MOZI_OT_remesh_from_voxel_cloud,
    MOZI_OT_rematerialize_from_voxel_cloud,
)
