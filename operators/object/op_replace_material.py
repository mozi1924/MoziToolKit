import bpy
from bpy.props import EnumProperty
from ...utils.system import register_menu_item, has_pillow, draw_pillow_warning, get_prefs
from ...utils.materials import get_configured_pack_stack, BIOME_ENUM_ITEMS


@register_menu_item(views=["object"])
class MOZI_OT_replace_material(bpy.types.Operator):
    """Replace selected objects' materials using the prioritized Resource Pack Stack configured in Addon Preferences."""

    bl_idname = "mozi.replace_material"
    bl_label = "Replace Material"
    bl_options = {"REGISTER"}

    material_mode: EnumProperty(
        name="Material Mode",
        description="Choose whether to bind unified Atlas materials or Standalone per-texture materials",
        items=[
            ("ATLAS", "Atlas (Recommended)", "Unified texture atlas with UDIM/chunk UV mapping. High performance and live-sync compatible."),
            ("STANDALONE", "Standalone", "Individual textures and separate materials per block face for granular shading."),
        ],
        default='ATLAS',
    )

    biome_preset: EnumProperty(
        name="Biome",
        description="Choose the Minecraft Biome color palette preset for grass, foliage, and water tinting",
        items=BIOME_ENUM_ITEMS,
        default='PLAINS',
    )

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.selected_objects)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        box_mode = layout.box()
        box_mode.label(text="Material Pipeline Mode:", icon="MATERIAL")
        row = box_mode.row(align=True)
        row.prop(self, "material_mode", expand=True)

        if self.material_mode == "ATLAS":
            box_mode.label(text="* High performance chunk atlas, synchronized with Live Sync.", icon="INFO")
        else:
            box_mode.label(text="* Individual per-face shader materials and textures.", icon="INFO")

        layout.separator()
        box_biome = layout.box()
        box_biome.label(text="Biome Color Tinting:", icon="WORLD")
        box_biome.prop(self, "biome_preset", text="Preset")

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
                "No active resource packs or Minecraft JARs found! Please configure your Resource Pack Stack in Edit > Preferences > Add-ons > MoziToolKit and click 'Precompile / Rebuild Stack Caches'."
            )
            return {"CANCELLED"}

        prefs = get_prefs(context)
        material_mode = self.material_mode
        biome_preset = self.biome_preset
        pack_textures = getattr(prefs, "pack_textures", True) if prefs else True

        if material_mode == "STANDALONE":
            if not pack_stack.is_standalone_baked():
                self.report(
                    {'ERROR'},
                    "The configured Resource Pack Stack has not been precompiled for Standalone mode. "
                    "Please go to Edit > Preferences > Add-ons > MoziToolKit and click 'Precompile / Rebuild Stack Caches'."
                )
                return {"CANCELLED"}
        else:
            if not pack_stack.is_stack_baked():
                self.report(
                    {'ERROR'},
                    "The configured Resource Pack Stack has not been precompiled. "
                    "Please go to Edit > Preferences > Add-ons > MoziToolKit and click 'Precompile / Rebuild Stack Caches'."
                )
                return {"CANCELLED"}

        params = {
            "pack_stack": pack_stack,
            "zip_path": str(pack_stack.packs[0].zip_path if pack_stack.packs[0].zip_path else pack_stack.packs[0].extract_dir),
            "material_mode": material_mode,
            "pack_textures": pack_textures,
            "biome_preset": biome_preset,
        }

        from ...pipeline import get_preset_pipeline, run_pipeline_modal
        from ...pipeline.step import StepStatus

        pipeline = get_preset_pipeline("replace_material")
        if not pipeline:
            self.report({'ERROR'}, "Preset pipeline 'replace_material' not found.")
            return {"CANCELLED"}

        def on_replacement_finished(result, ctx):
            if result.is_success:
                for obj in ctx.target_objects:
                    if obj:
                        obj["mtk:biome_preset"] = biome_preset

        res, ctx = run_pipeline_modal(
            pipeline,
            context,
            params=params,
            target_objects=list(context.selected_objects),
            on_finish=on_replacement_finished,
            title="Replace Material",
        )

        for level, msg in ctx.reports:
            self.report({level}, msg)

        if not res.is_success and res.status != StepStatus.CANCELLED:
            return {"CANCELLED"}

        return {"FINISHED"}


@register_menu_item(views=["object"])
class MOZI_OT_restore_materials_from_provenance(bpy.types.Operator):
    """Restore material slots and shader node trees purely from mesh face metadata (mtk_source_texture_key / chunk attributes)."""

    bl_idname = "mozi.restore_materials_from_provenance"
    bl_label = "Restore Materials from Attributes"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.selected_objects)

    def execute(self, context):
        from ...utils.materials.pipeline.provenance import reconstruct_materials_from_mesh_provenance
        from ...utils.materials import get_configured_pack_stack

        pack_stack = None
        try:
            pack_stack = get_configured_pack_stack()
        except Exception:
            pass

        restored_count = 0
        for obj in context.selected_objects:
            if obj.type == "MESH" and obj.data:
                success = reconstruct_materials_from_mesh_provenance(
                    mesh=obj.data,
                    obj=obj,
                    pack_stack=pack_stack,
                )
                if success:
                    restored_count += 1

        if restored_count > 0:
            self.report({'INFO'}, f"Successfully restored materials for {restored_count} object(s) from face attributes.")
            return {"FINISHED"}
        else:
            self.report({'WARNING'}, "No face provenance metadata found (mtk_source_texture_key or mtk_atlas_chunk_id).")
            return {"CANCELLED"}


