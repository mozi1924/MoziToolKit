"""
Multi-UV layer management for external mesh material replacement.

External imports keep their original local UV layout in its own UV map. A
separate ``MTK_Atlas`` UV map receives the generated atlas coordinates. This
makes re-atlasing lossless:

* An unchanged atlas layout can reuse the existing atlas UVs and only swap the
  bound textures/materials.
* A changed atlas layout re-maps atlas UVs from the preserved local UVs without
  touching the original layout.

MTK-generated voxel meshes keep their single native ``UVMap``; the atlas layer
is only created for external meshes.
"""

from __future__ import annotations

import array
import hashlib
import json
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("MoziToolKit.Material.UVLayers")

#: UV map used by Atlas materials for external meshes.
ATLAS_UV_LAYER_NAME = "MTK_Atlas"

#: Mesh custom properties recording the layers and the atlas layout hash.
LOCAL_UV_LAYER_PROP = "mtk:local_uv_layer"
ATLAS_UV_LAYER_PROP = "mtk:atlas_uv_layer"
ATLAS_LAYOUT_HASH_PROP = "mtk:atlas_layout_hash"

#: Bump when the canonical layout payload changes.
ATLAS_LAYOUT_HASH_VERSION = "v1"


def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    try:
        getter = getattr(obj, "get", None)
        if callable(getter):
            return getter(key, default)
    except Exception:
        pass
    try:
        return getattr(obj, key, default)
    except Exception:
        return default


def _safe_set(obj: Any, key: str, value: Any) -> None:
    if obj is None:
        return
    try:
        obj[key] = value
        return
    except Exception:
        pass
    try:
        setattr(obj, key, value)
    except Exception:
        pass


def get_uv_layer(mesh: Any, name: Any) -> Optional[Any]:
    """Return a UV layer by name, tolerating mocked/missing DNA collections."""
    if mesh is None or not hasattr(mesh, "uv_layers") or not isinstance(name, str) or not name:
        return None
    try:
        getter = getattr(mesh.uv_layers, "get", None)
        if callable(getter):
            return getter(name)
        for layer in mesh.uv_layers:
            if getattr(layer, "name", "") == name:
                return layer
    except Exception:
        pass
    return None


def _find_local_layer(mesh: Any) -> Optional[Any]:
    """Locate the preserved local UV map, excluding the atlas map."""
    atlas_name = _safe_get(mesh, ATLAS_UV_LAYER_PROP, "")
    if not isinstance(atlas_name, str):
        atlas_name = ""

    stored = _safe_get(mesh, LOCAL_UV_LAYER_PROP, "")
    layer = get_uv_layer(mesh, stored)
    if layer is not None and getattr(layer, "name", "") != atlas_name:
        return layer

    layer = get_uv_layer(mesh, "UVMap")
    if layer is not None and getattr(layer, "name", "") not in (atlas_name, ATLAS_UV_LAYER_NAME):
        return layer

    try:
        for candidate in mesh.uv_layers:
            name = getattr(candidate, "name", "")
            if name and name not in (atlas_name, ATLAS_UV_LAYER_NAME):
                return candidate
    except Exception:
        pass
    return None


def _find_atlas_layer(mesh: Any) -> Optional[Any]:
    """Locate the atlas UV map recorded on the mesh or by convention."""
    stored = _safe_get(mesh, ATLAS_UV_LAYER_PROP, "")
    layer = get_uv_layer(mesh, stored)
    if layer is not None:
        return layer
    return get_uv_layer(mesh, ATLAS_UV_LAYER_NAME)


def find_local_uv_layer(mesh: Any) -> Optional[Any]:
    """Return the preserved local UV map without creating or mutating layers."""
    if mesh is None or not hasattr(mesh, "uv_layers"):
        return None
    return _find_local_layer(mesh)


def detect_legacy_atlas_mesh(mesh: Any) -> bool:
    """
    Detect external meshes produced before multi-UV support.

    These have a single UV layer containing already-baked atlas UVs, plus
    provenance/chunk attributes. Their original local UV layout was overwritten
    and cannot be recovered, so they may only reuse the current atlas UVs.
    """
    if mesh is None or not hasattr(mesh, "uv_layers"):
        return False
    try:
        if len(mesh.uv_layers) != 1:
            return False
    except Exception:
        return False
    if _safe_get(mesh, LOCAL_UV_LAYER_PROP) or _safe_get(mesh, ATLAS_UV_LAYER_PROP):
        return False
    attributes = getattr(mesh, "attributes", None)
    if attributes is None:
        return False
    try:
        has_provenance = (
            "mtk_source_texture_key" in attributes
            or "mtk_source_texture_idx" in attributes
        )
        has_atlas_routing = "mtk_atlas_chunk_id" in attributes
    except Exception:
        return False
    return bool(has_provenance and has_atlas_routing)


def activate_uv_layer(mesh: Any, layer: Any) -> None:
    """Make *layer* the active (and active-render) UV map."""
    if mesh is None or layer is None or not hasattr(mesh, "uv_layers"):
        return
    try:
        index = mesh.uv_layers.find(getattr(layer, "name", ""))
        if index is not None and index >= 0:
            mesh.uv_layers.active_index = index
    except Exception:
        try:
            mesh.uv_layers.active = layer
        except Exception:
            pass
    try:
        mesh.uv_layers.active_render = layer
    except Exception:
        pass


def copy_uv_layer(source: Any, target: Any, num_loops: int) -> bool:
    """Copy loop UVs from *source* to *target*."""
    if source is None or target is None or num_loops <= 0:
        return False
    try:
        data = array.array("f", [0.0]) * (num_loops * 2)
        source.data.foreach_get("uv", data)
        target.data.foreach_set("uv", data)
        return True
    except Exception as exc:
        logger.debug("Failed copying UV layer %r -> %r: %s", source, target, exc)
        return False


