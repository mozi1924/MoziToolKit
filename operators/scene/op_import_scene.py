"""
Operator for importing an MTK Scene Interchange package (.mtkscene).
"""

from __future__ import annotations

import logging
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from ...bridge.scene import inspect_scene_package, load_and_mesh_scene_package
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

    enable_animated_textures: BoolProperty(  # type: ignore
        name="Animated Textures",
        description="Enable animated texture frame playback for water, lava, fire, and animated blocks",
        default=True,
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

    allow_host_fallback: BoolProperty(  # type: ignore
        name="Allow Host Fallback",
        description="Allow falling back to local asset cache if the scene package is missing models or textures",
        default=False,
    )

    enable_ctm: BoolProperty(  # type: ignore
        name="Connected Textures (CTM)",
        description="Apply the connected-texture rules embedded in the scene package",
        default=True,
    )

    material_mode: EnumProperty(  # type: ignore
        name="Material Mode",
        description="Shader material assembly mode for imported scene geometry",
        items=[
            ("ATLAS", "PBR Atlas", "Canonical Principled BSDF with self-contained Mini-Atlas"),
        ],
        default="ATLAS",
    )

    def draw(self, context):
        from ...i18n import tr
        layout = self.layout

        # 1. Scene Info Preview box (if a file is selected)
        if self.filepath:
            path = Path(self.filepath)
            if path.exists() and path.is_file():
                try:
                    meta = inspect_scene_package(path)
                    box_info = layout.box()
                    box_info.label(text=tr("Scene Capsule Info"), icon="INFO")
                    box_info.label(text=f"{tr('File')}: {path.name}")

                    bounds = meta.get("bounds", [0, 0, 0, 0, 0, 0])
                    dx, dy, dz = bounds[3], bounds[4], bounds[5]
                    v_count = meta.get("voxel_count", 0)
                    box_info.label(
                        text=f"{tr('Bounds')}: {dx} × {dy} × {dz} ({v_count:,} {tr('voxels')})",
                        icon="SNAP_INCREMENT",
                    )

                    u_states = meta.get("unique_states_count", 0)
                    u_biomes = meta.get("unique_biomes_count", 0)
                    u_entities = meta.get("unique_entities_count", 0)
                    box_info.label(
                        text=f"{tr('Palette')}: {u_states} states, {u_biomes} biomes, {u_entities} entities",
                    )

                    res = meta.get("atlas_resolution", [0, 0])
                    has_anim = meta.get("has_animated_atlas", False)
                    anim_badge = tr("Yes") if has_anim else tr("No")
                    box_info.label(
                        text=f"{tr('Mini-Atlas')}: {res[0]}×{res[1]} (Animated: {anim_badge})",
                        icon="TEXTURE",
                    )
                except Exception as e:
                    logger.debug("Failed inspecting scene package for UI preview: %s", e)

        # 2. Meshing & Shading Options
        box_mesh = layout.box()
        box_mesh.label(text=tr("Meshing & Shaders"), icon="SHADING_RENDERED")
        box_mesh.prop(self, "enable_animated_textures", text=tr("Animated Textures"))
        box_mesh.prop(self, "enable_ao", text=tr("Smooth AO"))
        box_mesh.prop(self, "mesh_fluids", text=tr("Mesh Fluids"))
        box_mesh.prop(self, "weld_vertices", text=tr("Weld Vertices"))
        box_mesh.prop(self, "origin_centered", text=tr("Center Origin"))
        box_mesh.prop(self, "allow_host_fallback", text=tr("Allow Host Fallback"))
        box_mesh.prop(self, "enable_ctm", text=tr("Connected Textures (CTM)"))

    def execute(self, context):

        path = Path(self.filepath).resolve()
        if not path.exists() or not path.is_file():
            self.report({"ERROR"}, f"Scene file does not exist: {path}")
            return {"CANCELLED"}

        prefs = get_prefs(context)

        try:
            enable_anim = getattr(self, "enable_animated_textures", True)
            allow_fallback = getattr(self, "allow_host_fallback", False)
            enable_ctm = getattr(self, "enable_ctm", True)
            data = load_and_mesh_scene_package(
                path=path,
                prefs=prefs,
                enable_ao=getattr(self, "enable_ao", True),
                mesh_fluids=getattr(self, "mesh_fluids", True),
                weld_vertices=getattr(self, "weld_vertices", True),
                origin_centered=getattr(self, "origin_centered", True),
                enable_animated_textures=enable_anim,
                allow_host_fallback=allow_fallback,
                enable_ctm=enable_ctm,
            )

            stem = path.stem
            res = apply_imported_scene_to_blender(
                data=data,
                scene_name=stem,
                origin_centered=getattr(self, "origin_centered", True),
                context=context,
                prefs=prefs,
                enable_animated_textures=enable_anim,
            )

            v_count = data.get("metadata", {}).get("voxel_count", 0)
            total_ms = data.get("total_ms", 0.0)

            # Select root container
            root_obj = res.get("root_obj")
            if root_obj and hasattr(context, "view_layer"):
                for obj in getattr(context, "selected_objects", []):
                    if hasattr(obj, "select_set"):
                        try:
                            obj.select_set(False)
                        except Exception:
                            pass
                if hasattr(root_obj, "select_set"):
                    try:
                        root_obj.select_set(True)
                    except Exception:
                        pass
                if hasattr(context.view_layer, "objects"):
                    try:
                        context.view_layer.objects.active = root_obj
                    except Exception:
                        pass

            if data.get("degraded"):
                self.report(
                    {"WARNING"},
                    f"Scene package was incomplete; imported with host fallback assets.",
                )
            self.report(
                {"INFO"},
                f"Imported MTK Scene '{stem}' ({v_count} voxels in {total_ms:.1f}ms).",
            )
            return {"FINISHED"}
        except Exception as e:
            logger.exception("Failed importing scene package: %s", e)
            self.report({"ERROR"}, f"Failed importing scene package: {e}")
            return {"CANCELLED"}
