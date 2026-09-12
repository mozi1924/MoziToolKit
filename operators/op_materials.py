"""
Operators for Material Replacement and Provenance Recovery.
"""

from __future__ import annotations

import bpy
from bpy.props import EnumProperty

from ..utils.materials.pipeline import replace_materials, restore_materials_from_provenance
from ..utils.system import get_prefs, register_menu_item


@register_menu_item(views=["object", "mesh"], label="Replace Materials (libmtk)")
class MOZI_OT_replace_materials(bpy.types.Operator):
    """Replace and upgrade Minecraft materials using pure Rust libmtk backend."""

    bl_idname = "mozi.replace_materials"
    bl_label = "Replace Materials (libmtk)"
    bl_options = {"REGISTER", "UNDO"}


    mode: EnumProperty(
        name="Material Mode",
        description="Target material organization mode",
        items=[
            ("ATLAS", "Atlas Mode", "Pack into single or few Atlas Chunk materials for maximum viewport performance"),
            ("STANDALONE", "Standalone Mode", "Generate individual Principled BSDF / LabPBR materials for each block"),
        ],
        default="ATLAS",
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
        return context.active_object and context.active_object.type == "MESH"

    def execute(self, context):
        obj = context.active_object
        prefs = get_prefs(context)

        try:
            res = replace_materials(obj, mode=self.mode, origin=self.origin, prefs=prefs)
            if res.get("success"):
                msg = (
                    f"Replaced materials for {res['face_count']} faces "
                    f"({res['materials_count']} {self.mode.lower()} materials assigned)."
                )
                if res.get("unmapped_faces", 0) > 0:
                    msg += f" [{res['unmapped_faces']} faces unmapped/fallback]"
                self.report({'INFO'}, msg)
                return {'FINISHED'}
            else:
                self.report({'WARNING'}, res.get("message", "Material replacement failed."))
                return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Material replacement error: {e}")
            return {'CANCELLED'}


@register_menu_item(views=["object", "mesh"], label="Restore Materials From Mesh")
class MOZI_OT_restore_materials_from_provenance(bpy.types.Operator):
    """Restore and reconstruct material slots and shader trees from mesh provenance attributes."""

    bl_idname = "mozi.restore_materials_from_provenance"
    bl_label = "Restore Materials From Mesh"
    bl_options = {"REGISTER", "UNDO"}


    mode: EnumProperty(
        name="Material Mode",
        description="Target material organization mode",
        items=[
            ("ATLAS", "Atlas Mode", "Reconstruct Atlas Chunk materials"),
            ("STANDALONE", "Standalone Mode", "Reconstruct Standalone block materials"),
        ],
        default="ATLAS",
    )

    @classmethod
    def poll(cls, context):
        if not context.active_object or context.active_object.type != "MESH":
            return False
        mesh = context.active_object.data
        return hasattr(mesh, "attributes") and "mtk_source_texture_key" in mesh.attributes

    def execute(self, context):
        obj = context.active_object
        prefs = get_prefs(context)

        try:
            res = restore_materials_from_provenance(obj, mode=self.mode, prefs=prefs)
            if res.get("success"):
                self.report(
                    {'INFO'},
                    f"Successfully restored {res['materials_count']} materials for {res['restored_faces']} faces."
                )
                return {'FINISHED'}
            else:
                self.report({'WARNING'}, res.get("message", "Restoration failed."))
                return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Restoration error: {e}")
            return {'CANCELLED'}


OPERATORS_CLASSES = (
    MOZI_OT_replace_materials,
    MOZI_OT_restore_materials_from_provenance,
)
