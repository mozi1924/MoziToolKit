"""
Minecraft Biome Control Panels for Object Properties and 3D Viewport.
Allows instantaneous switching of Minecraft Biome palettes (Grass, Foliage, Water)
for Atlas and Standalone mesh objects without running full material rebuilds.
"""

from __future__ import annotations

import bpy
from bpy.props import EnumProperty

try:
    from ..utils.materials.biome import (
        BIOME_ENUM_ITEMS,
        get_biome_colors,
        is_mtk_object,
        detect_object_material_mode,
        update_object_biome,
    )
    from ..i18n import tr
except (ImportError, ValueError):
    from utils.materials.biome import (
        BIOME_ENUM_ITEMS,
        get_biome_colors,
        is_mtk_object,
        detect_object_material_mode,
        update_object_biome,
    )
    try:
        from i18n import tr
    except (ImportError, ValueError):
        def tr(msgid: str, msgctxt: str | None = None) -> str:
            return msgid


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


def _on_custom_param_changed(self, context):
    """Real-time update callback when custom biome temperature, humidity, or colors change."""
    if self.get("mtk:biome_preset", "PLAINS") == "CUSTOM":
        update_object_biome(self, "CUSTOM")


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

        src = context.object
        count = 0
        for obj in target_objs:
            if self.biome_preset == "CUSTOM" and src and src != obj:
                # Copy custom biome attributes to target objects
                obj.mtk_biome_temp = src.mtk_biome_temp
                obj.mtk_biome_humidity = src.mtk_biome_humidity
                obj.mtk_biome_use_custom_grass = src.mtk_biome_use_custom_grass
                obj.mtk_biome_grass_color = src.mtk_biome_grass_color
                obj.mtk_biome_use_custom_foliage = src.mtk_biome_use_custom_foliage
                obj.mtk_biome_foliage_color = src.mtk_biome_foliage_color
                obj.mtk_biome_use_custom_dry_foliage = src.mtk_biome_use_custom_dry_foliage
                obj.mtk_biome_dry_foliage_color = src.mtk_biome_dry_foliage_color
                obj.mtk_biome_water_color = src.mtk_biome_water_color

            if update_object_biome(obj, self.biome_preset):
                count += 1

        self.report({'INFO'}, f"Applied '{self.biome_preset}' biome palette to {count} object(s).")
        return {'FINISHED'}


