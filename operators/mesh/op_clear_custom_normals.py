import bpy
from ...utils.menu_config import register_menu_item


@register_menu_item(views=["mesh", "object"])
class MOZI_OT_clear_custom_normals(bpy.types.Operator):
    """Delete custom_normal attribute and clear custom split normals for selected mesh objects"""

    bl_idname = "mozi.clear_custom_normals"
    bl_label = "Clear Custom Normals"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode in ("OBJECT", "EDIT_MESH") and any(
            o.type == "MESH" for o in context.selected_objects
        )

    def execute(self, context):
        selected_mesh_objs = [o for o in context.selected_objects if o.type == "MESH"]
        if not selected_mesh_objs:
            self.report({"WARNING"}, "No mesh objects selected")
            return {"CANCELLED"}

        saved_mode = context.mode
        saved_active = context.view_layer.objects.active

        if saved_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        cleared_count = 0

        try:
            for obj in selected_mesh_objs:
                mesh = obj.data
                had_custom = False

                # 1. Remove attributes matching custom_normal
                attrs_to_remove = [
                    attr
                    for attr in mesh.attributes
                    if "custom_normal" in attr.name.lower()
                    or "custom normal" in attr.name.lower()
                    or attr.name.lower().replace("_", "").replace(" ", "") == "customnormal"
                ]
                for attr in attrs_to_remove:
                    mesh.attributes.remove(attr)
                    had_custom = True

                # 2. Clear custom split normals data if still present
                if mesh.has_custom_normals:
                    context.view_layer.objects.active = obj
                    bpy.ops.mesh.customdata_custom_splitnormals_clear()
                    had_custom = True

                if had_custom:
                    cleared_count += 1
        finally:
            # Restore active object and mode safely
            if saved_active and saved_active in context.view_layer.objects.values():
                context.view_layer.objects.active = saved_active

            if saved_mode != "OBJECT":
                mode_to_set = "EDIT" if saved_mode == "EDIT_MESH" else saved_mode
                try:
                    bpy.ops.object.mode_set(mode=mode_to_set)
                except Exception:
                    pass

        if cleared_count == 0:
            self.report({"INFO"}, "No custom normals found on selected objects")
        else:
            self.report(
                {"INFO"},
                f"Cleared custom normals from {cleared_count} object(s)",
            )

        return {"FINISHED"}
