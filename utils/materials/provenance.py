"""
Material provenance, mode detection, and face source attribute tracking.
"""

from __future__ import annotations

import json
from pathlib import Path
try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

from .constants import (
    ATTR_SOURCE_ORIGIN,
    ATTR_SOURCE_TEXTURE_KEY,
    DEFAULT_NAMESPACE,
    PROP_CREATED_BY,
    PROP_PROVENANCE_SCHEMA_VERSION,
    PROP_ATLAS_MAPPING,
    PROVENANCE_SCHEMA_VERSION,
)


def without_blender_suffix(value: str) -> str:
    """Remove Blender's duplicate numeric suffix (e.g. '.001') without modifying valid names."""
    if "." in value and value.rsplit(".", 1)[1].isdigit():
        return value.rsplit(".", 1)[0]
    return value


def canonical_texture_key(namespace: str, texture_name: str) -> str:
    """Return the durable ``namespace:texture`` source identifier.

    The key intentionally does not contain a resource-pack hash: a later
    replacement pack is allowed to provide the same Minecraft resource.
    """
    namespace = (namespace or DEFAULT_NAMESPACE).strip().lower()
    texture_name = (texture_name or "").strip().lower().removesuffix(".png")
    return f"{namespace}:{texture_name}" if texture_name else ""


def split_texture_key(value: str) -> tuple[str, str]:
    """Parse a canonical key, accepting legacy texture-only values."""
    value = (value or "").strip().lower().removesuffix(".png")
    if not value:
        return DEFAULT_NAMESPACE, ""
    if ":" in value:
        namespace, texture_name = value.split(":", 1)
        return namespace or DEFAULT_NAMESPACE, texture_name
    return DEFAULT_NAMESPACE, value


def write_face_source_provenance(
    mesh: bpy.types.Mesh,
    texture_keys: list[str],
    origins: list[str] | None = None,
) -> None:
    """Write source identity only after a whole mesh conversion is validated."""
    if len(texture_keys) != len(mesh.polygons):
        raise ValueError("Source provenance must contain one entry per polygon")
    if origins is not None and len(origins) != len(mesh.polygons):
        raise ValueError("Source origins must contain one entry per polygon")

    def string_face_attribute(name: str):
        attr = mesh.attributes.get(name)
        if attr and (attr.domain != "FACE" or attr.data_type != "STRING"):
            mesh.attributes.remove(attr)
            attr = None
        return attr or mesh.attributes.new(name=name, type="STRING", domain="FACE")

    key_attr = string_face_attribute(ATTR_SOURCE_TEXTURE_KEY)
    for item, key in zip(key_attr.data, texture_keys):
        item.value = key.encode("utf-8")
    if origins is not None:
        origin_attr = string_face_attribute(ATTR_SOURCE_ORIGIN)
        for item, origin in zip(origin_attr.data, origins):
            item.value = origin.encode("utf-8")


def get_face_source_origin(mesh: bpy.types.Mesh, poly_idx: int) -> str:
    """Read an existing FACE origin without treating Mozi output as origin."""
    attr = mesh.attributes.get(ATTR_SOURCE_ORIGIN)
    if not attr or attr.domain != "FACE" or attr.data_type != "STRING" or poly_idx >= len(attr.data):
        return ""
    value = attr.data[poly_idx].value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value).strip()


def get_face_source_texture_key(mesh: bpy.types.Mesh, poly_idx: int) -> str:
    """Read an existing canonical source key, if this face already has one."""
    attr = mesh.attributes.get(ATTR_SOURCE_TEXTURE_KEY)
    if not attr or attr.domain != "FACE" or attr.data_type != "STRING" or poly_idx >= len(attr.data):
        return ""
    value = attr.data[poly_idx].value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value).strip()


