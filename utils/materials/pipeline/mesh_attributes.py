"""
Mesh Face Attribute and Metadata Management Utilities.
Handles bulk reading and writing of Blender mesh face attributes,
biome tint data encoding, and legacy attribute cleanup.
"""

from __future__ import annotations

import bpy
from ..constants import (
    ATTR_ATLAS_CHUNK_ID,
    ATTR_ATLAS_TEXTURE_ID,
    ATTR_UV_ROTATION,
    ATTR_UV_TILING_SCALE,
    ATTR_UV_TILING_LOCATION,
    ATTR_UV_TILING_TRANSFORM,
    ATTR_BIOME_TINT_DATA,
    ATTR_BIOME_TINT_COLOR,
    ATTR_ANIM_TIMING,
    ATTR_ANIM_FRAME_SIZE,
    ATTR_SOURCE_TEXTURE_KEY,
    ATTR_SOURCE_ORIGIN,
    ANIM_AND_ATLAS_ATTR_NAMES,
    LEGACY_SPLIT_ATTR_NAMES,
)
from ..biome import (
    get_biome_colors,
    blend_biome_colors,
    get_colormap_uv,
    TINT_TYPE_GRASS,
    TINT_TYPE_FOLIAGE,
    TINT_TYPE_WATER,
    TINT_TYPE_HARDCODED,
    TINT_TYPE_DRY_FOLIAGE,
)


def ensure_face_attribute(mesh: bpy.types.Mesh, name: str, data_type: str = "FLOAT") -> bpy.types.Attribute:
    """Ensure a face attribute of the given type exists on the mesh, recreating it if invalid."""
    attr = mesh.attributes.get(name)
    if attr and (attr.domain != "FACE" or attr.data_type != data_type or len(attr.data) != len(mesh.polygons)):
        mesh.attributes.remove(attr)
        attr = None
    return attr or mesh.attributes.new(name=name, type=data_type, domain="FACE")


def read_face_vector_attribute(mesh: bpy.types.Mesh, name: str, poly_idx: int, default: tuple = (0.0, 0.0, 0.0)) -> tuple:
    """Read a 3D float vector face attribute value at the given polygon index."""
    attr = mesh.attributes.get(name)
    if attr and attr.domain == "FACE" and attr.data_type == "FLOAT_VECTOR" and poly_idx < len(attr.data):
        return tuple(attr.data[poly_idx].vector)
    return default


def read_face_float_attribute(mesh: bpy.types.Mesh, name: str, poly_idx: int, default: float = 0.0) -> float:
    """Read a scalar float face attribute value at the given polygon index."""
    attr = mesh.attributes.get(name)
    if attr and attr.domain == "FACE" and attr.data_type == "FLOAT" and poly_idx < len(attr.data):
        return float(attr.data[poly_idx].value)
    return default


def read_face_string_attribute(mesh: bpy.types.Mesh, name: str) -> list[str]:
    """Read a FACE string attribute in bulk instead of crossing Blender's RNA API per face."""
    attr = mesh.attributes.get(name)
    if not attr or attr.domain != "FACE" or attr.data_type != "STRING":
        return [""] * len(mesh.polygons)

    values = []
    for item in attr.data:
        value = item.value
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        values.append(str(value).strip())
    return values if len(values) == len(mesh.polygons) else [""] * len(mesh.polygons)


