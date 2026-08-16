import bmesh
import bpy

try:
    from ...utils.system import register_menu_item
    from ...utils.mesh import poll_edit_mesh
    from ...utils.extrude_repair import repair_extruded_side_faces
except (ImportError, ValueError):
    from utils.system import register_menu_item
    from utils.mesh import poll_edit_mesh
    from utils.extrude_repair import repair_extruded_side_faces

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
_pending_repairs = set()
_idle_ticks = 0
_MAX_IDLE_TICKS = 3


def _is_uv_editing_active(context) -> bool:
    """Return True if the user is in or interacting with UV editing / Image Editor."""
    if not context:
        return False

    # Check current area
    area = getattr(context, "area", None)
    if area and area.type == "IMAGE_EDITOR":
        return True

    # Check space_data
    space_data = getattr(context, "space_data", None)
    if space_data and getattr(space_data, "type", None) == "IMAGE_EDITOR":
        return True

    # Check modal operators for any UV / 2D image operations
    window = getattr(context, "window", None)
    if window:
        for op in getattr(window, "modal_operators", []):
            identifier = getattr(op, "bl_idname", "")
            if not identifier:
                bl_rna = getattr(op, "bl_rna", None)
                identifier = getattr(bl_rna, "identifier", "")
            identifier_upper = identifier.upper()
            if (
                identifier_upper.startswith("UV_OT_")
                or identifier_upper.startswith("IMAGE_OT_")
                or identifier_upper.startswith("CLIP_OT_")
                or identifier_upper.startswith("NODE_OT_")
            ):
                return True

    return False


def _is_extrude_operator_identifier(identifier: str) -> bool:
    """Return True if the operator identifier corresponds to a mesh face extrusion operation."""
    if not identifier:
        return False
    id_upper = identifier.upper()
    return (
        id_upper.startswith("MESH_OT_EXTRUDE")
        or id_upper.startswith("MESH_OT_DUPLI_EXTRUDE")
        or id_upper.startswith("MESH_OT_POLYBUILD_EXTRUDE")
        or "EXTRUDE" in id_upper
    )


def _is_extrude_in_progress(context) -> bool:
    """
    Return True only if an extrusion operator or an extrusion-related modal transform
    is actively running in the 3D Viewport.
    """
    if _is_uv_editing_active(context):
        return False

    window = getattr(context, "window", None)
    window_manager = getattr(context, "window_manager", None)
    if not window or not window_manager:
        return False

    modal_ops = getattr(window, "modal_operators", [])
    if not modal_ops:
        return False

    has_modal_extrude = False
    has_modal_transform = False

    for op in modal_ops:
        identifier = getattr(op, "bl_idname", "")
        if not identifier:
            bl_rna = getattr(op, "bl_rna", None)
            identifier = getattr(bl_rna, "identifier", "")
        if _is_extrude_operator_identifier(identifier):
            has_modal_extrude = True
            break
        if identifier.upper().startswith("TRANSFORM_OT_"):
            has_modal_transform = True

    if has_modal_extrude:
        return True

    # If there is an active modal transform, check if it was triggered by an extrusion operator
    if has_modal_transform:
        recent_ops = getattr(window_manager, "operators", [])
        if recent_ops:
            for op in list(recent_ops)[-3:]:
                identifier = getattr(op, "bl_idname", "")
                if not identifier:
                    bl_rna = getattr(op, "bl_rna", None)
                    identifier = getattr(bl_rna, "identifier", "")
                if _is_extrude_operator_identifier(identifier):
                    return True

    return False


def _has_recent_extrude_operator(context) -> bool:
    """Return True if the most recent executed operator was an extrusion."""
    window_manager = getattr(context, "window_manager", None)
    if not window_manager:
        return False
    recent_ops = getattr(window_manager, "operators", [])
    if recent_ops:
        for op in list(recent_ops)[-2:]:
            identifier = getattr(op, "bl_idname", "")
            if not identifier:
                bl_rna = getattr(op, "bl_rna", None)
                identifier = getattr(bl_rna, "identifier", "")
            if _is_extrude_operator_identifier(identifier):
                return True
    return False


