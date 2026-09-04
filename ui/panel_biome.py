"""
Minecraft Biome Control Panels for Object Properties and 3D Viewport.
Allows instantaneous switching of Minecraft Biome palettes (Grass, Foliage, Water)
for Atlas and Standalone mesh objects without running full material rebuilds.
"""

from __future__ import annotations

import bpy
from bpy.props import EnumProperty

from ..utils.materials.biome import (
    BIOME_ENUM_ITEMS,
    get_biome_colors,
    is_mtk_object,
    detect_object_material_mode,
    update_object_biome,
)


def _get_object_biome(self) -> int:
    preset = self.get("mtk:biome_preset", "PLAINS")
    for idx, item in enumerate(BIOME_ENUM_ITEMS):
        if item[0] == preset:
            return idx
    return 0


def _set_object_biome(self, value: int):
    if 0 <= value < len(BIOME_ENUM_ITEMS):
        biome_name = BIOME_ENUM_ITEMS[value][0]
        update_object_biome(self, biome_name)


class MOZI_OT_set_object_biome(bpy.types.Operator):
    """Apply selected biome palette to the active or all selected Minecraft objects."""

    bl_idname = "mozi.set_object_biome"
    bl_label = "Apply Biome"
    bl_options = {"REGISTER", "UNDO"}

    biome_preset: EnumProperty(
        name="Biome",
        description="Choose the Minecraft Biome color palette preset",
        items=BIOME_ENUM_ITEMS,
        default="PLAINS",
    )
    apply_to_selected: bpy.props.BoolProperty(
        name="Apply to All Selected",
        description="Apply this biome preset to all selected Minecraft mesh objects",
        default=True,
    )

    def execute(self, context):
        target_objs = [
            obj for obj in context.selected_objects
            if is_mtk_object(obj)
        ] if self.apply_to_selected else ([context.object] if is_mtk_object(context.object) else [])

        if not target_objs:
            self.report({'WARNING'}, "No Minecraft mesh objects found in selection.")
            return {'CANCELLED'}

        count = 0
        for obj in target_objs:
            if update_object_biome(obj, self.biome_preset):
                count += 1

        self.report({'INFO'}, f"Applied '{self.biome_preset}' biome palette to {count} object(s).")
        return {'FINISHED'}


def _draw_biome_ui(layout, context, obj: bpy.types.Object):
    mode = detect_object_material_mode(obj)
    current_biome = obj.get("mtk:biome_preset", "PLAINS")
    biome_info = get_biome_colors(current_biome)
    from ..i18n import tr
    _tr = tr

    box = layout.box()
    row_top = box.row(align=True)
    mode_translated = _tr(mode.title()) if mode else mode
    row_top.label(text=f"{_tr('Material Mode')}: {mode_translated}", icon="MATERIAL")

    row_preset = box.row(align=True)
    row_preset.prop(obj, "mtk_biome", text=_tr("Biome"))

    # Preview Info
    col_info = box.column(align=True)
    row_temp = col_info.row(align=True)
    row_temp.label(text=f"{_tr('Temperature')}: {biome_info.get('temperature', 0.8):.2f}")
    row_temp.label(text=f"{_tr('Downfall')}: {biome_info.get('humidity', 0.4):.2f}")

    # Color previews
    row_cols = box.row(align=True)
    row_cols.scale_y = 0.8
    grass_hex = biome_info.get("grass_hex", "#91BD59")
    foliage_hex = biome_info.get("foliage_hex", "#77AB2F")
    row_cols.label(text=f"{_tr('Grass')}: {grass_hex}")
    row_cols.label(text=f"{_tr('Foliage')}: {foliage_hex}")

    # Batch button if multiple objects selected
    sel_mtk = [o for o in context.selected_objects if is_mtk_object(o)]
    if len(sel_mtk) > 1:
        row_batch = box.row(align=True)
        biome_display = _tr(current_biome.replace('_', ' ').title())
        op = row_batch.operator("mozi.set_object_biome", text=f"{_tr('Apply to All Selected')} ({len(sel_mtk)})", icon="COPYDOWN")
        op.biome_preset = current_biome
        op.apply_to_selected = True


class MOZI_PT_object_biome(bpy.types.Panel):
    """Minecraft Biome control panel in Object Properties tab."""

    bl_label = "Minecraft Biome"
    bl_idname = "MOZI_PT_object_biome"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        return is_mtk_object(context.object)

    def draw(self, context):
        _draw_biome_ui(self.layout, context, context.object)


class MOZI_PT_view3d_biome(bpy.types.Panel):
    """Minecraft Biome control panel in 3D Viewport Sidebar (N-panel)."""

    bl_label = "Minecraft Biome"
    bl_idname = "MOZI_PT_view3d_biome"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mozi"

    @classmethod
    def poll(cls, context):
        return is_mtk_object(context.object)

    def draw(self, context):
        _draw_biome_ui(self.layout, context, context.object)


classes = (
    MOZI_OT_set_object_biome,
    MOZI_PT_object_biome,
    MOZI_PT_view3d_biome,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Object.mtk_biome = EnumProperty(
        name="Biome",
        description="Choose the Minecraft Biome color palette preset for grass, foliage, and water tinting",
        items=BIOME_ENUM_ITEMS,
        get=_get_object_biome,
        set=_set_object_biome,
    )


def unregister():
    if hasattr(bpy.types.Object, "mtk_biome"):
        try:
            del bpy.types.Object.mtk_biome
        except Exception:
            pass

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass


