"""
Constants and type mapping definitions for Blender Mesh and libmtk bridge.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

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

MTK_TO_BLENDER_TYPE: Dict[str, Tuple[str, str, str]] = {
    "float": ("FLOAT", "value", "f"),
    "float2": ("FLOAT2", "vector", "f"),
    "float3": ("FLOAT_VECTOR", "vector", "f"),
    "float4": ("FLOAT_COLOR", "color", "f"),
    "int8": ("INT8", "value", "b"),
    "int16": ("INT", "value", "h"),
    "int32": ("INT", "value", "i"),
    "uint8": ("INT", "value", "B"),
    "uint16": ("INT", "value", "H"),
    "uint32": ("INT", "value", "I"),
    "bool": ("BOOLEAN", "value", "?"),
    "string": ("STRING", "value", ""),
    "Float": ("FLOAT", "value", "f"),
    "Float2": ("FLOAT2", "vector", "f"),
    "Float3": ("FLOAT_VECTOR", "vector", "f"),
    "Float4": ("FLOAT_COLOR", "color", "f"),
    "Int8": ("INT8", "value", "b"),
    "Int16": ("INT", "value", "h"),
    "Int32": ("INT", "value", "i"),
    "UInt8": ("INT", "value", "B"),
    "UInt16": ("INT", "value", "H"),
    "UInt32": ("INT", "value", "I"),
    "Bool": ("BOOLEAN", "value", "?"),
    "String": ("STRING", "value", ""),
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
    attr = mesh.attributes.get(name)
    if attr is None:
        try:
            return mesh.attributes.new(name=name, type=data_type, domain=domain)
        except Exception:
            return None
    return attr
