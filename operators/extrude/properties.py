"""
Properties definition for Auto Extrude Repair and Random Extrude.
"""

from __future__ import annotations

try:
    import bpy
    from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty
except ImportError:
    bpy = None
    BoolProperty = EnumProperty = FloatProperty = PointerProperty = lambda *args, **kwargs: None

if bpy is None:
    class _DummyBpyTypes:
        PropertyGroup = object
    class _DummyBpy:
        types = _DummyBpyTypes
    bpy = _DummyBpy()

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


PROPERTY_CLASSES = (
    MOZI_PG_auto_extrude_repair,
)


def register():
    if hasattr(bpy.types, "Scene"):
        bpy.types.Scene.mozi_auto_extrude_repair = PointerProperty(
            type=MOZI_PG_auto_extrude_repair
        )


def unregister():
    if hasattr(bpy.types.Scene, "mozi_auto_extrude_repair"):
        try:
            del bpy.types.Scene.mozi_auto_extrude_repair
        except Exception:
            pass
