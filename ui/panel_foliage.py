"""
Foliage Wind Control Panel for Object Properties and 3D Viewport.

Provides interactive sliders for wind direction, wiggle amplitude, speed, noise scale,
and target scope (Leaves, Plants, All) with instant updates on the modifier and batch-apply.
Fully compatible with Blender 4.x (IDProperties) and Blender 5.x (modifier.properties.inputs).
"""

from __future__ import annotations

import bpy
from bpy.props import EnumProperty, FloatProperty

from ..utils.foliage import (
    TARGET_SCOPE_ITEMS,
    TARGET_SCOPE_ALL,
    SCOPE_TO_GROUP,
    NODE_GROUP_NAME,
    MODIFIER_NAME,
    get_or_create_foliage_node_group,
    apply_foliage_modifier,
)
from ..utils.foliage.geo_node_builder import (
    get_modifier_input_value,
    set_modifier_input_value,
)
from ..utils.materials.biome import is_mtk_object


def _get_foliage_modifier(obj: bpy.types.Object) -> bpy.types.NodesModifier | None:
    if not obj or obj.type != "MESH":
        return None
    for m in obj.modifiers:
        if m.type == 'NODES' and m.node_group and m.node_group.name == NODE_GROUP_NAME:
            return m
    return None


def _get_socket_ident(node_group: bpy.types.GeometryNodeTree, socket_name: str) -> str | None:
    if hasattr(node_group, "interface"):
        for item in node_group.interface.items_tree:
            if item.in_out == 'INPUT' and item.name == socket_name:
                return item.identifier
    return None


# Property getters and setters attached to Object
def _get_foliage_scope(self) -> int:
    mod = _get_foliage_modifier(self)
    if not mod or not mod.node_group:
        return 0
    ident = _get_socket_ident(mod.node_group, "Selection Group")
    cur_val = get_modifier_input_value(mod, ident, "MTK_Foliage_All")
    for idx, item in enumerate(TARGET_SCOPE_ITEMS):
        if SCOPE_TO_GROUP.get(item[0]) == cur_val:
            return idx
    return 0


def _set_foliage_scope(self, value: int):
    mod = _get_foliage_modifier(self)
    if not mod or not mod.node_group:
        return
    scope_key = TARGET_SCOPE_ITEMS[value][0]
    group_name = SCOPE_TO_GROUP.get(scope_key, "MTK_Foliage_All")
    ident = _get_socket_ident(mod.node_group, "Selection Group")
    if ident:
        set_modifier_input_value(mod, ident, group_name)


def _get_wind_direction(self) -> float:
    mod = _get_foliage_modifier(self)
    if not mod or not mod.node_group:
        return 45.0
    ident = _get_socket_ident(mod.node_group, "Wind Direction (Deg)")
    return float(get_modifier_input_value(mod, ident, 45.0))


def _set_wind_direction(self, value: float):
    mod = _get_foliage_modifier(self)
    if not mod or not mod.node_group:
        return
    ident = _get_socket_ident(mod.node_group, "Wind Direction (Deg)")
    if ident:
        set_modifier_input_value(mod, ident, float(value))


def _get_wiggle_amplitude(self) -> float:
    mod = _get_foliage_modifier(self)
    if not mod or not mod.node_group:
        return 0.06
    ident = _get_socket_ident(mod.node_group, "Wiggle Amplitude")
    return float(get_modifier_input_value(mod, ident, 0.06))


def _set_wiggle_amplitude(self, value: float):
    mod = _get_foliage_modifier(self)
    if not mod or not mod.node_group:
        return
    ident = _get_socket_ident(mod.node_group, "Wiggle Amplitude")
    if ident:
        set_modifier_input_value(mod, ident, float(value))


def _get_wiggle_speed(self) -> float:
    mod = _get_foliage_modifier(self)
    if not mod or not mod.node_group:
        return 3.0
    ident = _get_socket_ident(mod.node_group, "Wiggle Speed")
    return float(get_modifier_input_value(mod, ident, 3.0))


def _set_wiggle_speed(self, value: float):
    mod = _get_foliage_modifier(self)
    if not mod or not mod.node_group:
        return
    ident = _get_socket_ident(mod.node_group, "Wiggle Speed")
    if ident:
        set_modifier_input_value(mod, ident, float(value))


def _get_noise_scale(self) -> float:
    mod = _get_foliage_modifier(self)
    if not mod or not mod.node_group:
        return 1.2
    ident = _get_socket_ident(mod.node_group, "Noise Scale")
    return float(get_modifier_input_value(mod, ident, 1.2))


