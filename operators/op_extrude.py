"""
Auto Extrude UV Repair and Random Extrude Operators for MoziToolKit.

Supports:
1. Real-time background live extrusion repair via depsgraph handlers & timers.
2. Manual post-extrusion repair operator on selected/all faces.
3. Random terrain extrusion with automatic integrated UV repair & edge creases.
All geometric UV calculations and noise generation are accelerated strictly by Rust libmtk.
"""

from __future__ import annotations

import logging
import math
from typing import Dict, Optional, Set

try:
    import bmesh
    import bpy
    import mathutils
    from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty
except ImportError:
    bmesh = None
    bpy = None
    mathutils = None
    BoolProperty = EnumProperty = FloatProperty = IntProperty = PointerProperty = lambda *args, **kwargs: None

if bpy is None:
    class _DummyBpyTypes:
        PropertyGroup = object
        Operator = object
        Panel = object
        Menu = object
    class _DummyBpyApp:
        class handlers:
            depsgraph_update_post = []
            persistent = staticmethod(lambda f: f)
        class timers:
            @staticmethod
            def is_registered(func): return False
            @staticmethod
            def register(func, **kwargs): pass
            @staticmethod
            def unregister(func): pass
    class _DummyBpy:
        types = _DummyBpyTypes
        app = _DummyBpyApp
        context = None
    bpy = _DummyBpy()

try:
    from ..bridge.extrude import generate_random_extrude_heights, repair_extruded_side_uv
    from ..bridge.uv import get_uv_bounds, is_uv_collapsed
    from ..utils.mesh.core import (
        bmesh_context,
        poll_edit_mesh,
    )
    from ..utils.mesh.random_extrude import process_random_extrude
    from ..utils.extrude_repair import repair_extruded_side_faces
    from ..utils.system.menu_registry import register_menu_item
except (ImportError, ValueError):
    from bridge.extrude import generate_random_extrude_heights, repair_extruded_side_uv
    from bridge.uv import get_uv_bounds, is_uv_collapsed
    from utils.mesh.core import (
        bmesh_context,
        poll_edit_mesh,
    )
    from utils.mesh.random_extrude import process_random_extrude
    from utils.extrude_repair import repair_extruded_side_faces
    from utils.system.menu_registry import register_menu_item

logger = logging.getLogger("MoziToolKit.AutoExtrudeRepair")

_smart_extrude_sessions: Dict[int, Dict[str, Set[int]]] = {}
_pending_repairs: Set[int] = set()
_is_updating: bool = False
_idle_ticks: int = 0
_SMART_EXTRUDE_POLL_INTERVAL = 0.03
_MAX_IDLE_TICKS = 5

UV_MODE_ITEMS = [
    ("SMART", "Smart (Automatic)", "Auto-detect outward protrusion vs inward indentation"),
    ("INWARD", "Inward (Block)", "Sample from top face edge towards the interior (Minecraft block standard)"),
    ("OUTWARD", "Outward (Terrain)", "Sample from adjacent base face outward into continuous terrain"),
]

NOISE_TYPE_ITEMS = [
    ("RANDOM", "Random (Seed)", "Independent uniform pseudo-random numbers based on seed"),
    ("PERLIN", "3D Perlin Noise", "Continuous 3D gradient noise based on face world coordinates"),
    ("CELL", "Cell Noise", "3D Voronoi / block noise based on face world coordinates"),
]


class MOZI_PG_auto_extrude_repair(bpy.types.PropertyGroup):
    enabled: BoolProperty(
        name="Auto Extrude Repair",
        description="Enable real-time background extrusion UV and crease repair",
        default=False,
    )
    uv_mode: EnumProperty(
        name="UV Correction Mode",
        description="Inward uses selected face pixels; outward uses adjacent face pixels",
        items=UV_MODE_ITEMS,
        default="SMART",
    )
    repair_uv: BoolProperty(
        name="Repair UV Overlap",
        description="Automatically fix UV overlapping on extruded side faces",
        default=True,
    )
    add_mean_crease: BoolProperty(
        name="Add Mean Crease",
        description="Automatically add Mean Crease to extruded edges to prevent rounding during subdivision",
        default=False,
    )
    crease_value: FloatProperty(
        name="Crease Weight",
        description="Edge Mean Crease weight value (0.0 - 1.0)",
        default=1.0,
        min=0.0,
        max=1.0,
    )



