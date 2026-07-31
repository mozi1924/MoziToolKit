import bpy
from ...utils.mesh import poll_edit_mesh, set_select_mode
from ...utils.pixel_split import process_adaptive_pixel_split, SplitConfig


class MOZI_OT_adaptive_pixel_split(bpy.types.Operator):
    """Subdivide or adjust mesh faces to match texture pixel resolution (1 face = 1 pixel)"""

    bl_idname = "mozi.adaptive_pixel_split"
    bl_label = "Adaptive Pixel Split"
    bl_options = {"REGISTER", "UNDO"}

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

    dissolve_pre_split: bpy.props.BoolProperty(
        name="Dissolve Pre-Split Edges",
        description="Dissolve coplanar inner split edges before re-subdividing",
        default=True,
    )

    only_selected: bpy.props.BoolProperty(
        name="Only Selected Faces",
        description="Only process currently selected mesh faces",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return poll_edit_mesh(context)

    def execute(self, context):
        set_select_mode(context, "FACE")

        config = SplitConfig(
            auto_resolution=self.auto_resolution,
            manual_resolution=(self.resolution_width, self.resolution_height),
            pixels_per_face=self.pixels_per_face,
            dissolve_pre_split=self.dissolve_pre_split,
            only_selected=self.only_selected,
        )

        stats = process_adaptive_pixel_split(context, config)

        self.report(
            {"INFO"},
            f"Adaptive Pixel Split: {stats['initial_faces']} face(s) -> {stats['final_faces']} face(s)",
        )
        return {"FINISHED"}
