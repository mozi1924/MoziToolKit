import bpy
from ...utils.mesh import bmesh_context, poll_edit_mesh, get_face_uv_center
from ...utils.system import register_menu_item


@register_menu_item(views=["uv"])
class MOZI_OT_scale_uv(bpy.types.Operator):
    """Scale individual UV faces in place"""

    bl_idname = "mozi.scale_uv"
    bl_label = "Scale UV Faces"
    bl_options = {"REGISTER", "UNDO"}

    scale_factor: bpy.props.FloatProperty(
        name="Scale Factor",
        description="Scale factor for UV faces",
        default=0.8,
        min=0.0,
        max=10.0,
        precision=3,
    )

    selection_scope: bpy.props.EnumProperty(
        name="Selection Scope",
        description="Faces to scale UV on",
        items=[
            ("AUTO", "Auto (Selected / All)", "Scale selected faces if any, otherwise scale all faces"),
            ("SELECTED", "Selected Faces", "Only scale currently selected faces"),
            ("ALL", "All Faces", "Scale all faces regardless of selection"),
        ],
        default="AUTO",
    )

    @classmethod
    def poll(cls, context):
        return poll_edit_mesh(context)

    def execute(self, context):
        params = {
            "scale_factor": self.scale_factor,
            "selection_scope": self.selection_scope,
        }
        from ...pipeline.presets import run_preset_pipeline

        res, ctx = run_preset_pipeline("scale_uv", context, params)
        for level, msg in ctx.reports:
            self.report({level}, msg)

        if not res.is_success:
            return {"CANCELLED"}
        return {"FINISHED"}