def _deferred_extrude_repair_tick():
    """
    Safely executes auto extrude repair in Blender's main event loop (outside depsgraph evaluation).
    Polls while a modal extrusion/transform is active, and returns None to sleep when idle.
    """
    global _is_updating, _pending_repairs, _smart_extrude_sessions, _idle_ticks

    if _is_updating:
        return _SMART_EXTRUDE_POLL_INTERVAL

    context = bpy.context
    if not context or context.mode != "EDIT_MESH" or _is_uv_editing_active(context):
        _pending_repairs.clear()
        _smart_extrude_sessions.clear()
        _idle_ticks = 0
        return None

    props = getattr(context.scene, "mozi_auto_extrude_repair", None)
    if not props or not props.enabled or not (props.repair_uv or props.add_mean_crease):
        _pending_repairs.clear()
        _smart_extrude_sessions.clear()
        _idle_ticks = 0
        return None

    obj = context.active_object
    if not obj or obj.type != "MESH":
        _pending_repairs.clear()
        _smart_extrude_sessions.clear()
        _idle_ticks = 0
        return None

    repaired_count = 0
    try:
        _is_updating = True
        bm = bmesh.from_edit_mesh(obj.data)
        if props.uv_mode == "SMART":
            session = _smart_extrude_sessions.setdefault(
                obj.as_pointer(), {"side_face_indices": set()}
            )
            repaired_count = repair_extruded_side_faces(
                bm,
                obj=obj,
                context=context,
                repair_uv=props.repair_uv,
                add_crease=props.add_mean_crease,
                crease_val=props.crease_value,
                only_collapsed=True,
                uv_mode="SMART",
                smart_side_face_indices=session["side_face_indices"],
            )
        else:
            repaired_count = repair_extruded_side_faces(
                bm,
                obj=obj,
                context=context,
                repair_uv=props.repair_uv,
                add_crease=props.add_mean_crease,
                crease_val=props.crease_value,
                only_collapsed=True,
                uv_mode=props.uv_mode,
            )
        if repaired_count > 0:
            bmesh.update_edit_mesh(obj.data)
    except Exception as e:
        import sys
        print(f"[MoziToolKit Exception] Error in auto extrude repair tick: {e}", file=sys.stderr)
    finally:
        _is_updating = False

    _pending_repairs.discard(obj.as_pointer())

    if repaired_count > 0:
        _idle_ticks = 0
    else:
        _idle_ticks += 1

    # Keep polling only while an extrusion is actively in progress in 3D view
    if _is_extrude_in_progress(context) and _idle_ticks < _MAX_IDLE_TICKS:
        return _SMART_EXTRUDE_POLL_INTERVAL

    # Finished and idle: clean up and return None to automatically stop the timer
    _smart_extrude_sessions.clear()
    _pending_repairs.clear()
    _idle_ticks = 0
    return None


@bpy.app.handlers.persistent
def depsgraph_auto_extrude_repair_handler(scene, depsgraph):
    """
    Lightweight depsgraph listener: marks dirty objects and schedules deferred main-thread execution.
    Never modifies mesh data directly within depsgraph_update_post to prevent re-evaluation cascades.
    Guards against non-3D / UV editor updates to avoid interfering with UV transforms.
    """
    if _is_updating:
        return
    try:
        context = bpy.context
        if not context or context.mode != "EDIT_MESH":
            return

        # Do not run if active in UV Editor / Image Editor
        if _is_uv_editing_active(context):
            return

        props = getattr(scene, "mozi_auto_extrude_repair", None)
        if not props or not props.enabled or not (props.repair_uv or props.add_mean_crease):
            return

        obj = context.active_object
        if not obj or obj.type != "MESH":
            return

        # Check if an extrusion is actively in progress or recently executed
        if not (_is_extrude_in_progress(context) or _has_recent_extrude_operator(context)):
            return

        # Check if geometry was updated
        geo_updated = False
        for update in depsgraph.updates:
            if update.is_updated_geometry:
                geo_updated = True
                break

        if geo_updated or not depsgraph.updates:
            _pending_repairs.add(obj.as_pointer())
            if not bpy.app.timers.is_registered(_deferred_extrude_repair_tick):
                bpy.app.timers.register(_deferred_extrude_repair_tick, first_interval=0.001, persistent=True)
    except Exception as e:
        import sys
        print(f"[MoziToolKit Exception] Error in depsgraph_auto_extrude_repair_handler: {e}", file=sys.stderr)


def register():
    bpy.types.Scene.mozi_auto_extrude_repair = bpy.props.PointerProperty(
        type=MOZI_PG_auto_extrude_repair
    )
    if depsgraph_auto_extrude_repair_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(depsgraph_auto_extrude_repair_handler)


def unregister():
    global _idle_ticks
    if depsgraph_auto_extrude_repair_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(depsgraph_auto_extrude_repair_handler)
    if bpy.app.timers.is_registered(_deferred_extrude_repair_tick):
        bpy.app.timers.unregister(_deferred_extrude_repair_tick)
    _smart_extrude_sessions.clear()
    _pending_repairs.clear()
    _idle_ticks = 0
    if hasattr(bpy.types.Scene, "mozi_auto_extrude_repair"):
        del bpy.types.Scene.mozi_auto_extrude_repair