def _draw_biome_ui(layout, context, obj: bpy.types.Object):
    mode = detect_object_material_mode(obj)
    current_biome = obj.get("mtk:biome_preset", "PLAINS")
    is_custom = current_biome == "CUSTOM"

    box = layout.box()
    row_top = box.row(align=True)
    mode_translated = tr(mode.title()) if mode else mode
    row_top.label(text=f"{tr('Material Mode')}: {mode_translated}", icon="MATERIAL")

    row_preset = box.row(align=True)
    row_preset.prop(obj, "mtk_biome", text=tr("Biome"))

    if is_custom:
        # Custom Biome Configuration Controls
        col_custom = box.column(align=True)
        col_custom.use_property_split = True
        col_custom.use_property_decorate = False

        # Climate & Colormap Sampling
        box_climate = col_custom.box()
        box_climate.label(text=tr("Colormap Sampling (Climate)"), icon="RESTRICT_COLOR_OFF")
        col_clim_props = box_climate.column(align=True)
        col_clim_props.prop(obj, "mtk_biome_temp", text=tr("Temperature"), slider=True)
        col_clim_props.prop(obj, "mtk_biome_humidity", text=tr("Downfall"), slider=True)

        # Color Overrides
        box_colors = col_custom.box()
        box_colors.label(text=tr("Color Overrides"), icon="COLOR")

        # Grass Color
        row_g = box_colors.row(align=True)
        row_g.prop(obj, "mtk_biome_use_custom_grass", text=tr("Override Grass"))
        if obj.mtk_biome_use_custom_grass:
            row_g.prop(obj, "mtk_biome_grass_color", text="")

        # Foliage Color
        row_f = box_colors.row(align=True)
        row_f.prop(obj, "mtk_biome_use_custom_foliage", text=tr("Override Foliage"))
        if obj.mtk_biome_use_custom_foliage:
            row_f.prop(obj, "mtk_biome_foliage_color", text="")

        # Dry Foliage Color
        row_df = box_colors.row(align=True)
        row_df.prop(obj, "mtk_biome_use_custom_dry_foliage", text=tr("Override Dry Foliage"))
        if obj.mtk_biome_use_custom_dry_foliage:
            row_df.prop(obj, "mtk_biome_dry_foliage_color", text="")

        # Water Color
        row_w = box_colors.row(align=True)
        row_w.label(text=tr("Water Color"))
        row_w.prop(obj, "mtk_biome_water_color", text="")
    else:
        # Standard Biome Preset Info
        biome_info = get_biome_colors(current_biome)
        col_info = box.column(align=True)
        row_temp = col_info.row(align=True)
        row_temp.label(text=f"{tr('Temperature')}: {biome_info.get('temperature', 0.8):.2f}")
        row_temp.label(text=f"{tr('Downfall')}: {biome_info.get('humidity', 0.4):.2f}")

        row_cols = box.row(align=True)
        row_cols.scale_y = 0.8
        grass_hex = biome_info.get("grass_hex", "#91BD59")
        foliage_hex = biome_info.get("foliage_hex", "#77AB2F")
        row_cols.label(text=f"{tr('Grass')}: {grass_hex}")
        row_cols.label(text=f"{tr('Foliage')}: {foliage_hex}")

    # Batch button if multiple objects selected
    sel_mtk = [o for o in context.selected_objects if is_mtk_object(o)]
    if len(sel_mtk) > 1:
        row_batch = box.row(align=True)
        op = row_batch.operator("mozi.set_object_biome", text=f"{tr('Apply to All Selected')} ({len(sel_mtk)})", icon="COPYDOWN")
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
    bpy.types.Object.mtk_biome_temp = bpy.props.FloatProperty(
        name="Temperature",
        description="Custom temperature for colormap sampling (-1.0 to 2.0)",
        default=0.8,
        min=-1.0,
        max=2.0,
        step=1,
        precision=2,
        update=_on_custom_param_changed,
    )
    bpy.types.Object.mtk_biome_humidity = bpy.props.FloatProperty(
        name="Downfall",
        description="Custom humidity / rainfall for colormap sampling (0.0 to 1.0)",
        default=0.4,
        min=0.0,
        max=1.0,
        step=1,
        precision=2,
        update=_on_custom_param_changed,
    )
    bpy.types.Object.mtk_biome_use_custom_grass = bpy.props.BoolProperty(
        name="Override Grass Color",
        description="Override grass color directly instead of colormap sampling",
        default=False,
        update=_on_custom_param_changed,
    )
    bpy.types.Object.mtk_biome_grass_color = bpy.props.FloatVectorProperty(
        name="Grass Color",
        description="Custom grass tint color",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(0.28, 0.51, 0.10, 1.0),
        update=_on_custom_param_changed,
    )
    bpy.types.Object.mtk_biome_use_custom_foliage = bpy.props.BoolProperty(
        name="Override Foliage Color",
        description="Override foliage color directly instead of colormap sampling",
        default=False,
        update=_on_custom_param_changed,
    )
    bpy.types.Object.mtk_biome_foliage_color = bpy.props.FloatVectorProperty(
        name="Foliage Color",
        description="Custom foliage tint color",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(0.18, 0.41, 0.03, 1.0),
        update=_on_custom_param_changed,
    )
    bpy.types.Object.mtk_biome_use_custom_dry_foliage = bpy.props.BoolProperty(
        name="Override Dry Foliage Color",
        description="Override dry foliage color directly instead of colormap sampling",
        default=False,
        update=_on_custom_param_changed,
    )
    bpy.types.Object.mtk_biome_dry_foliage_color = bpy.props.FloatVectorProperty(
        name="Dry Foliage Color",
        description="Custom dry foliage tint color",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(0.37, 0.18, 0.06, 1.0),
        update=_on_custom_param_changed,
    )
    bpy.types.Object.mtk_biome_water_color = bpy.props.FloatVectorProperty(
        name="Water Color",
        description="Custom water color",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(0.05, 0.18, 0.78, 1.0),
        update=_on_custom_param_changed,
    )


def unregister():
    for prop in (
        "mtk_biome",
        "mtk_biome_temp",
        "mtk_biome_humidity",
        "mtk_biome_use_custom_grass",
        "mtk_biome_grass_color",
        "mtk_biome_use_custom_foliage",
        "mtk_biome_foliage_color",
        "mtk_biome_use_custom_dry_foliage",
        "mtk_biome_dry_foliage_color",
        "mtk_biome_water_color",
    ):
        if hasattr(bpy.types.Object, prop):
            try:
                delattr(bpy.types.Object, prop)
            except Exception:
                pass

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