def read_uv_layer(layer: Any, num_loops: int) -> array.array:
    """Read loop UVs from *layer* as a flat float array."""
    data = array.array("f", [0.0]) * (num_loops * 2)
    if layer is not None and num_loops > 0:
        try:
            layer.data.foreach_get("uv", data)
        except Exception as exc:
            logger.debug("Failed reading UV layer %r: %s", layer, exc)
    return data


def resolve_uv_layers(
    mesh: Any,
    *,
    create_atlas: bool = True,
    activate: bool = True,
    legacy_atlas: bool = False,
) -> Tuple[Optional[Any], Optional[Any], bool]:
    """
    Resolve ``(local_layer, atlas_layer, created_atlas)`` for *mesh*.

    On a fresh external mesh the original UV layer is preserved as the local
    layer and a new ``MTK_Atlas`` layer is created and activated. On a legacy
    atlas-only mesh (``legacy_atlas=True``) the single existing layer is treated
    as the atlas layer and no local layer is reported.
    """
    if mesh is None or not hasattr(mesh, "uv_layers"):
        return None, None, False

    if legacy_atlas:
        atlas = None
        try:
            if len(mesh.uv_layers) > 0:
                atlas = mesh.uv_layers[0]
        except Exception:
            atlas = None
        if atlas is not None:
            _safe_set(mesh, ATLAS_UV_LAYER_PROP, getattr(atlas, "name", ""))
            if activate:
                activate_uv_layer(mesh, atlas)
        return None, atlas, False

    try:
        layer_count = len(mesh.uv_layers)
    except Exception:
        layer_count = 0

    if layer_count == 0:
        local = mesh.uv_layers.new(name="UVMap")
    else:
        local = _find_local_layer(mesh)

    atlas = _find_atlas_layer(mesh)
    created = False
    if atlas is None and create_atlas:
        atlas = mesh.uv_layers.new(name=ATLAS_UV_LAYER_NAME)
        created = True
        if local is not None:
            copy_uv_layer(local, atlas, len(mesh.loops))

    if local is not None and atlas is not None and getattr(local, "name", "") == getattr(atlas, "name", ""):
        local = None

    if local is not None:
        _safe_set(mesh, LOCAL_UV_LAYER_PROP, getattr(local, "name", ""))
    if atlas is not None:
        _safe_set(mesh, ATLAS_UV_LAYER_PROP, getattr(atlas, "name", ""))
        if activate:
            activate_uv_layer(mesh, atlas)

    return local, atlas, created


def _canonical_chunk(chunk: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "chunk_id",
        "category",
        "category_chunk_index",
        "is_animated",
        "width",
        "height",
        "has_normal",
        "has_specular",
        "has_overlay",
    )
    return {key: chunk.get(key) for key in keys}


def _canonical_sprite(key: str, sprite: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "texture_id",
        "chunk_id",
        "uv_bounds",
        "frame_0_uv_bounds",
        "local_uv_bounds",
        "frame_uv_step",
        "frame_size",
        "frame_count",
        "is_animated",
    )
    payload = {"key": key}
    payload.update({field: sprite.get(field) for field in keys})
    return payload


def compute_atlas_layout_hash(atlas_data: Optional[Dict[str, Any]]) -> str:
    """
    Hash the UV-affecting atlas layout (sprite bounds, routing, chunk geometry).

    Pixel contents and stack fingerprints are intentionally excluded: changing a
    texture image does not invalidate existing atlas UVs, while moving a sprite
    to a different UV rect or chunk does.
    """
    if not isinstance(atlas_data, dict):
        return ""

    chunks = [
        _canonical_chunk(chunk)
        for chunk in atlas_data.get("chunks", [])
        if isinstance(chunk, dict)
    ]
    chunks.sort(
        key=lambda chunk: (
            str(chunk.get("chunk_id")),
            str(chunk.get("category")),
            str(chunk.get("category_chunk_index")),
        )
    )

    def _sprites(bucket_name: str) -> list:
        bucket = atlas_data.get(bucket_name, {})
        if not isinstance(bucket, dict):
            return []
        rows = [
            _canonical_sprite(key, sprite)
            for key, sprite in bucket.items()
            if isinstance(sprite, dict)
        ]
        rows.sort(key=lambda row: row["key"])
        return rows

    payload = {
        "chunks": chunks,
        "sprites": _sprites("sprites"),
        "anim_sprites": _sprites("anim_sprites"),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return f"{ATLAS_LAYOUT_HASH_VERSION}:{digest}"


def get_stored_layout_hash(mesh: Any) -> str:
    value = _safe_get(mesh, ATLAS_LAYOUT_HASH_PROP, "")
    return value if isinstance(value, str) else ""


def set_stored_layout_hash(mesh: Any, layout_hash: str) -> None:
    if isinstance(layout_hash, str) and layout_hash:
        _safe_set(mesh, ATLAS_LAYOUT_HASH_PROP, layout_hash)


__all__ = [
    "ATLAS_UV_LAYER_NAME",
    "LOCAL_UV_LAYER_PROP",
    "ATLAS_UV_LAYER_PROP",
    "ATLAS_LAYOUT_HASH_PROP",
    "ATLAS_LAYOUT_HASH_VERSION",
    "detect_legacy_atlas_mesh",
    "find_local_uv_layer",
    "resolve_uv_layers",
    "activate_uv_layer",
    "copy_uv_layer",
    "read_uv_layer",
    "compute_atlas_layout_hash",
    "get_stored_layout_hash",
    "set_stored_layout_hash",
]