def read_face_tiling(mesh: bpy.types.Mesh, poly_idx: int) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Read UV tiling scale and location from packed FLOAT_COLOR or separate legacy attributes."""
    packed = mesh.attributes.get(ATTR_UV_TILING_TRANSFORM)
    if packed and packed.domain == "FACE" and packed.data_type == "FLOAT_COLOR" and poly_idx < len(packed.data):
        r, g, b, a = packed.data[poly_idx].color
        return (r, g, 1.0), (b, a, 0.0)
    return (
        read_face_vector_attribute(mesh, ATTR_UV_TILING_SCALE, poly_idx, (1.0, 1.0, 1.0)),
        read_face_vector_attribute(mesh, ATTR_UV_TILING_LOCATION, poly_idx, (0.0, 0.0, 0.0)),
    )


def compute_biome_tint_attributes(
    num_polygons: int,
    poly_tint_map: dict[int, dict],
    biome_preset: Union[str, list[tuple[str, float]]] = "PLAINS",
) -> tuple[list, list, list]:
    """
    Compute packed tint weights, colors, and colormap UV coordinates for all polygons based on tint data and biome.
    biome_preset can be a single biome preset name (e.g. 'PLAINS') or a list of weighted biomes
    for smooth biome transition interpolation (e.g. [('PLAINS', 0.6), ('FOREST', 0.4)]).
    Returns (packed_tint_data, tint_colors, colormap_uvs).
    """
    tint_weights = [0.0] * num_polygons
    base_tint_weights = [1.0] * num_polygons
    overlay_tint_weights = [1.0] * num_polygons
    tint_colors = [(1.0, 1.0, 1.0, 1.0)] * num_polygons
    hardcoded_colors = [(1.0, 1.0, 1.0, 1.0)] * num_polygons
    use_hardcodeds = [0.0] * num_polygons

    is_multi_biome = isinstance(biome_preset, list)
    if not is_multi_biome:
        biome_colors = get_biome_colors(str(biome_preset))
        grass_col = biome_colors["grass_linear"]
        foliage_col = biome_colors["foliage_linear"]
        dry_foliage_col = biome_colors["dry_foliage_linear"]
        water_col = biome_colors["water_linear"]
        temp = float(biome_colors.get("temperature", 0.8))
        hum = float(biome_colors.get("humidity", 0.4))
        u, v = get_colormap_uv(temp, hum)
        colormap_uvs = [(u, v, 0.0)] * num_polygons
    else:
        grass_col = blend_biome_colors(biome_preset, "grass")
        foliage_col = blend_biome_colors(biome_preset, "foliage")
        dry_foliage_col = blend_biome_colors(biome_preset, "dry_foliage")
        water_col = blend_biome_colors(biome_preset, "water")
        total_w = sum(w for _, w in biome_preset)
        if total_w > 0:
            avg_u = 0.0
            avg_v = 0.0
            for b_name, w in biome_preset:
                b_info = get_biome_colors(b_name)
                t = float(b_info.get("temperature", 0.8))
                h = float(b_info.get("humidity", 0.4))
                bu, bv = get_colormap_uv(t, h)
                avg_u += bu * (w / total_w)
                avg_v += bv * (w / total_w)
            colormap_uvs = [(avg_u, avg_v, 0.0)] * num_polygons
        else:
            colormap_uvs = [(0.2, 0.32, 0.0)] * num_polygons

    has_custom_grass = bool(biome_colors.get("has_custom_grass", False)) if not is_multi_biome else False
    has_custom_foliage = bool(biome_colors.get("has_custom_foliage", False)) if not is_multi_biome else False
    has_custom_dry_foliage = bool(biome_colors.get("has_custom_dry_foliage", False)) if not is_multi_biome else False

    for poly_idx, tint_info in poly_tint_map.items():
        if not tint_info:
            continue
        tw = float(tint_info.get("default_tint_weight", tint_info.get("tint_weight", 0.0)))
        tint_weights[poly_idx] = tw
        base_tint_weights[poly_idx] = float(tint_info.get("default_base_tint_weight", tint_info.get("base_tint_weight", 1.0)))
        overlay_tint_weights[poly_idx] = float(tint_info.get("default_overlay_tint_weight", tint_info.get("overlay_tint_weight", 1.0)))
        tt = int(tint_info.get("tint_type", 0))
        is_hc = bool(tint_info.get("is_hardcoded", False))

        has_custom = False
        if not is_multi_biome:
            if tt == TINT_TYPE_GRASS:
                has_custom = has_custom_grass
            elif tt == TINT_TYPE_FOLIAGE:
                has_custom = has_custom_foliage
            elif tt == TINT_TYPE_DRY_FOLIAGE:
                has_custom = has_custom_dry_foliage

        tint_type_val = float(TINT_TYPE_HARDCODED if (is_hc or has_custom) else tt)
        use_hardcodeds[poly_idx] = tint_type_val
        hc_c = tint_info.get("hardcoded_color")
        if hc_c:
            hardcoded_colors[poly_idx] = tuple(hc_c)
        if tt == TINT_TYPE_GRASS:
            tint_colors[poly_idx] = grass_col
        elif tt == TINT_TYPE_FOLIAGE:
            tint_colors[poly_idx] = foliage_col
        elif tt == TINT_TYPE_DRY_FOLIAGE:
            tint_colors[poly_idx] = dry_foliage_col
        elif tt == TINT_TYPE_WATER:
            tint_colors[poly_idx] = water_col
        elif tt == TINT_TYPE_HARDCODED or is_hc:
            tint_colors[poly_idx] = hardcoded_colors[poly_idx]
        else:
            tint_colors[poly_idx] = (1.0, 1.0, 1.0, 1.0)

    packed_tint_data = list(zip(base_tint_weights, overlay_tint_weights, tint_weights, use_hardcodeds))
    return packed_tint_data, tint_colors, colormap_uvs


def apply_biome_tint_attributes(
    mesh: bpy.types.Mesh,
    packed_tint_data: list,
    tint_colors: list,
    colormap_uvs: Optional[list] = None,
) -> None:
    """Write computed biome tint data, color vectors, and optional colormap UVs to mesh face attributes."""
    ensure_face_attribute(mesh, ATTR_BIOME_TINT_DATA, "FLOAT_COLOR").data.foreach_set(
        "color", [c for val in packed_tint_data for c in val]
    )
    ensure_face_attribute(mesh, ATTR_BIOME_TINT_COLOR, "FLOAT_COLOR").data.foreach_set(
        "color", [c for val in tint_colors for c in val]
    )
    if colormap_uvs is not None:
        from ..constants import ATTR_COLORMAP_UV
        ensure_face_attribute(mesh, ATTR_COLORMAP_UV, "FLOAT_VECTOR").data.foreach_set(
            "vector", [v for val in colormap_uvs for v in (val[0], val[1], val[2] if len(val) > 2 else 0.0)]
        )


def cleanup_legacy_mesh_attributes(mesh: bpy.types.Mesh) -> None:
    """Remove obsolete legacy split and helper attributes from the mesh."""
    for attr_name in LEGACY_SPLIT_ATTR_NAMES:
        attr = mesh.attributes.get(attr_name)
        if attr:
            mesh.attributes.remove(attr)


def cleanup_all_atlas_attributes(mesh: bpy.types.Mesh) -> None:
    """Remove all Atlas-mode and animation driving attributes from the mesh (used in Standalone mode)."""
    cleanup_legacy_mesh_attributes(mesh)
    for attr_name in ANIM_AND_ATLAS_ATTR_NAMES:
        attr = mesh.attributes.get(attr_name)
        if attr:
            mesh.attributes.remove(attr)
    if "mtk:atlas_mapping" in mesh:
        del mesh["mtk:atlas_mapping"]
    if "mtk_atlas_mapping" in mesh:
        del mesh["mtk_atlas_mapping"]


def cleanup_object_anim_properties(obj: bpy.types.Object) -> None:
    """Remove legacy object-level animation properties."""
    for prop in (
        "mtk_anim_total_frames", "mtk_anim_frametime",
        "mtk_anim_interpolate", "mtk_anim_frame_width",
        "mtk_anim_frame_height",
    ):
        if prop in obj:
            del obj[prop]
