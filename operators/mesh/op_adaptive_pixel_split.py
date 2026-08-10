import bpy
from ...utils.mesh import SELECTION_SCOPE_ITEMS, poll_mesh_object, set_select_mode
from ...utils.pixel_split import SplitConfig, process_adaptive_pixel_split
from ...utils.menu_config import register_menu_item


@register_menu_item(views=["mesh", "object", "uv"])
class MOZI_OT_adaptive_pixel_split(bpy.types.Operator):
    """Subdivide or adjust mesh faces to match texture pixel resolution (1 face = 1 pixel)"""

    bl_idname = "mozi.adaptive_pixel_split"
    bl_label = "Adaptive Pixel Split"
    bl_options = {"REGISTER", "UNDO"}

    selection_scope: bpy.props.EnumProperty(
        name="Selection Scope",
        description="Filter which faces to process (All, Selected, or Connected Mesh)",
        items=SELECTION_SCOPE_ITEMS,
        default="SELECTED",
    )

    auto_resolution: bpy.props.BoolProperty(
        name="Auto Resolution",
        description="Automatically detect texture resolution from face material",
        default=True,
    )

    resolution_width: bpy.props.IntProperty(
        name="Resolution Width",
        description="Texture width override when Auto Resolution is disabled",
        default=64,
        min=1,
        max=8192,
    )

    resolution_height: bpy.props.IntProperty(
        name="Resolution Height",
        description="Texture height override when Auto Resolution is disabled",
        default=64,
        min=1,
        max=8192,
    )

    pixels_per_face: bpy.props.IntProperty(
        name="Pixels Per Face",
        description="Number of pixels mapped to each 3D face grid cell",
        default=1,
        min=1,
        max=64,
    )

    @classmethod
    def poll(cls, context):
        return poll_mesh_object(context)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        layout = self.layout

        box = layout.box()
        box.label(text="Weight Preservation Active", icon="CHECKMARK")
        box.label(text="Subdivided vertices auto-inherit bone weights.")

        layout.prop(self, "selection_scope")
        layout.prop(self, "auto_resolution")
        if not self.auto_resolution:
            row = layout.row(align=True)
            row.prop(self, "resolution_width")
            row.prop(self, "resolution_height")

        layout.prop(self, "pixels_per_face")

    def execute(self, context):
        params = {
            "selection_scope": self.selection_scope,
            "auto_resolution": self.auto_resolution,
            "resolution_width": self.resolution_width,
            "resolution_height": self.resolution_height,
            "pixels_per_face": self.pixels_per_face,
        }
        from ...pipeline.presets import run_preset_pipeline

        res, ctx = run_preset_pipeline("adaptive_pixel_split", context, params)
        for level, msg in ctx.reports:
            self.report({level}, msg)

        if not res.is_success:
            return {"CANCELLED"}
        return {"FINISHED"}


