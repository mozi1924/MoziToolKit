import bpy
from bpy_extras.io_utils import ImportHelper
from ...utils.system import register_menu_item, has_pillow


@register_menu_item(views=["object"])
class MOZI_OT_replace_material(bpy.types.Operator, ImportHelper):
    """Replace selected objects' materials using a Minecraft Java Edition resource pack."""

    bl_idname = "mozi.replace_material"
    bl_label = "Replace Material"
    bl_options = {"REGISTER", "UNDO"}

    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Path to a Minecraft Java Edition resource-pack ZIP/JAR or unpacked directory",
        subtype='FILE_PATH',
    )

    filename_ext = ".zip"
    filter_glob: bpy.props.StringProperty(
        default="*.zip;*.jar",
        options={'HIDDEN'},
        maxlen=255,
    )

    material_mode: bpy.props.EnumProperty(
        name="Material Mode",
        description="Choose how imported materials are structured and generated",
        items=[
            ('STANDALONE', "Standalone", "Create individual materials for each texture (Default)"),
            ('ATLAS', "Atlas", "Combine all textures into a single texture atlas material"),
        ],
        default='STANDALONE',
    )

    biome_preset: bpy.props.EnumProperty(
        name="Biome Palette",
        description="Choose the Minecraft Biome color palette preset for grass, foliage, and water tinting",
        items=[
            ('PLAINS', "Plains", "Default vanilla plains vibrant colors"),
            ('FOREST', "Forest", "Vibrant forest green foliage and grass"),
            ('BIRCH_FOREST', "Birch Forest", "Bright spring green foliage and grass"),
            ('TAIGA', "Taiga", "Cooler spruce forest tones"),
            ('JUNGLE', "Jungle", "Lush vibrant tropical greens"),
            ('SAVANNA', "Savanna", "Warm dry yellowish greens"),
            ('BADLANDS', "Badlands (Mesa)", "Dry olive/brown foliage and grass"),
            ('SWAMP', "Swamp", "Murky dark swamp greens and water"),
            ('DARK_FOREST', "Dark Forest", "Deep dark canopy greens"),
            ('MANGROVE_SWAMP', "Mangrove Swamp", "Warm olive mangrove colors"),
            ('CHERRY_GROVE', "Cherry Grove", "Pastel spring greens"),
            ('SNOWY_PLAINS', "Snowy Plains", "Muted frost green tones"),
            ('DESERT', "Desert", "Dry desert and savanna vegetation tint"),
            ('WARM_OCEAN', "Warm Ocean", "Bright turquoise water"),
        ],
        default='PLAINS',
    )

    pack_textures: bpy.props.BoolProperty(
        name="Pack Textures into Blend File",
        description="Embed imported textures directly into the Blender file. When unchecked and the .blend file is saved, textures will be saved externally to '//textures/block/' in your project directory",
        default=True,
    )

    use_cache: bpy.props.BoolProperty(
        name="Use Resource Pack Cache",
        description="Cache extracted pack in Blender temp directory for faster reuse across projects",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.selected_objects)

    def invoke(self, context, event):
        self.filepath = ""
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Material Options", icon='TEXTURE')
        box.prop(self, "material_mode", text="Mode")
        box.prop(self, "biome_preset", text="Biome")

        if self.material_mode == 'ATLAS' and not has_pillow():
            alert_box = layout.box()
            alert_box.alert = True
            alert_box.label(text="Atlas mode requires 'Pillow' (PIL) module (Missing)!", icon='ERROR')
            alert_box.label(text="Please ensure Pillow or extension wheels are available.")
            op = alert_box.operator("mozi.open_preferences", text="Check Environment", icon='PREFERENCES')
            op.tab = "MISC"

        box.prop(self, "pack_textures")
        if not self.pack_textures:
            box.label(text="Note: Textures will be saved to //textures/block/", icon='INFO')
        box.prop(self, "use_cache")

    def execute(self, context):
        if not self.filepath:
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}

        if self.material_mode == 'ATLAS' and not has_pillow():
            self.report(
                {'ERROR'},
                "Atlas mode requires 'Pillow' (PIL) module. Please ensure Pillow or extension wheels are installed."
            )
            return {"CANCELLED"}

        from ...pipeline import get_preset_pipeline, run_pipeline_modal
        from ...pipeline.step import StepStatus

        params = {
            "zip_path": self.filepath,
            "material_mode": self.material_mode,
            "pack_textures": self.pack_textures,
            "use_cache": self.use_cache,
            "biome_preset": self.biome_preset,
        }

        # Clear filepath after capturing so future invocations always open the file selector window
        self.filepath = ""

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
