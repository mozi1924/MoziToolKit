"""
Constants and type mapping definitions for Blender Mesh and libmtk bridge.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

#: Mesh custom property holding the compact source-texture key palette.
PROP_SOURCE_TEXTURES = "mtk_source_textures"

BLENDER_TO_MTK_DOMAIN: Dict[str, str] = {
    "POINT": "point",
    "CORNER": "corner",
    "FACE": "face",
    "EDGE": "point",
}

MTK_TO_BLENDER_DOMAIN: Dict[str, str] = {
    "point": "POINT",
    "corner": "CORNER",
    "face": "FACE",
    "mesh": "POINT",
}

# Color Space Contract for Color Attributes:
# - FLOAT_COLOR: Maps to MTK "float4". Stores native scene-linear RGBA floats [0.0, 1.0].
#   Extracted via Blender's linear `color` accessor and DNA `f32` buffer directly.
#   All PBR shaders and biome tint attributes (e.g. mtk_biome_tint_color) expect scene-linear float4.
# - BYTE_COLOR: Extracted as MTK "float4" normalized floats [0.0, 1.0] representing raw 8-bit
#   sRGB channels (u8 / 255.0). Extracted via Blender's `color_srgb` accessor and DNA `u8` buffer.
#   This guarantees 100% bit-for-bit parity between Fast-Path DNA direct read and Safe-Path foreach_get,
#   preserving the original discrete 8-bit sRGB color space without round-trip loss.
BLENDER_TO_MTK_TYPE: Dict[str, Tuple[str, int, str, str]] = {
    "FLOAT": ("float", 1, "f", "value"),
    "FLOAT_VECTOR": ("float3", 3, "f", "vector"),
    "FLOAT_VECTOR2": ("float2", 2, "f", "vector"),
    "FLOAT2": ("float2", 2, "f", "vector"),
    "FLOAT_COLOR": ("float4", 4, "f", "color"),
    "BYTE_COLOR": ("uint8", 4, "B", "color"),
    "INT": ("int32", 1, "i", "value"),
    "INT8": ("int8", 1, "b", "value"),
    "INT32": ("int32", 1, "i", "value"),
    "BOOLEAN": ("bool", 1, "b", "value"),
    "STRING": ("string", 1, "", "value"),
}

MTK_TO_BLENDER_TYPE: Dict[str, Tuple[str, str]] = {
    "float": ("FLOAT", "value"),
    "float2": ("FLOAT2", "vector"),
    "float3": ("FLOAT_VECTOR", "vector"),
    "float4": ("FLOAT_COLOR", "color"),
    "int8": ("INT8", "value"),
    "int16": ("INT", "value"),
    "int32": ("INT", "value"),
    "uint8": ("INT", "value"),
    "uint16": ("INT", "value"),
    "uint32": ("INT", "value"),
    "bool": ("BOOLEAN", "value"),
    "string": ("STRING", "value"),
    "Float": ("FLOAT", "value"),
    "Float2": ("FLOAT2", "vector"),
    "Float3": ("FLOAT_VECTOR", "vector"),
    "Float4": ("FLOAT_COLOR", "color"),
    "Int8": ("INT8", "value"),
    "Int16": ("INT", "value"),
    "Int32": ("INT", "value"),
    "UInt8": ("INT", "value"),
    "UInt16": ("INT", "value"),
    "UInt32": ("INT", "value"),
    "Bool": ("BOOLEAN", "value"),
    "String": ("STRING", "value"),
}


def get_mesh(mesh_or_obj: Any) -> Any:
    """Helper to resolve bpy.types.Mesh from either Mesh or Object."""
    if hasattr(mesh_or_obj, "type") and mesh_or_obj.type == "MESH":
        return mesh_or_obj.data
    return mesh_or_obj


_get_mesh = get_mesh


def safe_get_attribute(mesh: Any, name: str) -> Optional[Any]:
    """Safely retrieves a named attribute layer from a Blender Mesh."""
    if not hasattr(mesh, "attributes"):
        return None
    try:
        return mesh.attributes.get(name)
    except Exception:
        return None


def get_or_create_attribute(
    mesh: Any, name: str, data_type: str, domain: str = "FACE"
) -> Optional[Any]:
    """Helper to safely get or create a Blender Mesh attribute."""
    if not hasattr(mesh, "attributes"):
        return None

    dom_upper = domain.upper()
    expected_count = None
    if dom_upper == "FACE":
        expected_count = len(getattr(mesh, "polygons", []))
    elif dom_upper == "CORNER":
        expected_count = len(getattr(mesh, "loops", []))
    elif dom_upper == "POINT":
        if hasattr(mesh, "vertices"):
            expected_count = len(mesh.vertices)
        elif hasattr(mesh, "points"):
            expected_count = len(mesh.points)
    elif dom_upper == "EDGE":
        expected_count = len(getattr(mesh, "edges", []))

    attr = mesh.attributes.get(name)
    if attr is not None and (
        attr.data_type != data_type
        or attr.domain != dom_upper
        or (expected_count is not None and len(attr.data) != expected_count)
    ):
        try:
            mesh.attributes.remove(attr)
        except Exception:
            pass
        attr = None

    if attr is None:
        try:
            return mesh.attributes.new(name=name, type=data_type, domain=domain)
        except Exception:
            return None
    return attr

