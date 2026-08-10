import bpy
from ...utils.menu_config import register_menu_item
from ...utils.mesh import poll_edit_mesh
from .op_auto_extrude_repair import UV_MODE_ITEMS

NOISE_MODE_ITEMS = [
    ("RANDOM", "Random (Seed)", "Uniform pseudo-random numbers based on seed"),
    ("PERLIN", "Perlin Noise", "Continuous 3D Perlin noise based on face position"),
    ("CELL", "Cell Noise", "3D Cell/Block noise based on face position"),
]


@register_menu_item(views=["mesh"])
class MOZI_OT_random_extrude(bpy.types.Operator):
    """Extrude selected faces individually along normals with random heights and UV repair"""

    bl_idname = "mozi.random_extrude"
    bl_label = "Random Extrude"
    bl_options = {"REGISTER", "UNDO"}

    min_height: bpy.props.FloatProperty(
        name="Min Extrude Height",
        description="Minimum extrusion distance along face normal",
        default=0.0,
        step=1,
        precision=3,
    )

    max_height: bpy.props.FloatProperty(
        name="Max Extrude Height",
        description="Maximum extrusion distance along face normal",
        default=0.01,
        step=1,
        precision=3,
    )

    seed: bpy.props.IntProperty(
        name="Random Seed",
        description="Random seed for extrude height generator",
        default=0,
        min=0,
        max=100000,
    )

    noise_mode: bpy.props.EnumProperty(
        name="Noise Generator",
        description="Function used to generate random heights",
        items=NOISE_MODE_ITEMS,
        default="RANDOM",
    )

    noise_scale: bpy.props.FloatProperty(
        name="Noise Scale",
        description="Frequency scale for 3D Perlin/Cell noise",
        default=1.0,
        min=0.01,
        max=100.0,
    )

    repair_uv: bpy.props.BoolProperty(
        name="Repair UV Overlap",
        description="Automatically fix UV overlapping on extruded side faces",
        default=True,
    )

    uv_mode: bpy.props.EnumProperty(
        name="UV Correction Mode",
        description="Inward uses selected face pixels; outward uses adjacent face pixels",
        items=UV_MODE_ITEMS,
        default="SMART",
    )

    add_mean_crease: bpy.props.BoolProperty(
        name="Add Mean Crease",
        description="Automatically add Mean Crease to extruded face edges",
        default=False,
    )

    crease_value: bpy.props.FloatProperty(
        name="Crease Weight",
        description="Edge Mean Crease weight value (0.0 - 1.0)",
        default=1.0,
        min=0.0,
        max=1.0,
    )

    @classmethod
    def poll(cls, context):
        return poll_edit_mesh(context)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        layout = self.layout

        box_ext = layout.box()
        box_ext.label(text="Random Extrude Options", icon="MOD_DISPLACE")
        box_ext.prop(self, "min_height")
        box_ext.prop(self, "max_height")
        box_ext.prop(self, "seed")
        box_ext.prop(self, "noise_mode")
        if self.noise_mode in ("PERLIN", "CELL"):
            box_ext.prop(self, "noise_scale")

        box_uv = layout.box()
        box_uv.label(text="UV & Crease Options", icon="UV_DATA")
        box_uv.prop(self, "repair_uv")
        sub_uv = box_uv.column()
        sub_uv.active = self.repair_uv
        sub_uv.prop(self, "uv_mode")

        box_uv.separator()
        box_uv.prop(self, "add_mean_crease")
        sub_crease = box_uv.column()
        sub_crease.active = self.add_mean_crease
        sub_crease.prop(self, "crease_value")

    def execute(self, context):
        params = {
            "min_height": self.min_height,
            "max_height": self.max_height,
            "seed": self.seed,
            "noise_mode": self.noise_mode,
            "noise_scale": self.noise_scale,
            "repair_uv": self.repair_uv,
            "uv_mode": self.uv_mode,
            "add_mean_crease": self.add_mean_crease,
            "crease_value": self.crease_value,
        }
        from ...pipeline.presets import run_preset_pipeline

        res, ctx = run_preset_pipeline("random_extrude", context, params)
        for level, msg in ctx.reports:
            self.report({level}, msg)

        if not res.is_success:
            return {"CANCELLED"}
        return {"FINISHED"}
