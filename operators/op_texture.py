"""
Texture and Shading Utility Operators for MoziToolKit.
"""

from __future__ import annotations

import bpy
from bpy.props import EnumProperty

try:
    from ..utils.system import register_menu_item
except (ImportError, ValueError):
    from utils.system import register_menu_item


@register_menu_item(views=["object"], label="Set Image Interpolation to Closest")
class MOZI_OT_set_texture_interpolation_closest(bpy.types.Operator):
    """Set interpolation of all image texture nodes in selected objects' materials to Closest (pixelated)"""

    bl_idname = "mozi.set_texture_interpolation_closest"
    bl_label = "Set Image Interpolation to Closest"
    bl_options = {"REGISTER", "UNDO"}

    interpolation: EnumProperty(
        name="Interpolation",
        description="Texture sampling interpolation mode",
        items=[
            ("Closest", "Closest (Pixelated)", "No smoothing, preserve raw pixel art sharpness"),
            ("Linear", "Linear", "Standard bilinear interpolation"),
            ("Cubic", "Cubic", "Bicubic smooth interpolation"),
            ("Smart", "Smart", "Bicubic with special filtering"),
        ],
        default="Closest",
    )

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects or context.active_object)

    def execute(self, context):
        targets = context.selected_objects or ([context.active_object] if context.active_object else [])
        processed_materials = set()
        nodes_modified = 0

        for obj in targets:
            if not hasattr(obj, "material_slots"):
                continue
            for slot in obj.material_slots:
                mat = slot.material
                if not mat or not mat.use_nodes or not mat.node_tree:
                    continue
                if mat.name in processed_materials:
                    continue
                processed_materials.add(mat.name)

                for node in mat.node_tree.nodes:
                    if node.type == "TEX_IMAGE":
                        if getattr(node, "interpolation", "") != self.interpolation:
                            node.interpolation = self.interpolation
                            nodes_modified += 1

        mat_count = len(processed_materials)
        if mat_count == 0:
            self.report({"WARNING"}, "No materials found on selected objects.")
        elif nodes_modified == 0:
            self.report({"INFO"}, f"Processed {mat_count} material(s), all image texture nodes are already set to {self.interpolation}.")
        else:
            self.report({"INFO"}, f"Set {nodes_modified} image texture node(s) to {self.interpolation} across {mat_count} material(s).")

        return {"FINISHED"}


OPERATORS_CLASSES = (
    MOZI_OT_set_texture_interpolation_closest,
)
