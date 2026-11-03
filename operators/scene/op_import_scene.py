"""
Operator for importing an MTK Scene Interchange package (.mtkscene).
"""

from __future__ import annotations

import logging
from pathlib import Path

try:
    import bpy
    from bpy.props import BoolProperty, StringProperty
    from bpy_extras.io_utils import ImportHelper
    HAS_BPY = True
except ImportError:
    bpy = None
    ImportHelper = object
    BoolProperty = StringProperty = lambda **kwargs: None
    HAS_BPY = False

from ...bridge.scene import load_and_mesh_scene_package
from ...utils.scene.hierarchy import apply_imported_scene_to_blender
from ...utils.system.dependencies import get_prefs

logger = logging.getLogger("MoziToolKit.Operators.Scene.Import")


class MOZI_OT_import_scene(bpy.types.Operator, ImportHelper):
    """Import an MTK Scene package (.mtkscene) with companion point cloud and mini-atlas"""

    bl_idname = "mozi.import_scene"
    bl_label = "Import MTK Scene (.mtkscene)"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".mtkscene"
    filter_glob: StringProperty(  # type: ignore
        default="*.mtkscene",
        options={"HIDDEN"},
    )

    enable_ao: BoolProperty(  # type: ignore
        name="Smooth AO",
        description="Compute smooth ambient occlusion for block vertices",
        default=True,
    )

    mesh_fluids: BoolProperty(  # type: ignore
        name="Mesh Fluids",
        description="Generate fluid surface geometry",
        default=True,
    )

    weld_vertices: BoolProperty(  # type: ignore
        name="Weld Vertices",
        description="Weld spatial coplanar vertices for clean smooth shading",
        default=True,
    )

    origin_centered: BoolProperty(  # type: ignore
        name="Center Origin",
        description="Center object geometry origin at bounding box center",
        default=True,
    )

    def execute(self, context):
        if not HAS_BPY:
            return {"CANCELLED"}

        path = Path(self.filepath).resolve()
        if not path.exists() or not path.is_file():
            self.report({"ERROR"}, f"Scene file does not exist: {path}")
            return {"CANCELLED"}

        prefs = get_prefs(context)

        try:
            data = load_and_mesh_scene_package(
                path=path,
                prefs=prefs,
                enable_ao=self.enable_ao,
                mesh_fluids=self.mesh_fluids,
                weld_vertices=self.weld_vertices,
                origin_centered=self.origin_centered,
            )

            stem = path.stem
            res = apply_imported_scene_to_blender(
                data=data,
                scene_name=stem,
                origin_centered=self.origin_centered,
            )

            v_count = data.get("metadata", {}).get("voxel_count", 0)
            total_ms = data.get("total_ms", 0.0)

            # Select root container
            root_obj = res.get("root_obj")
            if root_obj and hasattr(context, "view_layer"):
                for obj in getattr(context, "selected_objects", []):
                    if hasattr(obj, "select_set"):
                        obj.select_set(False)
                if hasattr(root_obj, "select_set"):
                    root_obj.select_set(True)
                if hasattr(context.view_layer, "objects"):
                    try:
                        context.view_layer.objects.active = root_obj
                    except Exception:
                        pass

            self.report(
                {"INFO"},
                f"Imported MTK Scene '{stem}' ({v_count} voxels in {total_ms:.1f}ms).",
            )
            return {"FINISHED"}
        except Exception as e:
            logger.exception("Failed importing scene package: %s", e)
            self.report({"ERROR"}, f"Failed importing scene package: {e}")
            return {"CANCELLED"}
