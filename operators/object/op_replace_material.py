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

    auto_unmerge_blocks: bpy.props.BoolProperty(
        name="Auto Unmerge Block Faces",
        description="Subdivide multi-block optimized faces into 1x1 block quads in Atlas Mode to prevent texture cross-bleeding",
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

        if self.material_mode == 'ATLAS':
            if not has_pillow():
                alert_box = layout.box()
                alert_box.alert = True
                alert_box.label(text="Atlas mode requires 'Pillow' dependency (Missing)!", icon='ERROR')
                alert_box.label(text="Please install it in Addon Preferences > Dependencies.")
                op = alert_box.operator("mozi.open_preferences", text="Install Dependencies", icon='PREFERENCES')
                op.tab = "MISC"
            else:
                # Check for jmc2obj or large UV faces on selected objects
                from ...utils.materials import is_jmc2obj_material
                has_jmc2obj = False
                for obj in context.selected_objects:
                    if obj.type == 'MESH':
                        for slot in obj.material_slots:
                            if slot.material and is_jmc2obj_material(slot.material):
                                has_jmc2obj = True
                                break
                    if has_jmc2obj:
                        break

                notice_box = layout.box()
                if has_jmc2obj:
                    notice_box.label(text="Notice: jmc2obj / Optimized Mesh Detected", icon='INFO')
                    notice_box.label(text="Atlas Mode will unmerge multi-block faces into 1x1 quads")
                    notice_box.label(text="to prevent texture cross-bleeding (Anti-optimization).")
                else:
                    notice_box.label(text="Atlas Optimization Settings", icon='MOD_SUBSURF')

                notice_box.prop(self, "auto_unmerge_blocks")

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

        from ...pipeline import get_preset_pipeline, run_pipeline_modal
        from ...pipeline.step import StepStatus

        params = {
            "zip_path": self.filepath,
            "material_mode": self.material_mode,
            "pack_textures": self.pack_textures,
            "use_cache": self.use_cache,
            "auto_unmerge_blocks": self.auto_unmerge_blocks,
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