def _set_noise_scale(self, value: float):
    mod = _get_foliage_modifier(self)
    if not mod or not mod.node_group:
        return
    ident = _get_socket_ident(mod.node_group, "Noise Scale")
    if ident:
        set_modifier_input_value(mod, ident, float(value))


def _draw_foliage_ui(layout, context, obj: bpy.types.Object):
    mod = _get_foliage_modifier(obj)

    from ..i18n import tr
    _tr = tr

    box = layout.box()
    row_top = box.row(align=True)
    row_top.label(text=_tr("Foliage Wind Wiggle"), icon="FORCE_WIND")

    if not mod:
        col = box.column(align=True)
        col.label(text=_tr("No foliage wind modifier applied."))
        col.operator("mozi.apply_foliage_waving", text=_tr("Apply Foliage Wind"), icon="MOD_PHYSICS")
        return

    # Scope selection dropdown
    col = box.column(align=True)
    col.prop(obj, "mtk_foliage_scope", text=_tr("Target Scope"))

    # Parameters
    col.prop(obj, "mtk_wind_direction", text=_tr("Wind Direction"), slider=True)
    col.prop(obj, "mtk_wiggle_amplitude", text=_tr("Wiggle Amplitude"), slider=True)
    col.prop(obj, "mtk_wiggle_speed", text=_tr("Wiggle Speed"), slider=True)
    col.prop(obj, "mtk_noise_scale", text=_tr("Noise Scale"), slider=True)

    # Batch operation button if multiple mesh objects selected
    sel_meshes = [o for o in context.selected_objects if o.type == 'MESH']
    if len(sel_meshes) > 1:
        box.separator()
        row_batch = box.row(align=True)
        from ..i18n import tr
        _tr = tr
        op = row_batch.operator(
            "mozi.sync_foliage_settings",
            text=f"{_tr('Apply to Selected Objects')} ({len(sel_meshes) - 1})",
            icon="COPYDOWN"
        )


class MOZI_PT_object_foliage(bpy.types.Panel):
    """Foliage Wind control panel in Object Properties tab."""

    bl_label = "Minecraft Foliage Wind"
    bl_idname = "MOZI_PT_object_foliage"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        return is_mtk_object(context.object) or (
            context.object and context.object.type == "MESH" and _get_foliage_modifier(context.object) is not None
        )

    def draw(self, context):
        _draw_foliage_ui(self.layout, context, context.object)


class MOZI_PT_view3d_foliage(bpy.types.Panel):
    """Foliage Wind control panel in 3D Viewport Sidebar (N-panel)."""

    bl_label = "Minecraft Foliage Wind"
    bl_idname = "MOZI_PT_view3d_foliage"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mozi"

    @classmethod
    def poll(cls, context):
        return is_mtk_object(context.object) or (
            context.object and context.object.type == "MESH" and _get_foliage_modifier(context.object) is not None
        )

    def draw(self, context):
        _draw_foliage_ui(self.layout, context, context.object)


classes = (
    MOZI_PT_object_foliage,
    MOZI_PT_view3d_foliage,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Object.mtk_foliage_scope = EnumProperty(
        name="Target Scope",
        description="Choose which foliage elements will sway with the wind",
        items=TARGET_SCOPE_ITEMS,
        get=_get_foliage_scope,
        set=_set_foliage_scope,
    )

    bpy.types.Object.mtk_wind_direction = FloatProperty(
        name="Wind Direction",
        description="Wind angle in degrees (0 to 360)",
        default=45.0,
        min=0.0,
        max=360.0,
        get=_get_wind_direction,
        set=_set_wind_direction,
    )

    bpy.types.Object.mtk_wiggle_amplitude = FloatProperty(
        name="Wiggle Amplitude",
        description="Amplitude of in-place foliage wiggle (meters)",
        default=0.06,
        min=0.0,
        max=0.5,
        get=_get_wiggle_amplitude,
        set=_set_wiggle_amplitude,
    )

    bpy.types.Object.mtk_wiggle_speed = FloatProperty(
        name="Wiggle Speed",
        description="Speed of foliage wiggle oscillation",
        default=3.0,
        min=0.0,
        max=20.0,
        get=_get_wiggle_speed,
        set=_set_wiggle_speed,
    )

    bpy.types.Object.mtk_noise_scale = FloatProperty(
        name="Noise Scale",
        description="Spatial frequency / scale of 4D noise",
        default=1.2,
        min=0.05,
        max=10.0,
        get=_get_noise_scale,
        set=_set_noise_scale,
    )


def unregister():
    for prop in (
        "mtk_foliage_scope",
        "mtk_wind_direction",
        "mtk_wiggle_amplitude",
        "mtk_wiggle_speed",
        "mtk_noise_scale",
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
