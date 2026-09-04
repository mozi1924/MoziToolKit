"""
Foliage Waving Operator for MoziToolKit.

Executes the foliage waving preset pipeline or synchronizes foliage parameters
across selected Minecraft objects.
"""

from __future__ import annotations

import bpy
from bpy.props import EnumProperty, FloatProperty, BoolProperty

from ...utils.foliage import (
    TARGET_SCOPE_ITEMS,
    TARGET_SCOPE_ALL,
    SCOPE_TO_GROUP,
    MODIFIER_NAME,
    apply_foliage_modifier,
    assign_foliage_vertex_groups,
    get_or_create_foliage_node_group,
)
from ...utils.materials.biome import is_mtk_object
from ...utils.system import register_menu_item


@register_menu_item(views=["object"])
class MOZI_OT_apply_foliage_waving(bpy.types.Operator):
    """Scan foliage metadata, create vertex groups, and apply Foliage Wind Geometry Nodes."""

    bl_idname = "mozi.apply_foliage_waving"
    bl_label = "Apply Foliage Wind"
    bl_options = {"REGISTER", "UNDO"}

    target_scope: EnumProperty(
        name="Target Scope",
        description="Choose which foliage elements will sway with the wind",
        items=TARGET_SCOPE_ITEMS,
        default=TARGET_SCOPE_ALL,
    )

    wind_direction: FloatProperty(
        name="Wind Direction",
        description="Wind angle in degrees (0 to 360)",
        default=45.0,
        min=0.0,
        max=360.0,
    )

    wiggle_amplitude: FloatProperty(
        name="Wiggle Amplitude",
        description="Amplitude of in-place foliage wiggle (meters)",
        default=0.06,
        min=0.0,
        max=0.5,
    )

    wiggle_speed: FloatProperty(
        name="Wiggle Speed",
        description="Speed of foliage wiggle oscillation",
        default=3.0,
        min=0.0,
        max=20.0,
    )

    noise_scale: FloatProperty(
        name="Noise Scale",
        description="Spatial frequency / scale of 4D noise",
        default=1.2,
        min=0.05,
        max=10.0,
    )

    apply_to_selected: BoolProperty(
        name="Apply to All Selected",
        description="Apply this foliage wind setup to all selected Minecraft mesh objects",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return any(o.type == "MESH" for o in context.selected_objects)

    def execute(self, context):
        from ...pipeline.presets import run_preset_pipeline

        target_objs = [
            obj for obj in context.selected_objects
            if obj.type == "MESH"
        ] if self.apply_to_selected else ([context.object] if context.object and context.object.type == "MESH" else [])

        if not target_objs:
            self.report({'WARNING'}, "No mesh objects found in selection.")
            return {'CANCELLED'}

        params = {
            "foliage_target_scope": self.target_scope,
            "wind_direction": self.wind_direction,
            "wiggle_amplitude": self.wiggle_amplitude,
            "wiggle_speed": self.wiggle_speed,
            "noise_scale": self.noise_scale,
            "protect_rigid_vertices": True,
        }

        res, ctx = run_preset_pipeline("foliage_waving", context, params=params, target_objects=target_objs)

        # Also sync custom properties to target objects for UI inspection
        for obj in target_objs:
            obj["mtk:foliage_scope"] = self.target_scope
            obj["mtk:wind_direction"] = self.wind_direction
            obj["mtk:wiggle_amplitude"] = self.wiggle_amplitude
            obj["mtk:wiggle_speed"] = self.wiggle_speed
            obj["mtk:noise_scale"] = self.noise_scale

        for level, msg in ctx.reports:
            self.report({level}, msg)

        if not res.is_success:
            return {'CANCELLED'}

        self.report({'INFO'}, f"Foliage wind applied to {len(target_objs)} object(s).")
        return {'FINISHED'}


@register_menu_item(views=["object"])
class MOZI_OT_sync_foliage_settings(bpy.types.Operator):
    """Copy foliage wind parameters from active object to all selected objects."""

    bl_idname = "mozi.sync_foliage_settings"
    bl_label = "Copy Foliage Wind to Selected"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or obj.type != "MESH":
            return False
        return any(m.type == 'NODES' and m.node_group and m.node_group.name == "MTK_Foliage_Wiggle" for m in obj.modifiers)

    def execute(self, context):
        active_obj = context.object
        if not active_obj:
            return {'CANCELLED'}

        ng = get_or_create_foliage_node_group()
        src_mod = None
        for m in active_obj.modifiers:
            if m.type == 'NODES' and m.node_group == ng:
                src_mod = m
                break

        if not src_mod:
            self.report({'WARNING'}, "Active object has no MTK_Foliage_Wiggle modifier.")
            return {'CANCELLED'}

        # Read active modifier input socket values
        sock_vals = {}
        for item in ng.interface.items_tree:
            if item.in_out == 'INPUT':
                ident = item.identifier
                if ident in src_mod:
                    sock_vals[ident] = src_mod[ident]

        target_objs = [o for o in context.selected_objects if o.type == 'MESH' and o != active_obj]
        if not target_objs:
            self.report({'INFO'}, "No other mesh objects selected.")
            return {'CANCELLED'}

        count = 0
        for obj in target_objs:
            assign_foliage_vertex_groups(obj, protect_rigid_vertices=True)
            mod = apply_foliage_modifier(obj, node_group=ng)
            for ident, val in sock_vals.items():
                try:
                    mod[ident] = val
                except Exception:
                    pass
            count += 1

        self.report({'INFO'}, f"Copied foliage wind settings to {count} object(s).")
        return {'FINISHED'}
