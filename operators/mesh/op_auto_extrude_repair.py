import bmesh
import bpy

from ...utils.menu_config import register_menu_item
from ...utils.mesh import poll_edit_mesh
from ...utils.extrude_repair import repair_extruded_side_faces

_smart_extrude_sessions = {}
_SMART_EXTRUDE_POLL_INTERVAL = 0.03


UV_MODE_ITEMS = [
    ("SMART", "Smart", "Auto-detect inward or outward mode based on extrude direction"),
    ("INWARD", "Inward (Use Selected Face Pixel)", "Shrink side UVs into selected face pixel area (default for Minecraft)"),
    ("OUTWARD", "Outward (Use Adjacent Face Pixels)", "Map each side UV strip into its adjacent face pixel"),
]


class MOZI_PG_auto_extrude_repair(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(
        name="Auto Extrude Repair",
        description="Enable automatic extrude UV and crease repair",
        default=False,
    )
    uv_mode: bpy.props.EnumProperty(
        name="UV Correction Mode",
        description="Inward uses selected face pixels; outward uses adjacent face pixels",
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
        description="Automatically add Mean Crease to all extruded face edges to prevent rounding during subdivision",
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
        description="Inward uses selected face pixels; outward uses adjacent face pixels",
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
        description="Automatically add Mean Crease to all extruded face edges to prevent rounding during subdivision",
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

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "repair_uv")
        sub_uv = layout.column()
        sub_uv.active = self.repair_uv
        sub_uv.prop(self, "uv_mode")

        layout.separator()
        layout.prop(self, "add_mean_crease")
        sub_crease = layout.column()
        sub_crease.active = self.add_mean_crease
        sub_crease.prop(self, "crease_value")

    def execute(self, context):
        params = {
            "uv_mode": self.uv_mode,
            "repair_uv": self.repair_uv,
            "add_mean_crease": self.add_mean_crease,
            "crease_value": self.crease_value,
        }
        from ...pipeline.presets import run_preset_pipeline

        res, ctx = run_preset_pipeline("auto_extrude_repair", context, params)
        for level, msg in ctx.reports:
            self.report({level}, msg)

        if not res.is_success:
            return {"CANCELLED"}
        return {"FINISHED"}


_is_updating = False


def _is_modal_mesh_operation_active(context):
    """Return whether an extrusion or its modal transform is still running."""
    window_manager = getattr(context, "window_manager", None)
    window = getattr(context, "window", None)
    seen_ops = set()
    operators = []
    
    raw_ops = []
    if window:
        raw_ops.extend(window.modal_operators)
    active_operator = getattr(context, "active_operator", None)
    if active_operator:
        raw_ops.append(active_operator)
    if window_manager:
        raw_ops.extend(window_manager.operators)

    for op in raw_ops:
        ptr = getattr(op, "as_pointer", lambda: id(op))()
        if ptr not in seen_ops:
            seen_ops.add(ptr)
            operators.append(op)

    for operator in operators:
        identifier = getattr(operator, "bl_idname", "")
        if not identifier:
            bl_rna = getattr(operator, "bl_rna", None)
            identifier = getattr(bl_rna, "identifier", "")
        identifier = identifier.upper()
        if identifier.startswith("MESH_OT_EXTRUDE") or identifier.startswith("TRANSFORM_OT_"):
            return True
    return False


def _monitor_smart_extrusions():
    """Continuously update smart UVs until the modal extrusion ends."""
    global _is_updating

    if not _smart_extrude_sessions:
        return _SMART_EXTRUDE_POLL_INTERVAL

    context = bpy.context
    if (
        not context
        or context.mode != "EDIT_MESH"
        or not _is_modal_mesh_operation_active(context)
    ):
        _smart_extrude_sessions.clear()
        return _SMART_EXTRUDE_POLL_INTERVAL

    props = getattr(context.scene, "mozi_auto_extrude_repair", None)
    obj = context.active_object
    if (
        not props
        or not props.enabled
        or props.uv_mode != "SMART"
        or not obj
        or obj.type != "MESH"
    ):
        _smart_extrude_sessions.clear()
        return _SMART_EXTRUDE_POLL_INTERVAL

    session = _smart_extrude_sessions.get(obj.as_pointer())
    if not session or _is_updating:
        return _SMART_EXTRUDE_POLL_INTERVAL

    try:
        _is_updating = True
        bm = bmesh.from_edit_mesh(obj.data)
        count = repair_extruded_side_faces(
            bm,
            repair_uv=props.repair_uv,
            add_crease=props.add_mean_crease,
            crease_val=props.crease_value,
            only_collapsed=True,
            uv_mode="SMART",
            smart_side_face_indices=session["side_face_indices"],
        )
        if count > 0:
            bmesh.update_edit_mesh(obj.data)
    except Exception as e:
        import sys
        print(f"[MoziToolKit Exception] Error in timer _monitor_smart_extrusions: {e}", file=sys.stderr)
    finally:
        _is_updating = False

    return _SMART_EXTRUDE_POLL_INTERVAL


@bpy.app.handlers.persistent
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

        if props.uv_mode == "SMART":
            object_key = obj.as_pointer()
            session = _smart_extrude_sessions.setdefault(
                object_key, {"side_face_indices": set()}
            )
            _is_updating = True
            bm = bmesh.from_edit_mesh(obj.data)
            count = repair_extruded_side_faces(
                bm,
                repair_uv=props.repair_uv,
                add_crease=props.add_mean_crease,
                crease_val=props.crease_value,
                only_collapsed=True,
                uv_mode="SMART",
                smart_side_face_indices=session["side_face_indices"],
            )
            if count > 0:
                bmesh.update_edit_mesh(obj.data)
            return

        _is_updating = True
        bm = bmesh.from_edit_mesh(obj.data)
        count = repair_extruded_side_faces(
            bm,
            repair_uv=props.repair_uv,
            add_crease=props.add_mean_crease,
            crease_val=props.crease_value,
            only_collapsed=True,
            uv_mode=props.uv_mode,
        )

        if count > 0:
            bmesh.update_edit_mesh(obj.data)
    except Exception as e:
        import sys
        print(f"[MoziToolKit Exception] Error in depsgraph_auto_extrude_repair_handler: {e}", file=sys.stderr)
    finally:
        _is_updating = False




def register():
    bpy.types.Scene.mozi_auto_extrude_repair = bpy.props.PointerProperty(
        type=MOZI_PG_auto_extrude_repair
    )
    if depsgraph_auto_extrude_repair_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(depsgraph_auto_extrude_repair_handler)
    if not bpy.app.timers.is_registered(_monitor_smart_extrusions):
        bpy.app.timers.register(_monitor_smart_extrusions, persistent=True)


def unregister():
    if depsgraph_auto_extrude_repair_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(depsgraph_auto_extrude_repair_handler)
    if bpy.app.timers.is_registered(_monitor_smart_extrusions):
        bpy.app.timers.unregister(_monitor_smart_extrusions)
    _smart_extrude_sessions.clear()
    if hasattr(bpy.types.Scene, "mozi_auto_extrude_repair"):
        del bpy.types.Scene.mozi_auto_extrude_repair
