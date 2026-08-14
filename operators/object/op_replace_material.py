import bpy
from bpy_extras.io_utils import ImportHelper
from ...utils.menu_config import register_menu_item
from ...utils.dependencies import has_pillow


@register_menu_item(views=["object"], label="替换材质")
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
            ('STANDALONE', "独立模式 (Standalone)", "Create individual materials for each texture (Default)"),
            ('ATLAS', "Atlas 模式 (Atlas)", "Combine all textures into a single texture atlas material"),
        ],
        default='STANDALONE',
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
        self.filepath = ""
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Material Options", icon='TEXTURE')
        box.prop(self, "material_mode", text="Mode")

        if self.material_mode == 'ATLAS' and not has_pillow():
            alert_box = layout.box()
            alert_box.alert = True
            alert_box.label(text="Atlas mode requires 'Pillow' dependency (Missing)!", icon='ERROR')
            alert_box.label(text="Please install it in Addon Preferences > Dependencies.")
            op = alert_box.operator("mozi.open_preferences", text="Install Dependencies (前往安装依赖)", icon='PREFERENCES')
            op.tab = "dependencies"

        box.prop(self, "pack_textures")
        box.prop(self, "use_cache")

    def execute(self, context):
        if not self.filepath:
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}

        if self.material_mode == 'ATLAS' and not has_pillow():
            self.report(
                {'ERROR'},
                "Atlas mode requires 'Pillow' dependency. Please open Preferences > Add-ons > MoziToolKit > Dependencies to install it."
            )
            return {"CANCELLED"}

        from ...pipeline.presets import run_preset_pipeline

        params = {
            "zip_path": self.filepath,
            "material_mode": self.material_mode,
            "pack_textures": self.pack_textures,
            "use_cache": self.use_cache,
        }

        res, ctx = run_preset_pipeline("replace_material", context, params=params)
        for level, msg in ctx.reports:
            self.report({level}, msg)

        # Clear filepath after execution so future invocations always open the file selector window
        self.filepath = ""

        if not res.is_success:
            return {"CANCELLED"}

        self.report({'INFO'}, f"Material replacement finished successfully in {self.material_mode} mode.")
        return {"FINISHED"}
