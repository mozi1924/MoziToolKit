"""
Mesh attribute injection utilities (source texture keys, custom attributes, palette indices).
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Sequence, Tuple

import numpy as np

from .attribute_schema import ATTR_SOURCE_TEXTURE_KEY, is_active
from .constants import (
    MTK_TO_BLENDER_DOMAIN,
    PROP_SOURCE_TEXTURES,
    MTK_TO_BLENDER_TYPE,
    get_mesh,
    get_or_create_attribute,
)

logger = logging.getLogger("MoziToolKit.Bridge.Mesh.Attributes")


def resolve_source_texture_keys(mesh_or_obj: Any) -> List[str]:
    """
    High-performance helper to resolve face source texture keys.
    Prioritizes INT palette-indexed attribute ('mtk_source_texture_idx' + 'mtk_source_textures'),
    with graceful fallback to direct STRING attribute ('mtk_source_texture_key').
    """
    mesh = get_mesh(mesh_or_obj)
    if not mesh or not hasattr(mesh, "polygons") or len(mesh.polygons) == 0:
        return []

    num_polys = len(mesh.polygons)

    # 1. Fast Path: INT attribute + Palette
    palette = None
    if hasattr(mesh, "keys") and "mtk_source_textures" in mesh:
        palette = list(mesh["mtk_source_textures"])
    elif hasattr(mesh_or_obj, "get") and "mtk_source_textures" in mesh_or_obj:
        palette = list(mesh_or_obj["mtk_source_textures"])

    attr_idx = mesh.attributes.get("mtk_source_texture_idx") if hasattr(mesh, "attributes") else None
    if attr_idx is not None and palette is not None and len(attr_idx.data) == num_polys:
        pal_len = len(palette)
        if hasattr(attr_idx.data, "foreach_get"):
            idx_arr = np.empty(num_polys, dtype=np.int32)
            attr_idx.data.foreach_get("value", idx_arr)
            return [palette[i] if 0 <= i < pal_len else "" for i in idx_arr]

    # 2. Robust Fallback: STRING attribute ('mtk_source_texture_key')
    attr_str = mesh.attributes.get(ATTR_SOURCE_TEXTURE_KEY) if hasattr(mesh, "attributes") else None
    if attr_str is not None and len(attr_str.data) == num_polys:
        result = []
        for elem in attr_str.data:
            val = getattr(elem, "value", "")
            if isinstance(val, (bytes, bytearray)):
                result.append(val.decode("utf-8", errors="replace"))
            else:
                result.append(str(val))
        return result

    return []


def resolve_source_texture_keys_paletted(mesh_or_obj: Any) -> Tuple[List[str], Any]:
    """
    Return `(palette, indices)` for per-face source texture keys.

    Prefers the INT palette attribute (`mtk_source_textures` +
    `mtk_source_texture_idx`); falls back to STRING attribute ('mtk_source_texture_key').
    Returns an empty palette and empty int32 array when no provenance exists.
    """
    mesh = get_mesh(mesh_or_obj)
    if not mesh or not hasattr(mesh, "polygons") or len(mesh.polygons) == 0:
        return [], np.empty(0, dtype=np.uint32)

    num_polys = len(mesh.polygons)
    palette = None
    if hasattr(mesh, "keys") and "mtk_source_textures" in mesh:
        palette = list(mesh["mtk_source_textures"])
    elif hasattr(mesh_or_obj, "get") and "mtk_source_textures" in mesh_or_obj:
        palette = list(mesh_or_obj["mtk_source_textures"])

    attr_idx = mesh.attributes.get("mtk_source_texture_idx") if hasattr(mesh, "attributes") else None
    if attr_idx is not None and palette is not None and len(attr_idx.data) == num_polys:
        idx_arr = np.empty(num_polys, dtype=np.uint32)
        attr_idx.data.foreach_get("value", idx_arr)
        return palette, idx_arr

    # 2. Robust Fallback: STRING attribute ('mtk_source_texture_key')
    attr_str = mesh.attributes.get(ATTR_SOURCE_TEXTURE_KEY) if hasattr(mesh, "attributes") else None
    if attr_str is not None and len(attr_str.data) == num_polys:
        values = []
        for elem in attr_str.data:
            val = getattr(elem, "value", "")
            if isinstance(val, (bytes, bytearray)):
                values.append(val.decode("utf-8", errors="replace"))
            else:
                values.append(str(val))
        palette = list(dict.fromkeys(values))
        key_to_idx = {k: i for i, k in enumerate(palette)}
        indices = np.fromiter((key_to_idx[k] for k in values), dtype=np.uint32, count=num_polys)
        return palette, indices

    return [], np.empty(0, dtype=np.uint32)


def inject_face_source_texture_palette(
    mesh: Any,
    palette: Sequence[str],
    indices: Any,
) -> None:
    """Write source texture provenance directly as palette + INT indices."""
    if not hasattr(mesh, "attributes") or not hasattr(mesh, "polygons"):
        return
    num_polys = len(mesh.polygons)
    if num_polys == 0:
        return
    if isinstance(indices, (list, tuple)):
        arr = np.ascontiguousarray(indices, dtype=np.int32)
    else:
        arr = np.frombuffer(indices, dtype=np.int32)
    if arr.size != num_polys:
        logger.warning(
            "Source-texture palette not written: got %d indices for %d faces",
            arr.size,
            num_polys,
        )
        return
    mesh[PROP_SOURCE_TEXTURES] = list(palette)
    attr_idx = get_or_create_attribute(mesh, "mtk_source_texture_idx", "INT", "FACE")
    if attr_idx is None or len(attr_idx.data) != num_polys:
        logger.warning(
            "Source-texture palette index attribute could not be sized to %d faces",
            num_polys,
        )
        return
    attr_idx.data.foreach_set("value", arr)

    # Synchronize or populate mtk_source_texture_key for meshes <= 1024 faces or when already existing
    attr_str = mesh.attributes.get(ATTR_SOURCE_TEXTURE_KEY)
    if attr_str is not None or num_polys <= 1024:
        if attr_str is None:
            attr_str = get_or_create_attribute(mesh, ATTR_SOURCE_TEXTURE_KEY, "STRING", "FACE")
        if attr_str is not None and len(attr_str.data) == num_polys:
            pal_list = list(palette)
            pal_len = len(pal_list)
            for i in range(num_polys):
                idx = int(arr[i])
                val = pal_list[idx] if 0 <= idx < pal_len else ""
                b_val = str(val).encode("utf-8")
                try:
                    attr_str.data[i].value = b_val
                except Exception as exc:
                    logger.debug("Failed to write source texture key at face %d: %s", i, exc)


def inject_face_source_texture_keys(mesh: Any, values: Sequence[str]) -> None:
    """
    Inject face source texture keys via palette indexing (sub-millisecond throughput).
    Creates:
      - mesh["mtk_source_textures"]: List[str] palette
      - "mtk_source_texture_idx": INT (FACE) attribute with mapped indices
      - "mtk_source_texture_key": STRING (FACE) attribute for interop and fallback
    """
    if not hasattr(mesh, "attributes") or not hasattr(mesh, "polygons"):
        return
    num_polys = len(mesh.polygons)
    if num_polys == 0 or len(values) != num_polys:
        logger.warning(
            "Source-texture keys not written: got %d keys for %d faces",
            len(values),
            num_polys,
        )
        return

    # 1. Build palette and index mapping
    palette = list(dict.fromkeys(values))
    key_to_idx = {k: i for i, k in enumerate(palette)}
    mesh[PROP_SOURCE_TEXTURES] = palette

    # 2. Write INT attribute in bulk
    attr_idx = get_or_create_attribute(mesh, "mtk_source_texture_idx", "INT", "FACE")
    if attr_idx is not None and len(attr_idx.data) == num_polys:
        np_indices = np.fromiter((key_to_idx[k] for k in values), dtype=np.uint32, count=num_polys)
        attr_idx.data.foreach_set("value", np_indices)

    # 3. Synchronize or populate STRING attribute for compatibility
    attr_str = mesh.attributes.get(ATTR_SOURCE_TEXTURE_KEY)
    if attr_str is not None or num_polys <= 1024:
        if attr_str is None:
            attr_str = get_or_create_attribute(mesh, ATTR_SOURCE_TEXTURE_KEY, "STRING", "FACE")
        if attr_str is not None and len(attr_str.data) == num_polys:
            for i, val in enumerate(values):
                b_val = str(val).encode("utf-8") if isinstance(val, str) else bytes(val)
                try:
                    attr_str.data[i].value = b_val
                except Exception as exc:
                    logger.debug("Failed to write source texture key at face %d: %s", i, exc)


def inject_face_attribute_string(mesh: Any, name: str, values: List[str]) -> None:
    """Inject a Face-domain String attribute into Blender Mesh."""
    if name == ATTR_SOURCE_TEXTURE_KEY:
        inject_face_source_texture_keys(mesh, values)
        return
    attr = get_or_create_attribute(mesh, name, "STRING", "FACE")
    if attr and len(attr.data) == len(values):
        for i, val in enumerate(values):
            b_val = val.encode("utf-8") if isinstance(val, str) else bytes(val)
            try:
                attr.data[i].value = b_val
            except Exception:
                try:
                    attr.data[i].value = val
                except Exception:
                    pass


def inject_face_attribute_int(mesh: Any, name: str, values: Any) -> None:
    """Inject a Face-domain Int attribute into Blender Mesh (list or buffer)."""
    attr = get_or_create_attribute(mesh, name, "INT", "FACE")
    if not attr:
        return
    if isinstance(values, (list, tuple)):
        arr = np.ascontiguousarray(values, dtype=np.int32)
    else:
        arr = np.frombuffer(values, dtype=np.int32)
    if arr.size == len(attr.data):
        attr.data.foreach_set("value", arr)


def inject_face_attribute_float(mesh: Any, name: str, values: Any) -> None:
    """Inject a Face-domain Float attribute into Blender Mesh (list or buffer)."""
    attr = get_or_create_attribute(mesh, name, "FLOAT", "FACE")
    if not attr:
        return
    if isinstance(values, (list, tuple)):
        arr = np.ascontiguousarray(values, dtype=np.float32)
    else:
        arr = np.frombuffer(values, dtype=np.float32)
    if arr.size == len(attr.data):
        attr.data.foreach_set("value", arr)


def inject_face_attribute_float4(mesh: Any, name: str, flat_values: Any) -> None:
    """Inject a Face-domain Float4/Color attribute into Blender Mesh.

    Accepts both Python sequences and buffer-protocol objects (numpy arrays /
    memoryviews). Buffers are consumed without an extra `np.ascontiguousarray`
    copy, which matters for Rust-owned flat property/recolor buffers.
    """
    attr = get_or_create_attribute(mesh, name, "FLOAT_COLOR", "FACE")
    if not attr:
        return
    if isinstance(flat_values, (list, tuple)):
        arr = np.ascontiguousarray(flat_values, dtype=np.float32)
    else:
        arr = np.frombuffer(flat_values, dtype=np.float32)
    if arr.size != len(attr.data) * 4:
        return
    attr.data.foreach_set("color", arr)


def inject_face_attribute_vector(mesh: Any, name: str, flat_values: Any) -> None:
    """Inject a Face-domain Float Vector attribute into Blender Mesh (list or buffer)."""
    attr = get_or_create_attribute(mesh, name, "FLOAT_VECTOR", "FACE")
    if not attr:
        return
    if isinstance(flat_values, (list, tuple)):
        arr = np.ascontiguousarray(flat_values, dtype=np.float32)
    else:
        arr = np.frombuffer(flat_values, dtype=np.float32)
    if arr.size == len(attr.data) * 3:
        attr.data.foreach_set("vector", arr)


def inject_attribute(
    mesh: Any,
    name: str,
    values: Any,
    data_type: str = "FLOAT",
    domain: str = "FACE",
) -> None:
    """Generic attribute injection dispatcher for Blender Mesh attributes."""
    dtype_upper = data_type.upper()
    dom_upper = domain.upper()

    if dom_upper == "FACE":
        if dtype_upper == "STRING":
            inject_face_attribute_string(mesh, name, values)
            return
        elif dtype_upper in ("INT", "INT32", "INT8", "BOOLEAN"):
            inject_face_attribute_int(mesh, name, values)
            return
        elif dtype_upper == "FLOAT":
            inject_face_attribute_float(mesh, name, values)
            return
        elif dtype_upper in ("FLOAT_COLOR", "BYTE_COLOR"):
            inject_face_attribute_float4(mesh, name, values)
            return
        elif dtype_upper in ("FLOAT_VECTOR", "FLOAT3"):
            inject_face_attribute_vector(mesh, name, values)
            return

    attr = get_or_create_attribute(mesh, name, dtype_upper, dom_upper)
    if not attr:
        return

    if dtype_upper == "STRING" and len(attr.data) == len(values):
        for i, val in enumerate(values):
            b_val = val.encode("utf-8") if isinstance(val, str) else bytes(val)
            try:
                attr.data[i].value = b_val
            except Exception:
                try:
                    attr.data[i].value = val
                except Exception:
                    pass
    elif dtype_upper in ("FLOAT_COLOR", "BYTE_COLOR"):
        attr.data.foreach_set("color", np.ascontiguousarray(values, dtype=np.float32))
    elif dtype_upper in ("FLOAT_VECTOR", "FLOAT3"):
        attr.data.foreach_set("vector", np.ascontiguousarray(values, dtype=np.float32))
    elif dtype_upper in ("INT", "INT32", "INT8", "BOOLEAN"):
        attr.data.foreach_set("value", np.ascontiguousarray(values, dtype=np.int32))
    elif dtype_upper == "FLOAT":
        attr.data.foreach_set("value", np.ascontiguousarray(values, dtype=np.float32))


def _inject_palette_provenance(mesh: Any, mesh_data: Any, attr_name: str) -> bool:
    """
    Inject compact palette provenance for a skipped string attribute.

    Live Sync meshes skip per-face strings to keep large baselines light, but the
    biome/material paths still need the original texture keys. The Rust mesher keeps
    those values, so we rebuild the palette + INT index attribute instead of losing
    provenance. Falls back to the legacy string path for older native builds.
    """
    if attr_name != ATTR_SOURCE_TEXTURE_KEY:
        return False

    builder = getattr(mesh_data, "source_texture_palette_indices", None)
    if callable(builder):
        try:
            palette, indices = builder()
            if palette:
                inject_face_source_texture_palette(mesh, palette, indices)
                return True
        except Exception as e:
            logger.debug("Palette provenance fast path failed: %s", e)

    return False


def inject_custom_attributes(mesh: Any, mesh_data: Any, skip_string_attributes: bool = False) -> None:
    """Generic custom attributes synchronization into mesh.attributes."""
    if not hasattr(mesh, "attributes") or not hasattr(mesh_data, "attribute_names"):
        return

    for attr_name in mesh_data.attribute_names():
        if not is_active(attr_name):
            # The native core never emits retired attributes; guard against a
            # stale native build and purge any leftover layer.
            b_attr = mesh.attributes.get(attr_name)
            if b_attr is not None:
                try:
                    mesh.attributes.remove(b_attr)
                except Exception as exc:
                    logger.debug("Failed to purge retired attribute %s: %s", attr_name, exc)
            continue

        try:
            info = mesh_data.attribute_info(attr_name)
            if info is None:
                continue

            domain_str, dtype_name, elem_count = info
            b_domain = MTK_TO_BLENDER_DOMAIN.get(domain_str.lower(), "POINT")

            # Source-texture provenance is always palette-based. Per-face strings
            # remain only as a <=256-face compatibility shim inside the helper, so
            # save imports and Live Sync meshes expose the exact same attributes.
            if dtype_name.lower() == "string":
                if attr_name == ATTR_SOURCE_TEXTURE_KEY and b_domain == "FACE":
                    _inject_palette_provenance(mesh, mesh_data, attr_name)
                    continue
                if skip_string_attributes:
                    continue

            type_tuple = MTK_TO_BLENDER_TYPE.get(dtype_name)
            if type_tuple is None:
                continue

            b_type, value_key, typecode = type_tuple
            b_attr = mesh.attributes.get(attr_name)
            if b_attr is not None and (
                b_attr.data_type != b_type
                or b_attr.domain != b_domain
                or len(b_attr.data) != elem_count
            ):
                try:
                    mesh.attributes.remove(b_attr)
                except Exception:
                    pass
                b_attr = None

            if b_attr is None:
                try:
                    b_attr = mesh.attributes.new(name=attr_name, type=b_type, domain=b_domain)
                except Exception:
                    continue

            if dtype_name.lower() == "string":
                str_vals = mesh_data.get_string_attribute(attr_name)
                if str_vals and len(str_vals) == len(b_attr.data):
                    if len(str_vals) <= 256:
                        for i, val in enumerate(str_vals):
                            b_val = val.encode("utf-8") if isinstance(val, str) else bytes(val)
                            try:
                                b_attr.data[i].value = b_val
                            except Exception:
                                try:
                                    b_attr.data[i].value = val
                                except Exception:
                                    pass
            else:
                mv = mesh_data.attribute_memoryview(attr_name)
                if mv is not None:
                    try:
                        if hasattr(mv, "cast") and mv.format == "B" and typecode:
                            mv = mv.cast(typecode)
                        b_attr.data.foreach_set(value_key, mv)
                    except Exception as e:
                        logger.debug("Failed setting attribute %s: %s", attr_name, e)
        except Exception as e:
            logger.debug("Error injecting attribute %s: %s", attr_name, e)
