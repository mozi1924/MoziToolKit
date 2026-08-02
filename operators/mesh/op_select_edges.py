import math
import bpy
from ...utils.mesh import bmesh_context, poll_edit_mesh, set_select_mode, is_hard_edge
from ...utils.menu_config import register_menu_item


@register_menu_item(views=["mesh"])
class MOZI_OT_select_hard_edges(bpy.types.Operator):
    """Select boundary edges, sharp marked edges, and edges exceeding sharp angle threshold"""

    bl_idname = "mozi.select_hard_edges"
    bl_label = "Select Hard & Sharp Edges"
    bl_options = {"REGISTER", "UNDO"}

    sharp_angle: bpy.props.FloatProperty(
        name="Sharp Angle",
        description="Angle threshold in degrees to treat as sharp edge",
        default=30.0,
        min=0.0,
        max=180.0,
        precision=1,
        subtype="ANGLE",
    )

    @classmethod
    def poll(cls, context):
        return poll_edit_mesh(context)

    def execute(self, context):
        set_select_mode(context, "EDGE")

        with bmesh_context(context) as (obj, bm):
            sharp_angle_rad = math.radians(self.sharp_angle)

            for edge in bm.edges:
                edge.select = is_hard_edge(edge, sharp_angle_rad)

        return {"FINISHED"}