def detect_material_mode(mat: bpy.types.Material | None) -> str:
    """Detect whether a material is Standalone, Atlas Chunk, Unified Atlas, or Generic."""
    if not mat:
        return "GENERIC"

    if "mtk:atlas_chunk_id" in mat:
        return "ATLAS_CHUNK"

    if mat.node_tree and "mtk:atlas_mapping" in mat.node_tree:
        if mat.name.startswith("mtk:") and "atlas_chunk" in mat.name:
            return "ATLAS_CHUNK"
        return "ATLAS_UNIFIED"

    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.name == "MC Atlas UV Decoder" or (
                node.type == "GROUP" and node.node_tree and node.node_tree.name == "MC_Atlas_UV_Decoder"
            ):
                return "ATLAS_UNIFIED"

    if "mtk:source_texture" in mat or "mtk:source_namespace" in mat:
        source_tex = str(mat.get("mtk:source_texture", ""))
        if source_tex.startswith("atlas_chunk_"):
            return "ATLAS_CHUNK"
        return "STANDALONE"

    return "GENERIC"


def is_mozi_material(mat: bpy.types.Material | None) -> bool:
    """Check if a material was created by MoziToolKit."""
    if not mat:
        return False
    # New materials carry an explicit, versioned ownership contract.  Keep
    # the older heuristics below only so existing blend files remain usable.
    if mat.get(PROP_CREATED_BY) == "MoziToolKit":
        return True
    if any(key in mat for key in (
        "mtk:source_texture", "mtk:source_namespace", "mtk:atlas_chunk_id", "mtk:material_id",
    )):
        return True
    if mat.node_tree and PROP_ATLAS_MAPPING in mat.node_tree:
        return True
    return False


def get_atlas_mapping_from_material(mat: bpy.types.Material | None) -> dict | None:
    """Extract and parse atlas_mapping JSON dictionary stored on a material or its node tree."""
    if not mat:
        return None
    raw = None
    if "mtk:atlas_mapping" in mat:
        raw = mat["mtk:atlas_mapping"]
    elif "mtk_atlas_mapping" in mat:
        raw = mat["mtk_atlas_mapping"]
    elif mat.node_tree and "mtk:atlas_mapping" in mat.node_tree:
        raw = mat.node_tree["mtk:atlas_mapping"]
    elif mat.node_tree and "mtk_atlas_mapping" in mat.node_tree:
        raw = mat.node_tree["mtk_atlas_mapping"]

    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def get_material_atlas_dimensions(mat: bpy.types.Material | None) -> dict:
    """Extract atlas dimensions (width, height, tile_size, tiles_per_row) from material custom properties or mapping."""
    res = {
        "width": 1024.0,
        "height": 1024.0,
        "tile_size": 16.0,
        "tiles_per_row": 64,
    }
    if not mat:
        return res

    if "mtk_atlas_width" in mat:
        res["width"] = float(mat["mtk_atlas_width"])
    if "mtk_atlas_height" in mat:
        res["height"] = float(mat["mtk_atlas_height"])
    if "mtk_tile_size" in mat:
        res["tile_size"] = float(mat["mtk_tile_size"])
    if "mtk_tiles_per_row" in mat:
        res["tiles_per_row"] = int(mat["mtk_tiles_per_row"])

    mapping = get_atlas_mapping_from_material(mat)
    if mapping:
        if "tile_size" in mapping and "mtk_tile_size" not in mat:
            res["tile_size"] = float(mapping["tile_size"])
        chunks = mapping.get("chunks", [])
        if chunks:
            chunk = chunks[0]
            if "width" in chunk and "mtk_atlas_width" not in mat:
                res["width"] = float(chunk["width"])
            if "height" in chunk and "mtk_atlas_height" not in mat:
                res["height"] = float(chunk["height"])
            if "tile_size" in chunk and "mtk_tile_size" not in mat:
                res["tile_size"] = float(chunk["tile_size"])
            if "tiles_per_row" in chunk and "mtk_tiles_per_row" not in mat:
                res["tiles_per_row"] = int(chunk["tiles_per_row"])

    return res


def get_atlas_mapping_from_mesh(mesh: bpy.types.Mesh | None) -> dict | None:
    """Read the mesh-side atlas mapping backup used when a node tree is edited."""
    if not mesh or PROP_ATLAS_MAPPING not in mesh:
        return None
    raw = mesh[PROP_ATLAS_MAPPING]
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def write_provenance_schema(owner) -> None:
    """Stamp a Blender ID datablock with Mozi's explicit provenance contract."""
    owner[PROP_CREATED_BY] = "MoziToolKit"
    owner[PROP_PROVENANCE_SCHEMA_VERSION] = PROVENANCE_SCHEMA_VERSION