# =========================================================================
# Real-time Background Polling & Depsgraph Listener
# =========================================================================

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
    if not window:
        return False

    modal_ops = getattr(window, "modal_operators", [])
    if not modal_ops:
        return False

    for op in modal_ops:
        identifier = getattr(op, "bl_idname", "")
        if not identifier:
            bl_rna = getattr(op, "bl_rna", None)
            identifier = getattr(bl_rna, "identifier", "")
        id_upper = identifier.upper()
        if _is_extrude_operator_identifier(id_upper) or id_upper.startswith("TRANSFORM_OT_"):
            return True

    return False


def _has_recent_extrude_operator(context) -> bool:
    """Return True if the most recent executed operator was an extrusion."""
    window_manager = getattr(context, "window_manager", None)
    if not window_manager:
        return False
    recent_ops = getattr(window_manager, "operators", [])
    if recent_ops:
        for op in list(recent_ops)[-5:]:
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
        logger.error(f"Error in auto extrude repair tick: {e}", exc_info=True)
    finally:
        _is_updating = False

    _pending_repairs.discard(obj.as_pointer())

    # Keep polling continuously while extrusion/transform is in progress
    if _is_extrude_in_progress(context):
        _idle_ticks = 0
        return _SMART_EXTRUDE_POLL_INTERVAL
    elif _idle_ticks < _MAX_IDLE_TICKS:
        _idle_ticks += 1
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
        logger.error(f"Error in depsgraph_auto_extrude_repair_handler: {e}", exc_info=True)


# =========================================================================
# Operator Implementations
# =========================================================================

