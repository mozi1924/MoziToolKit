"""
Operator: Random terrain extrusion with automatic integrated UV repair & edge creases.
"""

from __future__ import annotations

try:
    import bpy
    from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
except ImportError:
    bpy = None
    BoolProperty = EnumProperty = FloatProperty = IntProperty = lambda *args, **kwargs: None

if bpy is None:
    class _DummyBpyTypes:
        Operator = object
    class _DummyBpy:
        types = _DummyBpyTypes
    bpy = _DummyBpy()

from .properties import NOISE_TYPE_ITEMS, UV_MODE_ITEMS

try:
    from ...bridge.extrude import process_random_extrude
    from ...utils.mesh.core import bmesh_context, poll_edit_mesh
    from ...utils.system.menu_registry import register_menu_item
except (ImportError, ValueError):
    try:
        from ..bridge.extrude import process_random_extrude
        from ..utils.mesh.core import bmesh_context, poll_edit_mesh
        from ..utils.system.menu_registry import register_menu_item
    except (ImportError, ValueError):
        from bridge.extrude import process_random_extrude
        from utils.mesh.core import bmesh_context, poll_edit_mesh
        from utils.system.menu_registry import register_menu_item


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


OPERATOR_CLASSES = [
    MOZI_OT_random_extrude,
]
