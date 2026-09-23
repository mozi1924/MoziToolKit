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

try:
    from ..bridge.extrude import generate_random_extrude_heights, repair_extruded_side_uv
    from ..bridge.uv import get_uv_bounds, is_uv_collapsed
    from ..utils.mesh.core import (
        bmesh_context,
        poll_edit_mesh,
    )
    from ..utils.system.menu_registry import register_menu_item
except (ImportError, ValueError):
    from bridge.extrude import generate_random_extrude_heights, repair_extruded_side_uv
    from bridge.uv import get_uv_bounds, is_uv_collapsed
    from utils.mesh.core import (
        bmesh_context,
        poll_edit_mesh,
    )
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


def repair_extruded_side_faces(
    bm: bmesh.types.BMesh,
    obj=None,
    context=None,
    repair_uv: bool = True,
    add_crease: bool = False,
    crease_val: float = 1.0,
    only_collapsed: bool = True,
    uv_mode: str = "SMART",
    smart_side_face_indices: Optional[Set[int]] = None,
) -> int:
    """Core BMesh walker that detects collapsed side faces and reconstructs UVs via Rust core."""
    if not repair_uv and not add_crease:
        return 0

    uv_layer = bm.loops.layers.uv.verify() if repair_uv else None
    crease_layer = bm.edges.layers.crease.verify() if add_crease else None

    selected_faces = [f for f in bm.faces if f.select and f.is_valid]
    selected_faces_set = set(selected_faces)
    repaired_count = 0

    step_u = 1.0 / 16.0
    step_v = 1.0 / 16.0

    for top_face in selected_faces:
        if not top_face.is_valid:
            continue

        for edge in top_face.edges:
            # Find linked side faces
            for side_face in edge.link_faces:
                if side_face == top_face or not side_face.is_valid:
                    continue
                if len(side_face.verts) != 4:
                    continue

                if only_collapsed and uv_layer:
                    side_uvs = [tuple(l[uv_layer].uv) for l in side_face.loops]
                    if not is_uv_collapsed(side_uvs, pixel_step=(step_u, step_v)):
                        continue

                # Identify vertices
                edge_verts = set(edge.verts)
                top_verts = [v for v in side_face.verts if v in edge_verts]
                base_verts = [v for v in side_face.verts if v not in edge_verts]
                if len(top_verts) != 2 or len(base_verts) != 2:
                    continue

                v_top_a, v_top_b = top_verts[0], top_verts[1]
                v_base_a, v_base_b = base_verts[0], base_verts[1]

                uv_repaired = False
                if repair_uv and uv_layer:
                    uv_a = None
                    uv_b = None
                    for l in top_face.loops:
                        if l.vert == v_top_a:
                            uv_a = (l[uv_layer].uv.x, l[uv_layer].uv.y)
                        elif l.vert == v_top_b:
                            uv_b = (l[uv_layer].uv.x, l[uv_layer].uv.y)

                    if uv_a and uv_b:
                        top_uvs = [tuple(l[uv_layer].uv) for l in top_face.loops]
                        bounds = get_uv_bounds(top_uvs)
                        top_norm = (top_face.normal.x, top_face.normal.y, top_face.normal.z)
                        ext_vec = (
                            (v_top_a.co.x - v_base_a.co.x),
                            (v_top_a.co.y - v_base_a.co.y),
                            (v_top_a.co.z - v_base_a.co.z),
                        )

                        new_uvs = repair_extruded_side_uv(
                            uv_base_a=uv_a,
                            uv_base_b=uv_b,
                            top_normal=top_norm,
                            extrude_vec=ext_vec,
                            mode=uv_mode,
                            step_u=step_u,
                            step_v=step_v,
                            top_uv_bounds=(bounds[0], bounds[1], bounds[2], bounds[3]),
                        )

                        # Match vertices of side face
                        vert_uv_map = {
                            v_base_a: new_uvs[0],
                            v_base_b: new_uvs[1],
                            v_top_b: new_uvs[2],
                            v_top_a: new_uvs[3],
                        }
                        for loop in side_face.loops:
                            if loop.vert in vert_uv_map:
                                loop[uv_layer].uv.x = vert_uv_map[loop.vert][0]
                                loop[uv_layer].uv.y = vert_uv_map[loop.vert][1]
                        uv_repaired = True

                crease_repaired = False
                if add_crease and crease_layer:
                    for e in side_face.edges:
                        if abs(e[crease_layer] - crease_val) > 1e-6:
                            e[crease_layer] = crease_val
                            crease_repaired = True
                    for e in top_face.edges:
                        if abs(e[crease_layer] - crease_val) > 1e-6:
                            e[crease_layer] = crease_val
                            crease_repaired = True

                if uv_repaired or crease_repaired:
                    repaired_count += 1

    return repaired_count