@register_menu_item(views=["mesh"], label="Auto Extrude Repair")
class MOZI_OT_auto_extrude_repair(bpy.types.Operator):
    """Repair UV overlapping and add Mean Crease to side faces created during face extrusion"""

    bl_idname = "mozi.auto_extrude_repair"
    bl_label = "Auto Extrude Repair"
    bl_options = {"REGISTER", "UNDO"}

    uv_mode: EnumProperty(
        name="UV Correction Mode",
        description="Algorithm used for reconstructing extruded side UVs",
        items=UV_MODE_ITEMS,
        default="SMART",
    )

    repair_uv: BoolProperty(
        name="Repair UV Overlap",
        description="Automatically fix UV overlapping on extruded side faces",
        default=True,
    )

    add_mean_crease: BoolProperty(
        name="Add Mean Crease",
        description="Automatically add Mean Crease to all extruded face edges",
        default=False,
    )

    crease_value: FloatProperty(
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
        repaired_count = 0
        with bmesh_context(context, auto_update=True, flush_selection=True) as (obj, bm):
            repaired_count = repair_extruded_side_faces(
                bm,
                obj=obj,
                context=context,
                repair_uv=self.repair_uv,
                add_crease=self.add_mean_crease,
                crease_val=self.crease_value,
                only_collapsed=True,
                uv_mode=self.uv_mode,
            )

        self.report({"INFO"}, f"Auto Extrude Repair: Repaired {repaired_count} side face(s).")
        return {"FINISHED"}


@register_menu_item(views=["mesh"], label="Random Extrude")
class MOZI_OT_random_extrude(bpy.types.Operator):
    """Extrude selected faces individually along normals with random heights and automatic UV repair"""

    bl_idname = "mozi.random_extrude"
    bl_label = "Random Extrude"
    bl_options = {"REGISTER", "UNDO"}

    min_height: FloatProperty(
        name="Min Extrude Height",
        description="Minimum extrusion distance along face normal",
        default=0.0,
        step=1,
        precision=3,
        unit="LENGTH",
    )

    max_height: FloatProperty(
        name="Max Extrude Height",
        description="Maximum extrusion distance along face normal",
        default=0.1,
        step=1,
        precision=3,
        unit="LENGTH",
    )

    seed: IntProperty(
        name="Random Seed",
        description="Random seed for extrude height generator",
        default=0,
        min=0,
        max=100000,
    )

    noise_mode: EnumProperty(
        name="Noise Generator",
        description="Function used to generate random heights",
        items=NOISE_TYPE_ITEMS,
        default="RANDOM",
    )

    noise_scale: FloatProperty(
        name="Noise Scale",
        description="Frequency scale for 3D continuous noise",
        default=1.0,
        min=0.01,
        max=100.0,
    )

    repair_uv: BoolProperty(
        name="Repair UV Overlap",
        description="Automatically fix UV overlapping on extruded side faces",
        default=True,
    )

    uv_mode: EnumProperty(
        name="UV Correction Mode",
        description="Inward uses selected face pixels; outward uses adjacent face pixels",
        items=UV_MODE_ITEMS,
        default="SMART",
    )

    add_mean_crease: BoolProperty(
        name="Add Mean Crease",
        description="Automatically add Mean Crease to extruded face edges",
        default=False,
    )

    crease_value: FloatProperty(
        name="Crease Weight",
        description="Edge Mean Crease weight value (0.0 - 1.0)",
        default=1.0,
        min=0.0,
        max=1.0,
    )

    @classmethod
    def poll(cls, context):
        return poll_edit_mesh(context)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        layout = self.layout
        box_ext = layout.box()
        box_ext.label(text="Random Extrude Options", icon="MOD_DISPLACE")
        box_ext.prop(self, "min_height")
        box_ext.prop(self, "max_height")
        box_ext.prop(self, "seed")
        box_ext.prop(self, "noise_mode")
        if self.noise_mode in ("PERLIN", "CELL"):
            box_ext.prop(self, "noise_scale")

        box_uv = layout.box()
        box_uv.label(text="UV & Crease Options", icon="UV_DATA")
        box_uv.prop(self, "repair_uv")
        sub_uv = box_uv.column()
        sub_uv.active = self.repair_uv
        sub_uv.prop(self, "uv_mode")

        box_uv.separator()
        box_uv.prop(self, "add_mean_crease")
        sub_crease = box_uv.column()
        sub_crease.active = self.add_mean_crease
        sub_crease.prop(self, "crease_value")

    def execute(self, context):
        with bmesh_context(context, auto_update=True, flush_selection=True) as (obj, bm):
            extruded_count, repaired_count = process_random_extrude(
                bm=bm,
                min_height=self.min_height,
                max_height=self.max_height,
                seed=self.seed,
                noise_mode=self.noise_mode,
                noise_scale=self.noise_scale,
                repair_uv=self.repair_uv,
                uv_mode=self.uv_mode,
                add_crease=self.add_mean_crease,
                crease_val=self.crease_value,
                obj=obj,
                context=context,
            )

        if extruded_count == 0:
            self.report({"WARNING"}, "No faces selected or extruded.")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Randomly extruded {extruded_count} face(s); repaired {repaired_count} side UVs.",
        )
        return {"FINISHED"}


OPERATOR_CLASSES = (
    MOZI_PG_auto_extrude_repair,
    MOZI_OT_auto_extrude_repair,
    MOZI_OT_random_extrude,
)


def register():
    if hasattr(bpy.types, "Scene"):
        bpy.types.Scene.mozi_auto_extrude_repair = PointerProperty(
            type=MOZI_PG_auto_extrude_repair
        )
    if depsgraph_auto_extrude_repair_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(depsgraph_auto_extrude_repair_handler)


def unregister():
    if depsgraph_auto_extrude_repair_handler in bpy.app.handlers.depsgraph_update_post:
        try:
            bpy.app.handlers.depsgraph_update_post.remove(depsgraph_auto_extrude_repair_handler)
        except Exception:
            pass
    if bpy.app.timers.is_registered(_deferred_extrude_repair_tick):
        try:
            bpy.app.timers.unregister(_deferred_extrude_repair_tick)
        except Exception:
            pass
    _smart_extrude_sessions.clear()
    _pending_repairs.clear()
    if hasattr(bpy.types.Scene, "mozi_auto_extrude_repair"):
        try:
            del bpy.types.Scene.mozi_auto_extrude_repair
        except Exception:
            pass
