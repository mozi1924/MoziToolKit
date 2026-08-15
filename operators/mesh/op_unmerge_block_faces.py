import bpy
from ...utils.mesh import poll_mesh_object, fast_unmerge_block_quads
from ...utils.system import register_menu_item


@register_menu_item(views=["mesh", "object"])
class MOZI_OT_unmerge_block_faces(bpy.types.Operator):
    """Subdivide multi-block optimized quad faces into individual 1x1 block faces and normalize UVs."""

    bl_idname = "mozi.unmerge_block_faces"
    bl_label = "Unmerge Block Faces (Anti-Optimization)"
    bl_options = {"REGISTER", "UNDO"}

    uv_span_threshold: bpy.props.FloatProperty(
        name="UV Span Threshold",
        description="Minimum UV span to detect multi-block consolidated faces",
        default=1.05,
        min=1.001,
        max=10.0,
    )

    @classmethod
    def poll(cls, context):
        return poll_mesh_object(context)

    def execute(self, context):
        initial_mode = context.mode
        target_objs = [o for o in context.selected_objects if o.type == 'MESH' and o.data]
        if not target_objs and context.active_object and context.active_object.type == 'MESH':
            target_objs = [context.active_object]

        if not target_objs:
            self.report({'WARNING'}, "No valid mesh objects selected.")
            return {'CANCELLED'}

        if initial_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        total_large = 0
        total_sub = 0

        for obj in target_objs:
            large, sub = fast_unmerge_block_quads(obj.data, uv_span_threshold=self.uv_span_threshold)
            total_large += large
            total_sub += sub

        if initial_mode != "OBJECT":
            bpy.ops.object.mode_set(mode=initial_mode)

        if total_large == 0:
            self.report({'INFO'}, "No multi-block consolidated faces detected.")
        else:
            self.report(
                {'INFO'},
                f"Unmerged {total_large} multi-block face(s) into {total_sub} unit block quad(s)."
            )

        return {'FINISHED'}
