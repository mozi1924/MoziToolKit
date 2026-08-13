import bpy
from bpy_extras.io_utils import ImportHelper
from ...utils.menu_config import register_menu_item


@register_menu_item(views=["object"], label="替换材质")
class MOZI_OT_replace_material(bpy.types.Operator, ImportHelper):
    """Replace selected objects' materials using a Minecraft Java Edition Resource Pack (ZIP)"""

    bl_idname = "mozi.replace_material"
    bl_label = "Replace Material"
    bl_options = {"REGISTER", "UNDO"}

    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Path to Minecraft Java Edition Resource Pack ZIP",
        subtype='FILE_PATH',
    )

    filename_ext = ".zip"
    filter_glob: bpy.props.StringProperty(
        default="*.zip;*.jar",
        options={'HIDDEN'},
        maxlen=255,
    )


    pack_textures: bpy.props.BoolProperty(
        name="Pack Textures into Blend File",
        description="Embed imported textures directly into the Blender project file (.blend)",
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
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Material Options", icon='TEXTURE')
        box.prop(self, "pack_textures")
        box.prop(self, "use_cache")

    def execute(self, context):
        if not self.filepath:
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}

        from ...pipeline.presets import run_preset_pipeline


        params = {
            "zip_path": self.filepath,
            "pack_textures": self.pack_textures,
            "use_cache": self.use_cache,
        }

        res, ctx = run_preset_pipeline("replace_material", context, params=params)
        for level, msg in ctx.reports:
            self.report({level}, msg)

        if not res.is_success:
            return {"CANCELLED"}

        self.report({'INFO'}, "Material replacement finished successfully.")
        return {"FINISHED"}
