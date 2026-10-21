"""
Operators for Material Replacement and Provenance Recovery.
"""

from __future__ import annotations

import logging
import bpy
from bpy.props import BoolProperty, EnumProperty

logger = logging.getLogger("MoziToolKit.Operators.Materials")

try:
    from ..utils.assets import can_execute_asset_pipeline, check_asset_cache_status, ensure_pipeline_assets_ready_sync
    from ..utils.materials.biome import BIOME_ENUM_ITEMS
    from ..utils.materials.pipeline import replace_materials
    from ..utils.mesh.ownership import is_external_mesh
    from ..utils.system import get_prefs, register_menu_item
except (ImportError, ValueError):
    from utils.assets import can_execute_asset_pipeline, check_asset_cache_status, ensure_pipeline_assets_ready_sync
    from utils.materials.biome import BIOME_ENUM_ITEMS
    from utils.materials.pipeline import replace_materials
    from utils.mesh.ownership import is_external_mesh
    from utils.system import get_prefs, register_menu_item


def _has_provenance_attributes(obj: bpy.types.Object | None) -> bool:
    """Pre-detection check whether object has valid mesh provenance attributes."""
    if not obj or obj.type != "MESH" or not obj.data:
        return False
    mesh = obj.data
    return bool(hasattr(mesh, "attributes") and ("mtk_source_texture_key" in mesh.attributes or "mtk_source_texture_idx" in mesh.attributes))


@register_menu_item(views=["object", "mesh"], label="Replace Material")
class MOZI_OT_replace_material(bpy.types.Operator):
    """Replace and upgrade materials on external imported meshes using the native material pipeline."""

    bl_idname = "mozi.replace_material"
    bl_label = "Replace Material"
    bl_options = {"REGISTER", "UNDO"}

    reuse_atlas_uvs: BoolProperty(
        name="Reuse Atlas UVs",
        description=(
            "Reuse the existing MTK_Atlas UV map when the atlas layout is unchanged; "
            "disable to force re-mapping from the preserved local UVs"
        ),
        default=True,
    )

    mode: EnumProperty(
        name="Material Mode",
        description="Target material organization mode",
        items=[
            ("ATLAS", "Atlas Mode", "Pack into single or few Atlas Chunk materials for maximum viewport performance"),
        ],
        default="ATLAS",
    )

    biome_preset: EnumProperty(
        name="Biome",
        description="Choose the Minecraft Biome color palette preset for grass, foliage, and water tinting",
        items=BIOME_ENUM_ITEMS,
        default="PLAINS",
    )

    origin: EnumProperty(
        name="Source Importer",
        description="Geometry and material origin format",
        items=[
            ("AUTO", "Auto Detect", "Automatically detect from material names and geometry"),
            ("MINEWAYS", "Mineways", "Mineways grid-based terrain atlas"),
            ("JMC2OBJ", "jmc2obj", "jmc2obj individual tiled texture blocks"),
            ("ICE_CUBE", "Ice-Cube", "Ice-Cube asset library format"),
            ("GENERIC", "Generic", "Standard OBJ/FBX/glTF blocks"),
        ],
        default="AUTO",
    )

    @classmethod
    def poll(cls, context):
        # Replace Material only accepts external imports. MTK-generated meshes
        # derive their materials from a voxel source and must be rebuilt.
        if not is_external_mesh(getattr(context, "active_object", None)):
            return False
        prefs = get_prefs(context)
        can_run, reason = can_execute_asset_pipeline(prefs)
        if not can_run:
            if hasattr(cls, "poll_message_set"):
                cls.poll_message_set(reason)
            return False
        return True

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        has_prov = _has_provenance_attributes(obj)
        if has_prov:
            layout.prop(self, "reuse_atlas_uvs")
            layout.separator()

        layout.prop(self, "biome_preset")

        if not (has_prov and self.reuse_atlas_uvs):
            layout.prop(self, "origin")

    def execute(self, context):
        obj = context.active_object
        prefs = get_prefs(context)

        # Asset readiness gate: verify vanilla base pack and cache freshness before material operations
        can_run, reason = can_execute_asset_pipeline(prefs)
        if not can_run:
            self.report({'WARNING'}, reason)
            return {'CANCELLED'}

        status = check_asset_cache_status(prefs)
        if status in ("NO_PACKS", "NO_VANILLA"):
            self.report({'WARNING'}, reason)
            return {'CANCELLED'}
        if status in ("MISSING", "STALE"):
            self.report({'INFO'}, f"Asset cache is {status.lower()}; automatically precompiling before replacing materials...")
            success, _ = ensure_pipeline_assets_ready_sync(prefs)
            if not success:
                self.report({'ERROR'}, "Failed to precompile assets.")
                return {'CANCELLED'}

        # UV layer creation and bulk UV writes target the mesh data; leave Edit Mode first.
        if getattr(context, "mode", "OBJECT") != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass

        # The pipeline decides between reusing the existing atlas UV map (layout
        # unchanged) and re-mapping from the preserved local UV map (layout changed).
        try:
            res = replace_materials(
                obj,
                mode=self.mode,
                origin=self.origin,
                biome=self.biome_preset,
                prefs=prefs,
                force_remap=not self.reuse_atlas_uvs,
            )
            if res.get("success"):
                if res.get("reused_atlas_uvs"):
                    uv_note = f"reused {res.get('atlas_uv_layer', 'MTK_Atlas')} UVs"
                else:
                    uv_note = (
                        f"re-mapped atlas UVs from "
                        f"{res.get('local_uv_layer', 'local UV map')}"
                    )
                msg = (
                    f"Replaced materials for {res['face_count']} faces "
                    f"({res['materials_count']} {self.mode.lower()} materials assigned, "
                    f"biome: {res.get('biome', self.biome_preset)}; {uv_note})."
                )
                if res.get("animated_faces", 0) > 0:
                    msg += f" [{res['animated_faces']} animated faces]"
                if res.get("unmapped_faces", 0) > 0:
                    msg += f" [{res['unmapped_faces']} faces unmapped/fallback]"
                self.report({'INFO'}, msg)
                return {'FINISHED'}
            self.report({'WARNING'}, res.get("message", "Material replacement failed."))
            return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Material replacement error: {e}")
            return {'CANCELLED'}


OPERATOR_CLASSES = (
    MOZI_OT_replace_material,
)
OPERATORS_CLASSES = OPERATOR_CLASSES

