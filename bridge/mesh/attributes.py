"""
Mesh attribute injection utilities (source texture keys, custom attributes, palette indices).
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Sequence, Tuple

import numpy as np

from ..dna import is_dna_enabled
from .attribute_schema import ATTR_SOURCE_TEXTURE_KEY, is_active
from .constants import (
    MTK_TO_BLENDER_DOMAIN,
    PROP_SOURCE_TEXTURES,
    MTK_TO_BLENDER_TYPE,
    get_mesh,
    get_or_create_attribute,
)
from .dna import inject_custom_attribute_dna

logger = logging.getLogger("MoziToolKit.Bridge.Mesh.Attributes")


def resolve_source_texture_keys(mesh_or_obj: Any) -> List[str]:
    """
    High-performance helper to resolve per-face source texture keys.

    Reads the canonical INT palette-indexed pair
    (`mtk_source_texture_idx` + `mtk_source_textures`). The retired per-face
    STRING attribute (`mtk_source_texture_key`) is never consulted: the native
    mesher no longer emits it and hosts purge it on ingestion.
    """
    mesh = get_mesh(mesh_or_obj)
    if not mesh or not hasattr(mesh, "polygons") or len(mesh.polygons) == 0:
        return []

    num_polys = len(mesh.polygons)

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

    return []


def resolve_source_texture_keys_paletted(mesh_or_obj: Any) -> Tuple[List[str], Any]:
    """
    Return `(palette, indices)` for per-face source texture keys.

    Reads the canonical INT palette attribute (`mtk_source_textures` +
    `mtk_source_texture_idx`). Returns an empty palette and empty int32 array
    when no palette provenance exists.
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
    elif hasattr(indices, "format") and indices.format == "i":
        arr = indices
    else:
        arr = np.frombuffer(indices, dtype=np.int32)
    if len(arr) != num_polys:
        logger.warning(
            "Source-texture palette not written: got %d indices for %d faces",
            len(arr),
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

    # Clean up retired per-face string attribute if left over
    attr_str = mesh.attributes.get(ATTR_SOURCE_TEXTURE_KEY)
    if attr_str is not None:
        try:
            mesh.attributes.remove(attr_str)
        except Exception as exc:
            logger.debug("Failed to remove retired provenance string: %s", exc)


def inject_face_source_texture_keys(mesh: Any, values: Sequence[str]) -> None:
    """
    Inject face source texture keys via palette indexing (sub-millisecond throughput).
    Creates:
      - mesh["mtk_source_textures"]: List[str] palette
      - "mtk_source_texture_idx": INT (FACE) attribute with mapped indices
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
        np_indices = np.fromiter((key_to_idx[k] for k in values), dtype=np.int32, count=num_polys)
        attr_idx.data.foreach_set("value", np_indices)

    # Clean up retired per-face string attribute if left over
    attr_str = mesh.attributes.get(ATTR_SOURCE_TEXTURE_KEY)
    if attr_str is not None:
        try:
            mesh.attributes.remove(attr_str)
        except Exception as exc:
            logger.debug("Failed to remove retired provenance string: %s", exc)


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


def inject_custom_attributes(
    mesh: Any,
    mesh_data: Any,
    skip_string_attributes: bool = False,
    use_dna: bool = True,
) -> None:
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

            # Mesh-level global attributes (such as palettes or bounding boxes) are
            # stored as ID custom properties on the Mesh datablock, not custom data layers.
            if domain_str.lower() == "mesh":
                if dtype_name.lower() == "string":
                    str_vals = mesh_data.get_string_attribute(attr_name)
                    if str_vals is not None:
                        mesh[attr_name] = list(str_vals)
                else:
                    mv = mesh_data.attribute_memoryview(attr_name)
                    if mv is not None:
                        arr_dtype = np.int32 if "int" in dtype_name.lower() else np.float32
                        mesh[attr_name] = list(np.frombuffer(mv, dtype=arr_dtype))
                continue

            b_domain = MTK_TO_BLENDER_DOMAIN.get(domain_str.lower(), "POINT")

            # Source-texture provenance is always palette-based
            # (`mtk_source_textures` + `mtk_source_texture_idx`); per-face strings
            # are retired and never emitted, so they are only purged above.
            if dtype_name.lower() == "string" and skip_string_attributes:
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

            if dtype_name.lower() != "string":
                mv = mesh_data.attribute_memoryview(attr_name)
                if mv is not None:
                    dna_injected = False
                    if use_dna and is_dna_enabled():
                        try:
                            dna_injected = inject_custom_attribute_dna(
                                b_attr, mv, b_type, elem_count
                            )
                        except Exception as e:
                            logger.debug(
                                "DNA custom attribute injection error on %s: %s", attr_name, e
                            )

                    if not dna_injected:
                        try:
                            if hasattr(mv, "cast") and mv.format == "B" and typecode:
                                mv = mv.cast(typecode)
                            b_attr.data.foreach_set(value_key, mv)
                        except Exception as e:
                            logger.debug("Failed setting attribute %s: %s", attr_name, e)
        except Exception as e:
            logger.debug("Error injecting attribute %s: %s", attr_name, e)
