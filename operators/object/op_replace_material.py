import bpy
from ...utils.system import register_menu_item, has_pillow, draw_pillow_warning, get_prefs
from ...utils.materials import has_yefira_objects, get_configured_pack_stack


@register_menu_item(views=["object"])
class MOZI_OT_replace_material(bpy.types.Operator):
    """Replace selected objects' materials using the prioritized Resource Pack Stack configured in Addon Preferences."""

    bl_idname = "mozi.replace_material"
    bl_label = "Replace Material"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.selected_objects)

    def execute(self, context):
        if not has_pillow():
            self.report(
                {'ERROR'},
                "Material replacement requires 'Pillow' (PIL) module. Please ensure Pillow or extension wheels are installed."
            )
            return {"CANCELLED"}

        pack_stack = get_configured_pack_stack()
        if not pack_stack.packs:
            self.report(
                {'ERROR'},
                "No active resource packs or Minecraft JARs found! Please configure your Resource Pack Stack in Edit > Preferences > Add-ons > MoziToolKit > Resource Packs & Base JARs."
            )
            return {"CANCELLED"}

        prefs = get_prefs(context)
        material_mode = getattr(prefs, "material_mode", "ATLAS") if prefs else "ATLAS"
        biome_preset = getattr(prefs, "biome_preset", "PLAINS") if prefs else "PLAINS"
        pack_textures = getattr(prefs, "pack_textures", True) if prefs else True

        is_yefira = has_yefira_objects(context.selected_objects)
        effective_mode = 'ATLAS' if is_yefira else material_mode

        params = {
            "pack_stack": pack_stack,
            "zip_path": str(pack_stack.packs[0].zip_path if pack_stack.packs[0].zip_path else pack_stack.packs[0].extract_dir),
            "material_mode": effective_mode,
            "pack_textures": pack_textures,
            "biome_preset": biome_preset,
        }

        from ...pipeline import get_preset_pipeline, run_pipeline_modal
        from ...pipeline.step import StepStatus

        pipeline = get_preset_pipeline("replace_material")
        if not pipeline:
            self.report({'ERROR'}, "Preset pipeline 'replace_material' not found.")
            return {"CANCELLED"}

        res, ctx = run_pipeline_modal(
            pipeline,
            context,
            params=params,
            title="Replace Material",
        )

        for level, msg in ctx.reports:
            self.report({level}, msg)

        if not res.is_success and res.status != StepStatus.CANCELLED:
            return {"CANCELLED"}

        return {"FINISHED"}