# =========================================================================
# Real-time Background Polling & Depsgraph Listener
# =========================================================================

def _is_extrude_operator_identifier(identifier: str) -> bool:
    id_upper = identifier.upper()
    return (
        id_upper.startswith("MESH_OT_EXTRUDE")
        or id_upper.startswith("VIEW3D_OT_EDIT_MESH_EXTRUDE")
        or "EXTRUDE" in id_upper
    )


def _is_extrude_in_progress(context) -> bool:
    window = getattr(context, "window", None)
    window_manager = getattr(context, "window_manager", None)
    if not window or not window_manager:
        return False
    modal_ops = getattr(window, "modal_operators", [])
    for op in modal_ops:
        identifier = getattr(op, "bl_idname", "")
        if _is_extrude_operator_identifier(identifier):
            return True
        if identifier.upper().startswith("TRANSFORM_OT_"):
            return True
    return False


def _deferred_extrude_repair_tick():
    global _is_updating, _pending_repairs, _smart_extrude_sessions, _idle_ticks

    if _is_updating:
        return _SMART_EXTRUDE_POLL_INTERVAL

    context = bpy.context
    if not context or context.mode != "EDIT_MESH":
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
            uv_mode=props.uv_mode,
            smart_side_face_indices=session["side_face_indices"],
        )
        if repaired_count > 0:
            bmesh.update_edit_mesh(obj.data)
    except Exception as e:
        logger.error(f"Error in auto extrude repair tick: {e}", exc_info=True)
    finally:
        _is_updating = False

    _pending_repairs.discard(obj.as_pointer())

    if repaired_count > 0:
        _idle_ticks = 0
    else:
        _idle_ticks += 1

    if _is_extrude_in_progress(context) and _idle_ticks < _MAX_IDLE_TICKS:
        return _SMART_EXTRUDE_POLL_INTERVAL

    _smart_extrude_sessions.clear()
    _pending_repairs.clear()
    _idle_ticks = 0
    return None


@bpy.app.handlers.persistent
def depsgraph_auto_extrude_repair_handler(scene, depsgraph):
    if _is_updating:
        return
    try:
        context = bpy.context
        if not context or context.mode != "EDIT_MESH":
            return
        props = getattr(scene, "mozi_auto_extrude_repair", None)
        if not props or not props.enabled or not (props.repair_uv or props.add_mean_crease):
            return
        obj = context.active_object
        if not obj or obj.type != "MESH":
            return

        geo_updated = any(u.is_updated_geometry for u in depsgraph.updates)
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
            selected_faces = [f for f in bm.faces if f.select and f.is_valid]
            if not selected_faces:
                self.report({"WARNING"}, "No faces selected.")
                return {"CANCELLED"}

            centers = [(f.calc_center_median().x, f.calc_center_median().y, f.calc_center_median().z) for f in selected_faces]

            # Generate noise heights via Rust core
            heights = generate_random_extrude_heights(
                centers,
                noise_type=self.noise_mode,
                min_height=self.min_height,
                max_height=self.max_height,
                noise_scale=self.noise_scale,
                seed=self.seed,
            )

            # Extrude each face individually
            new_top_faces = []
            for f, h in zip(selected_faces, heights):
                if h <= 1e-6:
                    continue
                res = bmesh.ops.extrude_discrete_faces(bm, faces=[f])
                new_f = res.get("faces", [])
                for top_f in new_f:
                    norm = top_f.normal.normalized()
                    for v in top_f.verts:
                        v.co += norm * h
                    new_top_faces.append(top_f)

            # Crucial: Seamlessly execute UV repair & crease on newly extruded faces
            repaired_count = 0
            if new_top_faces and (self.repair_uv or self.add_mean_crease):
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

        self.report(
            {"INFO"},
            f"Randomly extruded {len(selected_faces)} face(s); repaired {repaired_count} side UVs.",
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
