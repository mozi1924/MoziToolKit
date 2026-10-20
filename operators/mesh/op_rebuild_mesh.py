"""
Unified Voxel Mesh Reconstruction Operator.
Reconstructs voxel surface mesh with manifold topology, smooth AO, fluids, and atlas shaders.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import bpy

try:
    from ...utils.system import get_prefs, register_menu_item
    from ...utils.async_task import AsyncTask, ModalTaskRunner
    from ...utils.progress import BlenderProgressReporter
    from ...bridge.point_cloud import extract_voxel_point_cloud
    from ...bridge.world import (
        clear_world_sessions,
        ensure_world_materials,
        get_world_pipeline_assets,
        mesh_voxel_storage,
        prepare_world_mesh_context,
    )
    from ...bridge.mesh import inject_mesh_data
    from ...bridge.sync import get_sync_bridge_session
    from ...bridge.assets import (
        prepare_asset_context,
        check_asset_cache_status,
        check_cache_dirty,
        ensure_pipeline_assets_ready_sync,
        invalidate_asset_cache_memory,
        reload_atlas_images,
        run_task_with_asset_guard,
    )
    from ...utils.mesh.ownership import (
        ORIGIN_EXTERNAL,
        ORIGIN_VOXEL,
        classify_origin,
        stamp_geometry_origin,
    )
except (ImportError, ValueError):
    from utils.system import get_prefs, register_menu_item
    from utils.async_task import AsyncTask, ModalTaskRunner
    from utils.progress import BlenderProgressReporter
    from bridge.point_cloud import extract_voxel_point_cloud
    from bridge.world import (
        clear_world_sessions,
        ensure_world_materials,
        get_world_pipeline_assets,
        mesh_voxel_storage,
        prepare_world_mesh_context,
    )
    from bridge.mesh import inject_mesh_data
    from bridge.sync import get_sync_bridge_session
    from bridge.assets import (
        prepare_asset_context,
        check_asset_cache_status,
        check_cache_dirty,
        ensure_pipeline_assets_ready_sync,
        invalidate_asset_cache_memory,
        reload_atlas_images,
        run_task_with_asset_guard,
    )
    from utils.mesh.ownership import (
        ORIGIN_EXTERNAL,
        ORIGIN_VOXEL,
        classify_origin,
        stamp_geometry_origin,
    )


def _resolve_mesh_rebuild_targets_from_root(
    root_container: bpy.types.Object,
) -> Tuple[bpy.types.Object, Optional[bpy.types.Object], Optional[bpy.types.Object], str]:
    """Helper to locate child mesh and child point cloud under an Empty root container."""
    container_type = "SAVE"
    if hasattr(root_container, "get"):
        c_type = root_container.get("mtk:container_type")
        if c_type:
            container_type = str(c_type)
        elif root_container.get("mtk:is_yefira_world") or root_container.name.startswith("Yefira_World"):
            container_type = "SYNC"
    elif root_container.name.startswith("Yefira_World"):
        container_type = "SYNC"

    mesh_child = None
    cloud_child = None
    children = getattr(root_container, "children", [])
    for ch in children:
        if getattr(ch, "type", "") == "MESH":
            is_cloud = False
            if hasattr(ch, "get"):
                is_cloud = bool(ch.get("mtk_is_voxel_cloud"))
            if not is_cloud and getattr(ch, "name", "").endswith("_VoxelCloud"):
                is_cloud = True

            if is_cloud:
                cloud_child = ch
            else:
                # Prefer an MTK-generated mesh when a user has parented an
                # external mesh under the same container.
                if mesh_child is None:
                    mesh_child = ch
                elif (
                    classify_origin(mesh_child) == ORIGIN_EXTERNAL
                    and classify_origin(ch) != ORIGIN_EXTERNAL
                ):
                    mesh_child = ch

    if mesh_child is None and hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
        cand = bpy.data.objects.get(f"{root_container.name}_Mesh")
        if cand and getattr(cand, "type", "") == "MESH":
            mesh_child = cand
    if cloud_child is None and hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
        cand = bpy.data.objects.get(f"{root_container.name}_VoxelCloud")
        if cand and getattr(cand, "type", "") == "MESH":
            cloud_child = cand

    return root_container, mesh_child, cloud_child, container_type


def resolve_mesh_rebuild_targets(
    context: Optional[bpy.types.Context],
) -> Tuple[Optional[bpy.types.Object], Optional[bpy.types.Object], Optional[bpy.types.Object], str]:
    """
    Resolves (root_container, world_mesh_obj, cloud_obj, source_type) from context selection.
    source_type can be:
      - "SYNC": Live Sync world container or section mesh
      - "SAVE": Minecraft Save container or mesh
      - "CLOUD": Standalone or companion Voxel Point Cloud
      - "NONE": Unrecognized or non-voxel object
    """
    if context is None:
        return None, None, None, "NONE"

    active = getattr(context, "active_object", None)
    if not active:
        selected = getattr(context, "selected_objects", [])
        active = selected[0] if selected else None

    if not active:
        return None, None, None, "NONE"

    # 1. Target is an Empty container root (SYNC or SAVE)
    if getattr(active, "type", "") == 'EMPTY':
        return _resolve_mesh_rebuild_targets_from_root(active)

    # 2. Target is a Mesh object
    if getattr(active, "type", "") == "MESH":
        # Check if parent is an Empty container
        parent = getattr(active, "parent", None)
        if parent and getattr(parent, "type", "") == 'EMPTY':
            is_cont = False
            if hasattr(parent, "get"):
                is_cont = bool(parent.get("mtk:is_container") or parent.get("mtk:is_yefira_world"))
            if is_cont or parent.name.startswith("Save_") or parent.name.startswith("Yefira_World"):
                c_root, c_mesh, c_cloud, c_type = _resolve_mesh_rebuild_targets_from_root(parent)
                if getattr(active, "name", "").endswith("_VoxelCloud") or (hasattr(active, "get") and active.get("mtk_is_voxel_cloud")):
                    c_cloud = active
                else:
                    c_mesh = active
                return c_root, c_mesh, c_cloud, c_type

        # Check if active itself is a companion voxel point cloud
        is_cloud = False
        if hasattr(active, "get"):
            is_cloud = bool(active.get("mtk_is_voxel_cloud"))
        if not is_cloud and getattr(active, "name", "").endswith("_VoxelCloud"):
            is_cloud = True

        if is_cloud:
            cloud_obj = active
            world_mesh = None
            if hasattr(active, "get"):
                w_name = active.get("mtk_world_mesh")
                if w_name and hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
                    world_mesh = bpy.data.objects.get(w_name)
            if world_mesh is None and active.name.endswith("_VoxelCloud"):
                base = active.name[:-11]
                for cand_name in (f"{base}_Mesh", base):
                    if hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
                        cand = bpy.data.objects.get(cand_name)
                        if cand and getattr(cand, "type", "") == "MESH":
                            world_mesh = cand
                            break
            return None, world_mesh, cloud_obj, "CLOUD"

        # Check if active is a world mesh with companion point cloud or Live Sync mesh
        cloud_obj = None
        if hasattr(active, "get"):
            c_name = active.get("mtk_voxel_cloud")
            if c_name and hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
                cloud_obj = bpy.data.objects.get(c_name)
        if cloud_obj is None and hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
            conv_name = f"{active.name}_VoxelCloud"
            cand = bpy.data.objects.get(conv_name)
            if cand and getattr(cand, "type", "") == "MESH":
                cloud_obj = cand
            elif active.name.endswith("_Mesh"):
                base = active.name[:-5]
                cand = bpy.data.objects.get(f"{base}_VoxelCloud")
                if cand and getattr(cand, "type", "") == "MESH":
                    cloud_obj = cand

        is_sync = False
        if hasattr(active, "get") and (active.get("mtk:is_yefira_mesh") or active.get("mtk:is_yefira_world")):
            is_sync = True
        elif active.name.startswith("Yefira_World"):
            is_sync = True

        if is_sync:
            return None, active, cloud_obj, "SYNC"

        if cloud_obj is not None:
            return None, active, cloud_obj, "SAVE"

    return None, None, None, "NONE"


def _live_session_matches_container(
    context: Optional[Any],
    root_container: Optional[bpy.types.Object],
) -> bool:
    """Return True when an active Live Sync session owns this container."""
    session = get_sync_bridge_session() if callable(get_sync_bridge_session) else None
    if not session or not getattr(session, "is_active", False):
        return False

    scene = getattr(context, "scene", None) if context is not None else None
    active_name = getattr(scene, "mozi_active_sync_container_name", "") if scene is not None else ""
    if not isinstance(active_name, str):
        active_name = ""

    if root_container is not None and active_name:
        return getattr(root_container, "name", "") == active_name
    return True


@register_menu_item(views=["object", "mesh"], label="Rebuild Voxel Mesh")
class MOZI_OT_rebuild_mesh(bpy.types.Operator):
    """
    Reconstruct voxel surface mesh with manifold topology, smooth AO, fluids, and atlas shaders.
    Unified operator supporting Live Sync world sessions, Save containers, and Voxel Point Clouds.
    """

    bl_idname = "mozi.rebuild_mesh"
    bl_label = "Rebuild Voxel Mesh"
    bl_description = "Unified rebuild of voxel surface geometry from Live Sync, Save container, or Point Cloud"
    bl_options = {"REGISTER", "UNDO"}

    enable_ao: bpy.props.BoolProperty(
        name="Ambient Occlusion",
        description="Calculate smooth 4-corner ambient occlusion lighting",
        default=True,
    )

    mesh_fluids: bpy.props.BoolProperty(
        name="Mesh Fluids",
        description="Reconstruct physically-accurate fluid surfaces",
        default=True,
    )

    weld_vertices: bpy.props.BoolProperty(
        name="Weld Vertices",
        description="Weld adjacent coplanar vertices into manifold topology",
        default=True,
    )

    origin_centered: bpy.props.BoolProperty(
        name="Origin Centered",
        description="Center mesh coordinate bounds relative to selection bottom center",
        default=True,
    )

    run_async: bpy.props.BoolProperty(
        name="Run Asynchronously",
        description="Run calculation in non-blocking background thread with live status bar progress",
        default=True,
        options={"HIDDEN"},
    )

    _runner: Optional[Any] = None

    @classmethod
    def poll(cls, context):
        if not context:
            return False
        root_container, world_mesh, cloud_obj, source_type = resolve_mesh_rebuild_targets(context)
        if source_type == "NONE":
            return False

        # An external mesh parented under an MTK container must not be
        # overwritten with voxel-generated geometry.
        if source_type in ("SAVE", "SYNC") and world_mesh is not None:
            if classify_origin(world_mesh) == ORIGIN_EXTERNAL:
                return False

        if source_type == "SYNC":
            # Active sessions rebuild from in-memory storage; offline sessions
            # require the persistent companion point cloud.
            if _live_session_matches_container(context, root_container):
                return True
            return cloud_obj is not None

        if source_type == "SAVE":
            # Offline rebuild requires the persistent voxel point cloud.
            return cloud_obj is not None

        if source_type == "CLOUD":
            # A standalone cloud needs an existing surface mesh to receive geometry.
            return cloud_obj is not None and world_mesh is not None

        return False

    def execute(self, context):
        root_container, world_mesh_obj, cloud_obj, source_type = resolve_mesh_rebuild_targets(context)
        if source_type == "NONE" or (world_mesh_obj is None and cloud_obj is None and root_container is None):
            self.report({"WARNING"}, "No valid Live Sync, Save container, or Voxel Point Cloud found.")
            return {"CANCELLED"}

        prefs = get_prefs(context)
        status = check_asset_cache_status(prefs)

        # Ensure Object mode
        saved_mode = getattr(context, "mode", "OBJECT")
        if saved_mode != "OBJECT" and hasattr(bpy.ops, "object") and hasattr(bpy.ops.object, "mode_set"):
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass

        # Branch A: Active Live Sync session
        session = get_sync_bridge_session() if callable(get_sync_bridge_session) else None

        use_live_session = False
        if source_type == "SYNC" and session and getattr(session, "is_active", False):
            active_c_name = getattr(context.scene, "mozi_active_sync_container_name", "") if hasattr(context, "scene") else ""
            if not root_container or not active_c_name or root_container.name == active_c_name:
                use_live_session = True

        if use_live_session:
            try:
                from ..sync.hierarchy import get_or_create_world_mesh_object, update_world_mesh
            except Exception:
                from operators.sync.hierarchy import get_or_create_world_mesh_object, update_world_mesh

            prefs = get_prefs(context)
            if status in ("MISSING", "STALE"):
                ensure_pipeline_assets_ready_sync(prefs)
                if hasattr(session, "check_and_reload_dirty_cache"):
                    session.check_and_reload_dirty_cache(prefs=prefs, force=True)
            elif hasattr(session, "check_and_reload_dirty_cache"):
                try:
                    session.check_and_reload_dirty_cache(prefs=prefs)
                except Exception:
                    pass

            def do_live_rebuild(progress_callback=None):
                return session.get_world_mesh()

            def on_live_success(mesh_data):
                if not mesh_data or mesh_data.vertex_count == 0:
                    self.report({"WARNING"}, "Voxel storage is empty or no geometry generated.")
                    return
                target_root = root_container
                world_obj = world_mesh_obj or get_or_create_world_mesh_object(context, root_container=target_root)
                storage = session.get_storage()
                v_count, f_count = update_world_mesh(world_obj, mesh_data, storage=storage, sync_point_cloud=True)
                root_obj = target_root or world_obj
                props = getattr(root_obj, "mozi_sync", None) or (getattr(context.scene, "mozi_sync", None) if hasattr(context, "scene") else None)
                if props:
                    props.point_count = v_count
                    props.faces_count = f_count
                    props.last_update_info = f"Rebuilt World Mesh: {v_count:,} vertices, {f_count:,} faces"
                self.report({"INFO"}, f"Live Sync mesh rebuilt: {v_count:,} vertices, {f_count:,} faces")

            if not self.run_async:
                try:
                    data = do_live_rebuild()
                    on_live_success(data)
                    return {"FINISHED"}
                except Exception as e:
                    self.report({"ERROR"}, f"Failed rebuilding live sync mesh: {e}")
                    return {"CANCELLED"}

            task = AsyncTask(target=do_live_rebuild)
            reporter = BlenderProgressReporter(context=context, total=100, title="Rebuilding World Mesh")
            self._runner = ModalTaskRunner(
                operator=self,
                context=context,
                task=task,
                reporter=reporter,
                on_success=on_live_success,
                title="Rebuilding World Mesh",
            )
            return self._runner.start()

        # Branch B: Remesh from companion Voxel Point Cloud (Save container, offline Sync, or Carved cloud)
        if status == "NO_PACKS":
            self.report({"WARNING"}, "No enabled resource packs configured. Configure a Minecraft pack in Preferences if rebuild fails.")
        if cloud_obj is None:
            self.report({"WARNING"}, "Associated Voxel Point Cloud is required for offline mesh reconstruction.")
            return {"CANCELLED"}

        cloud_data = extract_voxel_point_cloud(cloud_obj)
        if cloud_data is None:
            self.report({"ERROR"}, "Failed to extract voxel point cloud data from companion object.")
            return {"CANCELLED"}

        pt_count = len(cloud_data)
        if pt_count == 0:
            if world_mesh_obj and hasattr(world_mesh_obj, "data") and hasattr(world_mesh_obj.data, "clear_geometry"):
                world_mesh_obj.data.clear_geometry()
            self.report({"INFO"}, "Voxel cloud is empty; cleared mesh geometry.")
            return {"FINISHED"}

        # Inherit settings from root container or operator properties
        enable_ao = getattr(self, "enable_ao", True)
        if hasattr(enable_ao, "default"):
            enable_ao = enable_ao.default
        elif not isinstance(enable_ao, bool):
            enable_ao = True

        mesh_fluids = getattr(self, "mesh_fluids", True)
        if hasattr(mesh_fluids, "default"):
            mesh_fluids = mesh_fluids.default
        elif not isinstance(mesh_fluids, bool):
            mesh_fluids = True

        weld_vertices = getattr(self, "weld_vertices", True)
        if hasattr(weld_vertices, "default"):
            weld_vertices = weld_vertices.default
        elif not isinstance(weld_vertices, bool):
            weld_vertices = True

        origin_centered = getattr(self, "origin_centered", True)
        if hasattr(origin_centered, "default"):
            origin_centered = origin_centered.default
        elif not isinstance(origin_centered, bool):
            origin_centered = True
        if root_container is not None and hasattr(root_container, "get"):
            if root_container.get("mtk_enable_ao") is not None:
                enable_ao = bool(root_container.get("mtk_enable_ao"))
            if root_container.get("mtk_mesh_fluids") is not None:
                mesh_fluids = bool(root_container.get("mtk_mesh_fluids"))
            if root_container.get("mtk_weld_vertices") is not None:
                weld_vertices = bool(root_container.get("mtk_weld_vertices"))
            if root_container.get("mtk_origin_centered") is not None:
                origin_centered = bool(root_container.get("mtk_origin_centered"))

        prefs = get_prefs(context)
        did_precompile = False
        if status in ("MISSING", "STALE"):
            try:
                ensure_pipeline_assets_ready_sync(prefs)
            except Exception as e:
                self.report({"ERROR"}, f"Failed to precompile assets: {e}")
                return {"CANCELLED"}
            did_precompile = True
            status = "READY"

        # Resolve every bpy-backed value before launching the worker. The worker
        # only receives plain Python/Rust objects and never touches bpy.
        asset_context = prepare_asset_context(prefs)
        mesh_context = prepare_world_mesh_context(prefs)
        model_db = mesh_context["model_db"]
        atlas = mesh_context["atlas"]
        biome_resolver = mesh_context["biome_resolver"]
        ctm_solver = mesh_context["ctm_solver"]
        num_threads = mesh_context["num_threads"]
        anim_tex_enabled = mesh_context["enable_animated_textures"]
        cache_fingerprint = mesh_context["cache_fingerprint"]
        cache_timestamp = mesh_context["cache_timestamp"]

        session_key = (
            getattr(root_container, "name", None)
            or (root_container.get("mozi_save_uuid") if root_container and hasattr(root_container, "get") else None)
            or (getattr(world_mesh_obj, "name", None))
            or (getattr(cloud_obj, "name", "global_cloud"))
        )

        def do_cloud_rebuild(progress_callback=None):
            storage = cloud_data.to_storage()
            mesh_data, elapsed_ms = mesh_voxel_storage(
                storage=storage,
                model_db=model_db,
                atlas=atlas,
                biome_resolver=biome_resolver,
                ctm_solver=ctm_solver,
                prefs=prefs,
                enable_ao=enable_ao,
                mesh_fluids=mesh_fluids,
                weld_vertices=weld_vertices,
                origin_centered=origin_centered,
                num_threads=num_threads,
                progress_callback=progress_callback,
                world_session_key=session_key,
                force_rebuild=did_precompile,
                enable_animated_textures=anim_tex_enabled,
                cache_fingerprint=cache_fingerprint,
                cache_timestamp=cache_timestamp,
                resolve_prefs=False,
                resolve_ctm=False,
            )
            # Keep the rebuilt storage so the success handler can cache it for
            # later WORLD biome re-tints.
            return mesh_data, elapsed_ms, storage

        def on_cloud_success(result_tuple):
            storage = None
            if isinstance(result_tuple, tuple) and len(result_tuple) == 2 and isinstance(result_tuple[1], bool):
                inner, did_precompile = result_tuple
                if len(inner) == 3:
                    mesh_data, elapsed_ms, storage = inner
                else:
                    mesh_data, elapsed_ms = inner
                if did_precompile:
                    try:
                        reload_atlas_images(prefs)
                    except Exception:
                        pass
            elif isinstance(result_tuple, tuple) and len(result_tuple) == 3:
                mesh_data, elapsed_ms, storage = result_tuple
            else:
                mesh_data, elapsed_ms = result_tuple

            nonlocal world_mesh_obj
            if world_mesh_obj is None and root_container is not None:
                mesh_name = f"{root_container.name}_Mesh"
                b_mesh = bpy.data.meshes.new(mesh_name)
                world_mesh_obj = bpy.data.objects.new(mesh_name, b_mesh)
                if hasattr(world_mesh_obj, "parent"):
                    world_mesh_obj.parent = root_container
                target_coll = context.collection if context and context.collection else (
                    bpy.context.scene.collection if hasattr(bpy.context, "scene") else None
                )
                if target_coll and hasattr(target_coll, "objects") and hasattr(target_coll.objects, "link"):
                    target_coll.objects.link(world_mesh_obj)

                # The new mesh inherits the container's origin so it is not
                # mistaken for an external import.
                root_origin = classify_origin(root_container)
                if root_origin == ORIGIN_EXTERNAL:
                    root_origin = ORIGIN_VOXEL
                stamp_geometry_origin(world_mesh_obj, root_origin, overwrite=True)

            if world_mesh_obj and hasattr(world_mesh_obj, "data"):
                inject_mesh_data(
                    world_mesh_obj.data,
                    mesh_data,
                    update_topology=True,
                    update_normals=True,
                )
                used_chunk_ids = mesh_data.used_materials() if hasattr(mesh_data, "used_materials") else None
                ensure_world_materials(world_mesh_obj, prefs=prefs, atlas=atlas, used_chunk_ids=used_chunk_ids)

                # Offline rebuilds resample the 3D biomes from the point cloud, so
                # the object must advertise the WORLD preset (and keep that storage
                # available for later panel edits).
                try:
                    from ...utils.materials.biome.updater import mark_world_biome
                except (ImportError, ValueError):
                    try:
                        from utils.materials.biome.updater import mark_world_biome
                    except Exception:
                        mark_world_biome = None
                if mark_world_biome is not None:
                    aliases = []
                    if root_container is not None:
                        aliases.append(getattr(root_container, "name", ""))
                        container_id = root_container.get("mtk:container_id", "") if hasattr(root_container, "get") else ""
                        if isinstance(container_id, str) and container_id:
                            aliases.append(container_id)
                        mark_world_biome(root_container, storage)
                    mark_world_biome(world_mesh_obj, storage, aliases=aliases)

                poly_cnt = len(world_mesh_obj.data.polygons) if hasattr(world_mesh_obj.data, "polygons") else 0
                self.report({"INFO"}, f"Rebuilt voxel mesh: {poly_cnt:,} faces in {round(elapsed_ms, 1)}ms")
            else:
                self.report({"WARNING"}, "No mesh object available to receive geometry.")

        if not self.run_async:
            try:
                res = do_cloud_rebuild()
                on_cloud_success(res)
                return {"FINISHED"}
            except Exception as e:
                self.report({"ERROR"}, f"Remeshing failed: {e}")
                return {"CANCELLED"}

        task = AsyncTask(
            target=run_task_with_asset_guard,
            kwargs={
                "target_func": do_cloud_rebuild,
                "target_kwargs": {},
                "prefs": prefs,
                "task_title": "Rebuilding Voxel Mesh",
                "asset_context": asset_context,
            },
        )
        reporter = BlenderProgressReporter(context=context, total=100, title="Rebuilding Voxel Mesh")
        self._runner = ModalTaskRunner(
            operator=self,
            context=context,
            task=task,
            reporter=reporter,
            on_success=on_cloud_success,
            title="Rebuilding Voxel Mesh",
        )
        return self._runner.start()

    def modal(self, context, event):
        if self._runner is not None:
            return self._runner.modal(event)
        return {"FINISHED"}
