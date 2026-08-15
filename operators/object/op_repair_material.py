import bpy
from ...utils.system import register_menu_item


@register_menu_item(views=["object"], label="修复/重建材质节点")
class MOZI_OT_repair_material(bpy.types.Operator):
    """Repair and reconnect LabPBR decoder and animated UV shader nodes for selected objects' materials."""

    bl_idname = "mozi.repair_material"
    bl_label = "Repair Material Nodes"
    bl_options = {"REGISTER", "UNDO"}

    force_rebuild: bpy.props.BoolProperty(
        name="Force Rebuild Node Tree",
        description="Re-instantiate shader node groups from latest template definitions",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.selected_objects)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "force_rebuild")

    def execute(self, context):
        from ...pipeline.presets import run_preset_pipeline

        params = {
            "force_rebuild": self.force_rebuild,
        }

        res, ctx = run_preset_pipeline("repair_material", context, params=params)
        for level, msg in ctx.reports:
            self.report({level}, msg)

        if not res.is_success:
            return {"CANCELLED"}

        self.report({'INFO'}, "Material nodes repaired successfully.")
        return {"FINISHED"}
