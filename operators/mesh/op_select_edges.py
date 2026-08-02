import math
import bpy
from ...utils.mesh import bmesh_context, poll_edit_mesh, set_select_mode
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
            # Deselect all edges
            for edge in bm.edges:
                edge.select = False

            sharp_angle_rad = math.radians(self.sharp_angle)

            for edge in bm.edges:
                if edge.is_boundary or not edge.smooth:
                    edge.select = True
                elif len(edge.link_faces) == 2 and edge.calc_face_angle(0) > sharp_angle_rad:
                    edge.select = True

        return {"FINISHED"}
