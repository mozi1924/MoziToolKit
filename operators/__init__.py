"""
MoziToolKit Operators Root.
"""

try:
    import bpy
except ImportError:
    bpy = None

from .op_cull import OPERATOR_CLASSES as CULL_CLASSES
from .extrude import OPERATOR_CLASSES as EXTRUDE_CLASSES
from .op_materials import OPERATOR_CLASSES as MATERIAL_CLASSES
from .op_mesh import OPERATOR_CLASSES as MESH_CLASSES
from .op_pixel_split import OPERATOR_CLASSES as PIXEL_SPLIT_CLASSES
from .op_precompile import OPERATOR_CLASSES as PRECOMPILE_CLASSES
from .op_texture import OPERATOR_CLASSES as TEXTURE_CLASSES
from .op_uv import OPERATOR_CLASSES as UV_CLASSES
from .op_voxel_cloud import OPERATOR_CLASSES as VOXEL_CLOUD_CLASSES

ALL_OPERATORS = (
    PRECOMPILE_CLASSES
    + MATERIAL_CLASSES
    + MESH_CLASSES
    + UV_CLASSES
    + TEXTURE_CLASSES
    + PIXEL_SPLIT_CLASSES
    + EXTRUDE_CLASSES
    + CULL_CLASSES
    + VOXEL_CLOUD_CLASSES
)

from . import extrude
from . import sync


def register():
    for cls in ALL_OPERATORS:
        bpy.utils.register_class(cls)
    extrude.register()
    sync.register()


def unregister():
    sync.unregister()
    extrude.unregister()
    for cls in reversed(ALL_OPERATORS):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
