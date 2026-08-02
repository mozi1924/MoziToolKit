import bmesh
import bpy

from ...utils.menu_config import register_menu_item
from ...utils.mesh import poll_edit_mesh
from ...utils.extrude_repair import repair_extruded_side_faces

_last_processed_extrude_op = None
_smart_side_faces_by_object = {}


UV_MODE_ITEMS = [
    ("SMART", "Smart", "Auto-detect inward or outward mode based on extrude direction"),
    ("INWARD", "Inward (Use Face Pixel)", "Shrink side UVs into reference face pixel area (default for Minecraft)"),
    ("OUTWARD", "Outward (Extend UVs)", "Extend side UVs outwards from reference face UV bounds"),
]


class MOZI_PG_auto_extrude_repair(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(
        name="Auto Extrude Repair",
        description="Enable automatic extrude UV and crease repair",
        default=False,
    )
    uv_mode: bpy.props.EnumProperty(
        name="UV Correction Mode",
        description="Direction for side UV extension (Inward uses reference face pixel color)",
        items=UV_MODE_ITEMS,
        default="SMART",
    )
    repair_uv: bpy.props.BoolProperty(
        name="Repair UV Overlap",
        description="Automatically fix UV overlapping on extruded side faces",
        default=True,
    )
    add_mean_crease: bpy.props.BoolProperty(
        name="Add Mean Crease",
        description="Automatically add Mean Crease to extruded side edges to prevent rounding during subdivision",
        default=False,
    )
    crease_value: bpy.props.FloatProperty(
        name="Crease Weight",
        description="Edge Mean Crease weight value (0.0 - 1.0)",
        default=1.0,
        min=0.0,
        max=1.0,
    )


@register_menu_item(views=["mesh"])
class MOZI_OT_auto_extrude_repair(bpy.types.Operator):
    """Repair UV overlapping and add Mean Crease to side faces created during face extrusion"""

    bl_idname = "mozi.auto_extrude_repair"
    bl_label = "Auto Extrude Repair"
    bl_options = {"REGISTER", "UNDO"}

    uv_mode: bpy.props.EnumProperty(
        name="UV Correction Mode",
        description="Direction for side UV extension (Inward uses reference face pixel color)",
        items=UV_MODE_ITEMS,
        default="SMART",
    )

    repair_uv: bpy.props.BoolProperty(
        name="Repair UV Overlap",
        description="Automatically fix UV overlapping on extruded side faces",
        default=True,
    )

    add_mean_crease: bpy.props.BoolProperty(
        name="Add Mean Crease",
        description="Automatically add Mean Crease to extruded side edges to prevent rounding during subdivision",
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

    def execute(self, context):
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)

        count = repair_extruded_side_faces(
            bm,
            repair_uv=self.repair_uv,
            add_crease=self.add_mean_crease,
            crease_val=self.crease_value,
            uv_mode=self.uv_mode,
        )

        if count > 0:
            bmesh.update_edit_mesh(obj.data)
            self.report({"INFO"}, f"Repaired {count} extruded side faces")
        else:
            self.report({"INFO"}, "No extruded side faces to repair")

        return {"FINISHED"}


_is_updating = False


def _is_modal_mesh_operation_active(context):
    """Return whether an extrusion or its modal transform is still running."""
    window_manager = getattr(context, "window_manager", None)
    if not window_manager:
        return False

    for operator in window_manager.operators:
        identifier = getattr(operator, "bl_idname", "")
        if not identifier:
            bl_rna = getattr(operator, "bl_rna", None)
            identifier = getattr(bl_rna, "identifier", "")
        identifier = identifier.upper()
        if "EXTRUDE" in identifier or identifier.startswith("TRANSFORM_OT_"):
            return True
    return False


def _clear_finished_smart_extrusions():
    """End smart tracking immediately after an extrusion is confirmed/cancelled."""
    if _smart_side_faces_by_object and not _is_modal_mesh_operation_active(bpy.context):
        _smart_side_faces_by_object.clear()
    return 0.1


def depsgraph_auto_extrude_repair_handler(scene, depsgraph):
    global _is_updating
    if _is_updating:
        return
    try:
        context = bpy.context
        if not context or context.mode != "EDIT_MESH":
            return

        props = getattr(scene, "mozi_auto_extrude_repair", None)
        if not props or not props.enabled:
            return

        if not (props.repair_uv or props.add_mean_crease):
            return

        obj = context.active_object
        if not obj or obj.type != "MESH":
            return

        _is_updating = True
        bm = bmesh.from_edit_mesh(obj.data)
        smart_side_face_indices = None
        if props.uv_mode == "SMART":
            object_key = obj.as_pointer()
            smart_side_face_indices = _smart_side_faces_by_object.setdefault(object_key, set())
        count = repair_extruded_side_faces(
            bm,
            repair_uv=props.repair_uv,
            add_crease=props.add_mean_crease,
            crease_val=props.crease_value,
            only_collapsed=True,
            uv_mode=props.uv_mode,
            smart_side_face_indices=smart_side_face_indices,
        )

        if count > 0:
            bmesh.update_edit_mesh(obj.data)
    except Exception:
        pass
    finally:
        _is_updating = False




def register():
    bpy.types.Scene.mozi_auto_extrude_repair = bpy.props.PointerProperty(
        type=MOZI_PG_auto_extrude_repair
    )
    if depsgraph_auto_extrude_repair_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(depsgraph_auto_extrude_repair_handler)
    if not bpy.app.timers.is_registered(_clear_finished_smart_extrusions):
        bpy.app.timers.register(_clear_finished_smart_extrusions, persistent=True)


def unregister():
    if depsgraph_auto_extrude_repair_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(depsgraph_auto_extrude_repair_handler)
    if bpy.app.timers.is_registered(_clear_finished_smart_extrusions):
        bpy.app.timers.unregister(_clear_finished_smart_extrusions)
    _smart_side_faces_by_object.clear()
    if hasattr(bpy.types.Scene, "mozi_auto_extrude_repair"):
        del bpy.types.Scene.mozi_auto_extrude_repair
