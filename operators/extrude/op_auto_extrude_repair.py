"""
Operator: Auto Extrude UV Repair on selected/all faces.
"""

from __future__ import annotations

try:
    import bpy
    from bpy.props import BoolProperty, EnumProperty, FloatProperty
except ImportError:
    bpy = None
    BoolProperty = EnumProperty = FloatProperty = lambda *args, **kwargs: None

if bpy is None:
    class _DummyBpyTypes:
        Operator = object
    class _DummyBpy:
        types = _DummyBpyTypes
    bpy = _DummyBpy()

from .properties import UV_MODE_ITEMS

try:
    from ...bridge.extrude import repair_extruded_side_faces
    from ...utils.mesh.core import bmesh_context, poll_edit_mesh
    from ...utils.system.menu_registry import register_menu_item
except (ImportError, ValueError):
    try:
        from ..bridge.extrude import repair_extruded_side_faces
        from ..utils.mesh.core import bmesh_context, poll_edit_mesh
        from ..utils.system.menu_registry import register_menu_item
    except (ImportError, ValueError):
        from bridge.extrude import repair_extruded_side_faces
        from utils.mesh.core import bmesh_context, poll_edit_mesh
        from utils.system.menu_registry import register_menu_item


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


OPERATOR_CLASSES = [
    MOZI_OT_auto_extrude_repair,
]
