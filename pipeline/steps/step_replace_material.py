"""
Material replacement and reconstruction pipeline step.
Supports Standalone and Texture Atlas generation modes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Union, Optional
import bpy

from ..progress import ProgressUpdate
from ..step import PipelineStep, StepResult
from ...utils.materials import (
    ZipResourcePack,
    get_cache_dir,
    rebuild_material,
    extract_material_texture_keys,
    detect_material_mode,
    get_atlas_mapping_from_material,
    get_atlas_mapping_from_mesh,
    write_provenance_schema,
    extract_face_texture_info,
    canonical_texture_key,
    split_texture_key,
    material_source_origin,
    write_face_source_provenance,
    get_face_source_origin,
    get_face_source_texture_key,
    is_ice_cube_internal_face_material,
    ATLAS_FORMAT_VERSION,
    AtlasGenerator,
    build_atlas_chunk_materials,
    remap_uv_coordinate,
    remap_uv_to_local,
    remap_local_to_target_uv,
    get_material_animation_info,
    get_texture_info_animation_info,
    ATTR_ATLAS_CHUNK_ID,
    ATTR_ATLAS_TEXTURE_ID,
    ATTR_FACE_MATERIAL_ID,
    ATTR_UV_ROTATION,
    ATTR_UV_TILING_SCALE,
    ATTR_UV_TILING_LOCATION,
    ATTR_UV_TILING_TRANSFORM,
    ATTR_BIOME_TINT_DATA,
    ATTR_BIOME_TINT_COLOR,
    ATTR_ANIM_TIMING,
    ATTR_ANIM_FRAME_SIZE,
    ANIM_AND_ATLAS_ATTR_NAMES,
    LEGACY_SPLIT_ATTR_NAMES,
    BiomeResolver,
    get_biome_colors,
    TINT_TYPE_NONE,
    TINT_TYPE_GRASS,
    TINT_TYPE_FOLIAGE,
    TINT_TYPE_WATER,
    TINT_TYPE_HARDCODED,
)
from ...utils.system import has_pillow
from ...utils.mesh import (
    straighten_face_uv, normalize_face_uv_for_atlas_tiling,
    face_uv_requires_atlas_tiling, restore_atlas_tiling_uv,
)


def _ensure_face_attribute(mesh: bpy.types.Mesh, name: str, data_type: str = "FLOAT") -> bpy.types.Attribute:
    attr = mesh.attributes.get(name)
    if attr and (attr.domain != "FACE" or attr.data_type != data_type or len(attr.data) != len(mesh.polygons)):
        mesh.attributes.remove(attr)
        attr = None
    return attr or mesh.attributes.new(name=name, type=data_type, domain="FACE")


def _read_face_vector_attribute(mesh: bpy.types.Mesh, name: str, poly_idx: int, default: tuple = (0.0, 0.0, 0.0)) -> tuple:
    attr = mesh.attributes.get(name)
    if attr and attr.domain == "FACE" and attr.data_type == "FLOAT_VECTOR" and poly_idx < len(attr.data):
        return tuple(attr.data[poly_idx].vector)
    return default


def _read_face_float_attribute(mesh: bpy.types.Mesh, name: str, poly_idx: int, default: float = 0.0) -> float:
    attr = mesh.attributes.get(name)
    if attr and attr.domain == "FACE" and attr.data_type == "FLOAT" and poly_idx < len(attr.data):
        return float(attr.data[poly_idx].value)
    return default


def _read_face_tiling(mesh: bpy.types.Mesh, poly_idx: int) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    packed = mesh.attributes.get(ATTR_UV_TILING_TRANSFORM)
    if packed and packed.domain == "FACE" and packed.data_type == "FLOAT_COLOR" and poly_idx < len(packed.data):
        r, g, b, a = packed.data[poly_idx].color
        return (r, g, 1.0), (b, a, 0.0)
    return (
        _read_face_vector_attribute(mesh, ATTR_UV_TILING_SCALE, poly_idx, (1.0, 1.0, 1.0)),
        _read_face_vector_attribute(mesh, ATTR_UV_TILING_LOCATION, poly_idx, (0.0, 0.0, 0.0)),
    )


def _build_old_mappings(obj: bpy.types.Object, mesh: bpy.types.Mesh) -> dict:
    old_mappings = {}
    for slot in obj.material_slots:
        if slot.material and slot.material not in old_mappings:
            old_mappings[slot.material] = (
                get_atlas_mapping_from_material(slot.material)
                or get_atlas_mapping_from_mesh(mesh)
            )
    return old_mappings


def _compute_biome_tint_attributes(
    num_polygons: int,
    poly_tint_map: dict[int, dict],
    biome_preset: str,
) -> tuple[list, list]:
    tint_weights = [0.0] * num_polygons
    base_tint_weights = [1.0] * num_polygons
    overlay_tint_weights = [1.0] * num_polygons
    tint_colors = [(1.0, 1.0, 1.0, 1.0)] * num_polygons
    hardcoded_colors = [(1.0, 1.0, 1.0, 1.0)] * num_polygons
    use_hardcodeds = [0.0] * num_polygons
    biome_colors = get_biome_colors(biome_preset)

    for poly_idx, tint_info in poly_tint_map.items():
        if not tint_info:
            continue
        tw = float(tint_info.get("default_tint_weight", tint_info.get("tint_weight", 0.0)))
        tint_weights[poly_idx] = tw
        base_tint_weights[poly_idx] = float(tint_info.get("default_base_tint_weight", tint_info.get("base_tint_weight", 1.0)))
        overlay_tint_weights[poly_idx] = float(tint_info.get("default_overlay_tint_weight", tint_info.get("overlay_tint_weight", 1.0)))
        tt = int(tint_info.get("tint_type", 0))
        is_hc = bool(tint_info.get("is_hardcoded", False))
        use_hardcodeds[poly_idx] = 1.0 if is_hc else 0.0
        hc_c = tint_info.get("hardcoded_color")
        if hc_c:
            hardcoded_colors[poly_idx] = tuple(hc_c)
        if tt == TINT_TYPE_GRASS:
            tint_colors[poly_idx] = biome_colors["grass_linear"]
        elif tt == TINT_TYPE_FOLIAGE:
            tint_colors[poly_idx] = biome_colors["foliage_linear"]
        elif tt == TINT_TYPE_WATER:
            tint_colors[poly_idx] = biome_colors["water_linear"]
        elif tt == TINT_TYPE_HARDCODED:
            tint_colors[poly_idx] = hardcoded_colors[poly_idx]
        else:
            tint_colors[poly_idx] = (1.0, 1.0, 1.0, 1.0)

    packed_tint_data = list(zip(base_tint_weights, overlay_tint_weights, tint_weights, use_hardcodeds))
    return packed_tint_data, tint_colors


def _apply_biome_tint_attributes(mesh: bpy.types.Mesh, packed_tint_data: list, tint_colors: list) -> None:
    _ensure_face_attribute(mesh, ATTR_BIOME_TINT_DATA, "FLOAT_COLOR").data.foreach_set(
        "color", [c for val in packed_tint_data for c in val]
    )
    _ensure_face_attribute(mesh, ATTR_BIOME_TINT_COLOR, "FLOAT_COLOR").data.foreach_set(
        "color", [c for val in tint_colors for c in val]
    )


def _cleanup_legacy_mesh_attributes(mesh: bpy.types.Mesh) -> None:
    for attr_name in LEGACY_SPLIT_ATTR_NAMES:
        attr = mesh.attributes.get(attr_name)
        if attr:
            mesh.attributes.remove(attr)


def _cleanup_object_anim_properties(obj: bpy.types.Object) -> None:
    for prop in (
        "mtk_anim_total_frames", "mtk_anim_frametime",
        "mtk_anim_interpolate", "mtk_anim_frame_width",
        "mtk_anim_frame_height",
    ):
        if prop in obj:
            del obj[prop]


def _write_yefira_point_atlas_attributes(mesh: bpy.types.Mesh, mapping: dict) -> None:
    """Fill Yefira's face atlas attributes directly from Mozi's mapping."""
    state_attr = mesh.attributes.get("block_state")
    if not state_attr or state_attr.domain != 'POINT':
        return

    by_name = {
        str(entry.get("name", "")).removeprefix("minecraft:").removeprefix("block/"): entry
        for entry in mapping.get("materials", [])
        if entry.get("name")
    }
    texture_locations = mapping.get("textures", {})

    def texture_location(block_name: str) -> dict:
        """Find a flat texture entry when a block model has no face table."""
        for key in (block_name, f"minecraft:{block_name}", f"minecraft:block/{block_name}"):
            location = texture_locations.get(key)
            if isinstance(location, dict):
                return location
        return {}

    def texture_only_faces(block_name: str) -> dict:
        """Derive standard cube faces from a texture-only atlas mapping.

        SPBR maps usually retain individual textures but not Minecraft model
        JSON.  Normal meshes still work because their source polygons carry
        the exact texture key; Yefira has only a logical block state, so make
        that bridge here.  A differentiated model face table remains the
        authoritative source whenever present.
        """
        base = texture_location(block_name)
        side = texture_location(f"{block_name}_side") or base
        top = texture_location(f"{block_name}_top") or texture_location(f"{block_name}_end") or side
        bottom = texture_location(f"{block_name}_bottom") or texture_location(f"{block_name}_end") or top
        if block_name == "grass_block":
            bottom = texture_location("dirt") or bottom
        named_variants = any(texture_location(f"{block_name}{suffix}") for suffix in ("_side", "_top", "_bottom", "_end"))
        if not named_variants or not side or not top or not bottom:
            return {}
        return {"+X": side, "-X": side, "+Y": top, "-Y": bottom, "+Z": side, "-Z": side}

    def mapping_names(state: str) -> tuple[str, ...]:
        """Resolve stateful generated models before generic texture fallback."""
        block_name, _, raw_props = state.partition("[")
        block_name = block_name.removeprefix("minecraft:").removeprefix("block/")
        names = []
        if block_name.endswith("_door"):
            props = {
                key.strip(): value.strip().rstrip("]")
                for pair in raw_props.rstrip("]").split(",") if "=" in pair
                for key, value in [pair.split("=", 1)]
            }
            names.append(f"{block_name}_{'top' if props.get('half') == 'upper' else 'bottom'}")
        names.append(block_name)
        return tuple(names)
    face_specs = (
        ("east", "+X"), ("west", "-X"), ("top", "+Y"),
        ("bottom", "-Y"), ("south", "+Z"), ("north", "-Z"),
    )
    values = {name: {"tile": [], "chunk": [], "texture": [], "tint_data": []} for name, _ in face_specs}
    material_ids = []

    for item in state_attr.data:
        state = item.value.decode("utf-8", errors="replace") if isinstance(item.value, bytes) else str(item.value)
        names = mapping_names(state)
        entry = next((by_name[name] for name in names if name in by_name), None)
        material_ids.append(int(entry.get("material_id", 0)) if entry else 0)
        faces = entry.get("faces", {}) if entry else {}
        fallback_location = next((texture_location(name) for name in names if texture_location(name)), {})
        # In a texture-only pack atlas_generator emits a uniform material row
        # for e.g. oak_log.  Replace that row only when the texture table
        # proves that side/top/end components exist; do not override actual
        # multi-face model data.
        primary_name = names[0]
        explicit_locations = [faces.get(mapping_face) for _, mapping_face in face_specs]
        has_differentiated_faces = len({loc.get("texture_key") for loc in explicit_locations if isinstance(loc, dict)}) > 1
        derived_faces = texture_only_faces(primary_name) if not has_differentiated_faces else {}
        for attr_face, mapping_face in face_specs:
            # Vanilla generated models such as stained glass are represented
            # by a material entry with null faces, while their atlas location
            # is correctly present in ``textures``.  A missing face is not a
            # valid request for texture zero.
            location = derived_faces.get(mapping_face) or faces.get(mapping_face) or fallback_location
            values[attr_face]["tile"].append((
                float(location.get("tile_column", 0)),
                float(location.get("tile_row", 0)), 0.0,
            ))
            values[attr_face]["chunk"].append(int(location.get("chunk_id", 0)))
            values[attr_face]["texture"].append(int(location.get("texture_id", 0)))
            values[attr_face]["tint_data"].append((
                float(location.get("default_base_tint_weight", 0.0)),
                float(location.get("default_overlay_tint_weight", 0.0)),
                float(location.get("default_tint_weight", 0.0)),
                1.0 if location.get("is_hardcoded", False) else 0.0,
            ))

    def point_attr(name: str, data_type: str):
        attr = mesh.attributes.get(name)
        if attr and (attr.domain != 'POINT' or attr.data_type != data_type or len(attr.data) != len(state_attr.data)):
            mesh.attributes.remove(attr)
            attr = None
        return attr or mesh.attributes.new(name=name, type=data_type, domain='POINT')

    point_attr("mtk_material_id", 'INT').data.foreach_set('value', material_ids)
    for face, _ in face_specs:
        tile_attr = point_attr(f"mtk_tile_{face}", 'FLOAT_VECTOR')
        tile_attr.data.foreach_set('vector', [component for tile in values[face]["tile"] for component in tile])
        point_attr(f"mtk_chunk_{face}", 'INT').data.foreach_set('value', values[face]["chunk"])
        point_attr(f"mtk_texture_{face}", 'INT').data.foreach_set('value', values[face]["texture"])
        tint_attr = point_attr(f"mtk_tint_data_{face}", 'FLOAT_COLOR')
        tint_attr.data.foreach_set('color', [component for value in values[face]["tint_data"] for component in value])


def _is_yefira_world(obj: bpy.types.Object) -> bool:
    """Identify the explicit Yefira point-cloud material variant.

    A polygon-free mesh is not sufficient: other procedural objects can have
    no base polygons and must retain the normal MoziToolKit material contract.
    """
    if not obj or obj.type != 'MESH' or obj.name != "Yefira_World":
        return False
    state_attr = obj.data.attributes.get("block_state")
    if not state_attr or state_attr.domain != 'POINT':
        return False
    return any(mod.type == 'NODES' and mod.name == 'Yefira_WorldModifier' for mod in obj.modifiers)



def name_replaced_material(mat: bpy.types.Material, texture_info: dict, pack: ZipResourcePack) -> None:
    """Assign a compact visible identity and durable provenance metadata."""
    namespace = texture_info["namespace"]
    texture_name = texture_info["texture_name"]
    full_hash = pack.pack_hash
    mat.name = f"mtk:{namespace}:{texture_name}:{full_hash[:12]}"
    mat["mtk:source_namespace"] = namespace
    mat["mtk:source_texture"] = texture_name
    mat["mtk:material_id"] = f"{namespace}:{texture_name}"
    mat["mtk:pack_hash"] = full_hash
    mat["mtk:pack_hash_short"] = full_hash[:12]
    write_provenance_schema(mat)


def find_existing_replacement(texture_info: dict, pack: ZipResourcePack) -> bpy.types.Material | None:
    """Find an existing material datablock matching the exact pack hash and texture key."""
    namespace = texture_info["namespace"]
    texture_name = texture_info["texture_name"]
    for material in bpy.data.materials:
        if (
            material.get("mtk:source_namespace") == namespace
            and material.get("mtk:source_texture") == texture_name
            and material.get("mtk:pack_hash") == pack.pack_hash
        ):
            return material
    return None


def apply_mesh_face_materials_and_provenance(
    mesh: bpy.types.Mesh,
    face_materials: list[bpy.types.Material | None],
    source_keys: list[str],
    source_origins: list[str],
) -> None:
    """Consolidate material slots and write back durable face-level provenance."""
    unique_materials: list[bpy.types.Material] = []
    for mat in face_materials:
        if mat is not None and mat not in unique_materials:
            unique_materials.append(mat)

    if unique_materials:
        mesh.materials.clear()
        for mat in unique_materials:
            mesh.materials.append(mat)
        mat_slots = {m: idx for idx, m in enumerate(unique_materials)}
        for poly_idx, mat in enumerate(face_materials):
            if mat is not None:
                mesh.polygons[poly_idx].material_index = mat_slots[mat]
            else:
                # Clearing slots invalidates every prior index.  A face with
                # no replacement must point at a valid slot rather than a
                # dangling material index.
                mesh.polygons[poly_idx].material_index = 0

    write_face_source_provenance(mesh, source_keys, source_origins)


def remap_polygon_loop_uvs(
    polygon: bpy.types.MeshPolygon,
    uv_layer: bpy.types.MeshUVLoopLayer,
    orig_mode: str,
    old_loc: Optional[dict] = None,
    old_chunk: Optional[dict] = None,
    old_anim_info: Optional[dict] = None,
    target_location: Optional[dict] = None,
    target_chunk: Optional[dict] = None,
    target_anim_info: Optional[dict] = None,
) -> None:
    """Transform all loop UVs for a single polygon from source space to target space."""
    for loop_index in polygon.loop_indices:
        uv = uv_layer.data[loop_index].uv
        uv.x, uv.y = remap_uv_coordinate(
            uv.x, uv.y,
            orig_mode=orig_mode,
            old_loc=old_loc,
            old_chunk=old_chunk,
            old_anim_info=old_anim_info,
            target_location=target_location,
            target_chunk=target_chunk,
            target_anim_info=target_anim_info,
        )


class StepReplaceMaterial(PipelineStep):
    """
    Modular PipelineStep for replacing and reconstructing materials from a Minecraft Java Resource Pack.
    Supports both Standalone and Atlas material generation modes.
    """

    name = "replace_material"
    description = "Replace and reconstruct materials from Minecraft Java Resource Pack"

    def execute_iter(self, pipeline_context) -> Iterator[Union[ProgressUpdate, StepResult]]:
        zip_path = pipeline_context.get_param("zip_path")
        pack_textures = pipeline_context.get_param("pack_textures", True)
        use_cache = pipeline_context.get_param("use_cache", True)
        material_mode = pipeline_context.get_param("material_mode", "STANDALONE")

        if not zip_path or not Path(zip_path).exists():
            yield StepResult.failed("Resource pack ZIP file not specified or found.")
            return

        target_objects = pipeline_context.target_objects
        if not target_objects:
            yield StepResult.failed("No objects selected for material replacement.")
            return

        yield ProgressUpdate(0.05, 1.0, "Loading Minecraft resource pack...")

        if pipeline_context.is_cancelled:
            yield StepResult.cancelled("Material replacement cancelled by user.")
            return

        try:
            pack = ZipResourcePack(zip_path, use_cache=use_cache)
        except Exception as e:
            yield StepResult.failed(f"Failed to load resource pack: {e}")
            return

        valid_objects = [o for o in target_objects if o and o.type == "MESH" and o.data and o.material_slots]
        if not valid_objects:
            yield StepResult.failed("No valid mesh objects with material slots found.")
            return

        if not has_pillow():
            yield StepResult.failed(
                "Material replacement requires 'Pillow' (PIL) module. Please ensure Pillow or extension wheels are installed."
            )
            return

        # The legacy unified-atlas builder does not record a per-face chunk
        # and texture location.  Its UVs therefore cannot be inverted safely;
        # fail loudly instead of reporting a successful no-op or corrupting UVs.
        for obj in valid_objects:
            mesh = obj.data
            chunk_attr = mesh.attributes.get(ATTR_ATLAS_CHUNK_ID)
            texture_attr = mesh.attributes.get(ATTR_ATLAS_TEXTURE_ID)
            for poly_idx, poly in enumerate(mesh.polygons):
                if poly.material_index >= len(obj.material_slots):
                    continue
                mat = obj.material_slots[poly.material_index].material
                if detect_material_mode(mat) != "ATLAS_UNIFIED":
                    continue
                has_location = (
                    chunk_attr and texture_attr
                    and poly_idx < len(chunk_attr.data) and poly_idx < len(texture_attr.data)
                    and chunk_attr.data[poly_idx].value >= 0
                    and texture_attr.data[poly_idx].value >= 0
                )
                if not has_location:
                    yield StepResult.failed(
                        "Unified Atlas material lacks per-face provenance and cannot be converted safely. "
                        "Rebuild it as Atlas Chunk material first."
                    )
                    return

        biome_preset = pipeline_context.get_param("biome_preset", "PLAINS")

        if material_mode == "ATLAS":
            yield from self._execute_atlas_mode_iter(pipeline_context, pack, valid_objects, pack_textures, biome_preset=biome_preset)
        else:
            yield from self._execute_standalone_mode_iter(pipeline_context, pack, valid_objects, pack_textures, biome_preset=biome_preset)

    def _execute_atlas_mode_iter(
        self, pipeline_context, pack: ZipResourcePack, valid_objects: list, pack_textures: bool, biome_preset: str = "PLAINS"
    ) -> Iterator[Union[ProgressUpdate, StepResult]]:
        """Iteratively execute material replacement in Atlas Mode with fine-grained progress."""
        cache_root = get_cache_dir()
        atlas_dir = cache_root / pack.pack_hash
        mapping_path = atlas_dir / "atlas_mapping.json"

        yield ProgressUpdate(0.10, 1.0, "Checking Atlas texture cache...")

        if pipeline_context.is_cancelled:
            yield StepResult.cancelled("Material replacement cancelled by user.")
            return

        cache_is_current = False
        if mapping_path.exists():
            try:
                with open(mapping_path, "r", encoding="utf-8") as fp:
                    cached_mapping = json.load(fp)
                    cache_is_current = (
                        cached_mapping.get("format_version") == ATLAS_FORMAT_VERSION
                        and bool(cached_mapping.get("chunks"))
                        and bool(cached_mapping.get("textures"))
                    )
            except (OSError, json.JSONDecodeError):
                cache_is_current = False

        if not cache_is_current:
            if not has_pillow():
                yield StepResult.failed(
                    "Atlas Mode requires 'Pillow' (PIL) module. Please ensure Pillow or extension wheels are installed."
                )
                return
            pipeline_context.report("INFO", f"Generating Atlas texture for pack hash {pack.pack_hash[:12]}...")
            try:
                gen = AtlasGenerator(pack.extract_dir)
                for frac, msg, _res in gen.build_iter(atlas_dir):
                    if pipeline_context.is_cancelled:
                        yield StepResult.cancelled("Material replacement cancelled by user.")
                        return
                    # Map Atlas build progress (0.0 - 1.0) into pipeline progress range (0.15 - 0.35)
                    atlas_pct = 0.15 + 0.20 * frac
                    yield ProgressUpdate(atlas_pct, 1.0, f"Atlas: {msg}")
            except Exception as e:
                yield StepResult.failed(f"Failed to generate Atlas texture: {e}")
                return

        yield ProgressUpdate(0.35, 1.0, "Reading Atlas mapping and required chunks...")

        with open(mapping_path, "r", encoding="utf-8") as fp:
            mapping_data = json.load(fp)

        if not mapping_data.get("chunks") or not mapping_data.get("textures"):
            yield StepResult.failed(
                "Atlas generation produced no usable texture chunks. Check the resource pack and Pillow installation."
            )
            return

        texture_map = {}
        for name, location in mapping_data.get("textures", {}).items():
            if location is None:
                continue
            namespace, texture_name = split_texture_key(location.get("texture_key", name))
            texture_map[canonical_texture_key(namespace, texture_name)] = location
            legacy_namespace, legacy_texture = split_texture_key(name)
            texture_map.setdefault(canonical_texture_key(legacy_namespace, legacy_texture), location)

        chunks_by_id = {int(chunk["chunk_id"]): chunk for chunk in mapping_data.get("chunks", [])}

        # Collect required chunks
        required_chunk_ids = set()
        # Old Atlas materials store a large JSON mapping on their node tree.
        # Do not parse it again for every polygon: a dense imported world can
        # contain millions of faces and this phase otherwise appears to hang
        # at 35%.
        mapping_by_material = {}
        total_faces = sum(len(obj.data.polygons) for obj in valid_objects)
        scanned_faces = 0
        for obj in valid_objects:
            mesh = obj.data
            for poly_idx, poly in enumerate(mesh.polygons):
                scanned_faces += 1
                # Yield periodically so very large legacy worlds remain
                # cancellable and Blender's UI does not look frozen while
                # required chunk IDs are collected.
                if scanned_faces % 10_000 == 0:
                    if pipeline_context.is_cancelled:
                        yield StepResult.cancelled("Material replacement cancelled by user.")
                        return
                    progress = 0.35 + 0.08 * (scanned_faces / max(1, total_faces))
                    yield ProgressUpdate(progress, 1.0, f"Reading Atlas attributes: {scanned_faces:,}/{total_faces:,} faces")
                if poly.material_index >= len(obj.material_slots):
                    continue
                slot_mat = obj.material_slots[poly.material_index].material
                if not slot_mat:
                    continue
                if slot_mat not in mapping_by_material:
                    mapping_by_material[slot_mat] = (
                        get_atlas_mapping_from_material(slot_mat)
                        or get_atlas_mapping_from_mesh(mesh)
                    )
                namespace, candidates, _old_loc = extract_face_texture_info(
                    mesh, poly_idx, slot_mat, mapping_by_material[slot_mat]
                )
                for cand in candidates:
                    loc = texture_map.get(canonical_texture_key(namespace, cand))
                    if loc is not None:
                        required_chunk_ids.add(int(loc["chunk_id"]))
                        break

        # If no polygon faces were scanned (e.g. Point Cloud object or procedural Geometry Nodes world),
        # ensure static chunk 0 (or all static chunks) are generated.
        if not required_chunk_ids:
            static_chunks = [int(c["chunk_id"]) for c in mapping_data.get("chunks", []) if c.get("kind") == "static"]
            required_chunk_ids = set(static_chunks) if static_chunks else {0}

        yefira_objects = [obj for obj in valid_objects if _is_yefira_world(obj)]

        yield ProgressUpdate(0.45, 1.0, f"Building {len(required_chunk_ids)} Atlas chunk material(s)...")

        if pipeline_context.is_cancelled:
            yield StepResult.cancelled("Material replacement cancelled by user.")
            return

        atlas_materials = build_atlas_chunk_materials(
            atlas_dir,
            pack_hash=pack.pack_hash,
            pack_textures=pack_textures,
            chunk_ids=required_chunk_ids,
        )
        # A Yefira world is a distinct material variant.  It must never reuse
        # the normal UV-layer materials above because it supplies UVMap from
        # evaluated Geometry Nodes instead.
        yefira_atlas_materials = {}
        if yefira_objects:
            yefira_atlas_materials = build_atlas_chunk_materials(
                atlas_dir,
                pack_hash=pack.pack_hash,
                pack_textures=pack_textures,
                chunk_ids={int(chunk["chunk_id"]) for chunk in mapping_data.get("chunks", [])},
                uv_attribute="UVMap",
            )

        session_materials = {}

        def get_or_create_replacement_material(texture_info):
            texture_key = (texture_info["namespace"], texture_info["texture_name"])
            canonical_mat = find_existing_replacement(texture_info, pack) or session_materials.get(texture_key)
            if canonical_mat:
                return canonical_mat, False

            mat_name = f"mtk:{texture_info['namespace']}:{texture_info['texture_name']}"
            mat = bpy.data.materials.new(name=mat_name)
            if not rebuild_material(mat, texture_info, pack_textures=pack_textures, pack_hash=pack.pack_hash):
                bpy.data.materials.remove(mat)
                return None, False

            name_replaced_material(mat, texture_info, pack)
            session_materials[texture_key] = mat
            return mat, True

        replaced_objects = 0
        total_objs = len(valid_objects)

        for obj_idx, obj in enumerate(valid_objects):
            if pipeline_context.is_cancelled:
                yield StepResult.cancelled("Material replacement cancelled by user.")
                return

            obj_progress = 0.50 + 0.45 * (obj_idx / max(1, total_objs))
            yield ProgressUpdate(obj_progress, 1.0, f"Remapping Atlas UVs: {obj.name} ({obj_idx + 1}/{total_objs})")

            mesh = obj.data

            # Yefira is the only supported point-cloud variant.  Treating any
            # polygon-free object this way would corrupt ordinary procedural
            # meshes, which still use the standard UV material contract.
            if _is_yefira_world(obj):
                primary_mat = yefira_atlas_materials.get(0) or (list(yefira_atlas_materials.values())[0] if yefira_atlas_materials else None)
                if primary_mat:
                    # Chunk IDs are the Geometry Nodes material indices.  Give
                    # the point-cloud a dense, deterministic slot table rather
                    # than discarding every atlas chunk except the first one.
                    obj.data.materials.clear()
                    max_chunk_id = max(yefira_atlas_materials)
                    for chunk_id in range(max_chunk_id + 1):
                        chunk_material = yefira_atlas_materials.get(chunk_id)
                        if chunk_material is None:
                            raise RuntimeError(f"Atlas mapping is missing material chunk {chunk_id}")
                        chunk_material.use_fake_user = True
                        obj.data.materials.append(chunk_material)

                    # Notify Yefira to refresh point cloud attributes and rebuild geometry nodes
                    try:
                        if hasattr(bpy.ops, "yefira") and hasattr(bpy.ops.yefira, "rebuild_world"):
                            bpy.ops.yefira.rebuild_world()
                        else:
                            import sys
                            if "yefira_blender.operators.main_operators" in sys.modules:
                                from yefira_blender.operators.main_operators import trigger_point_cloud_update
                                trigger_point_cloud_update(bpy.context)
                            elif "yefira_blender.nodes.world_tree" in sys.modules:
                                from yefira_blender.nodes.world_tree import setup_world_geometry_nodes
                                setup_world_geometry_nodes(obj)
                    except Exception:
                        pass

                    # Ensure ATTR_UV_TILING_TRANSFORM and ATTR_UV_ROTATION exist on point cloud mesh
                    if len(mesh.vertices) > 0:
                        tiling_attr = mesh.attributes.get(ATTR_UV_TILING_TRANSFORM)
                        if not tiling_attr or tiling_attr.data_type != 'FLOAT_COLOR' or len(tiling_attr.data) != len(mesh.vertices):
                            if tiling_attr:
                                mesh.attributes.remove(tiling_attr)
                            tiling_attr = mesh.attributes.new(name=ATTR_UV_TILING_TRANSFORM, type='FLOAT_COLOR', domain='POINT')
                        flat_colors = [c for _ in range(len(mesh.vertices)) for c in (1.0, 1.0, 0.0, 0.0)]
                        tiling_attr.data.foreach_set('color', flat_colors)

                        rot_attr = mesh.attributes.get(ATTR_UV_ROTATION)
                        if not rot_attr or rot_attr.data_type != 'FLOAT' or len(rot_attr.data) != len(mesh.vertices):
                            if rot_attr:
                                mesh.attributes.remove(rot_attr)
                            rot_attr = mesh.attributes.new(name=ATTR_UV_ROTATION, type='FLOAT', domain='POINT')
                        rot_attr.data.foreach_set('value', [0.0] * len(mesh.vertices))

                        # v5 Yefira GN reads atlas metadata as named geometry
                        # attributes.  They are intentionally not modifier
                        # inputs, so a user cannot desynchronise the atlas.
                        chunk_0 = chunks_by_id.get(0, {})
                        atlas_metadata = {
                            "mtk_atlas_width": float(chunk_0.get("width", primary_mat.get("mtk_atlas_width", 1024.0))),
                            "mtk_atlas_height": float(chunk_0.get("height", primary_mat.get("mtk_atlas_height", 1024.0))),
                            "mtk_tile_size": float(chunk_0.get("tile_size", primary_mat.get("mtk_tile_size", 16.0))),
                            "mtk_tiles_per_row": float(chunk_0.get("tiles_per_row", primary_mat.get("mtk_tiles_per_row", 64))),
                        }
                        for attr_name, attr_value in atlas_metadata.items():
                            attr = mesh.attributes.get(attr_name)
                            if not attr or attr.data_type != 'FLOAT' or attr.domain != 'POINT' or len(attr.data) != len(mesh.vertices):
                                if attr:
                                    mesh.attributes.remove(attr)
                                attr = mesh.attributes.new(name=attr_name, type='FLOAT', domain='POINT')
                            attr.data.foreach_set('value', [attr_value] * len(mesh.vertices))

                        _write_yefira_point_atlas_attributes(mesh, mapping_data)

                    # Atlas mapping/provenance belongs to the atlas materials.
                    # Writing it to a generated point-cloud data-block is both
                    # redundant and invalid for several Blender RNA wrappers.
                    replaced_objects += 1
                continue

            # Generic polygon-free objects retain the pre-Yefira behavior:
            # one normal atlas material and normal mesh-side provenance.
            if len(mesh.polygons) == 0:
                primary_mat = atlas_materials.get(0) or (list(atlas_materials.values())[0] if atlas_materials else None)
                if primary_mat:
                    if not obj.data.materials:
                        obj.data.materials.append(primary_mat)
                    else:
                        obj.data.materials[0] = primary_mat
                    for mod in obj.modifiers:
                        if mod.type == 'NODES' and mod.node_group:
                            for n in mod.node_group.nodes:
                                if n.type == 'SET_MATERIAL' and "Material" in n.inputs:
                                    n.inputs["Material"].default_value = primary_mat
                    mesh["mtk:atlas_mapping"] = json.dumps(mapping_data, separators=(",", ":"))
                    write_provenance_schema(mesh)
                    replaced_objects += 1
                continue

            uv_layer = mesh.uv_layers.active_render or mesh.uv_layers.active

            chunk_ids = [-1.0] * len(mesh.polygons)
            texture_ids = [-1.0] * len(mesh.polygons)
            uv_rotations = [0.0] * len(mesh.polygons)
            uv_tiling_scales = [(1.0, 1.0, 1.0)] * len(mesh.polygons)
            uv_tiling_locations = [(0.0, 0.0, 0.0)] * len(mesh.polygons)
            existing_rot_attr = mesh.attributes.get(ATTR_UV_ROTATION)
            if existing_rot_attr and len(existing_rot_attr.data) == len(mesh.polygons):
                uv_rotations = [float(item.value) for item in existing_rot_attr.data]

            anim_frames = [1.0] * len(mesh.polygons)
            anim_frametimes = [1.0] * len(mesh.polygons)
            anim_interps = [0.0] * len(mesh.polygons)
            anim_widths = [16.0] * len(mesh.polygons)
            anim_heights = [16.0] * len(mesh.polygons)

            poly_tint_map = {}

            resolved_locations = [None] * len(mesh.polygons)
            resolved_standalone = [None] * len(mesh.polygons)
            source_keys = [get_face_source_texture_key(mesh, idx) for idx in range(len(mesh.polygons))]
            source_origins = [get_face_source_origin(mesh, idx) for idx in range(len(mesh.polygons))]
            unresolved_faces = []
            skipped_faces = []
            face_materials = [
                obj.material_slots[poly.material_index].material
                if poly.material_index < len(obj.material_slots) else None
                for poly in mesh.polygons
            ]
            poly_updated = False

            old_mappings = _build_old_mappings(obj, mesh)

            for poly_idx, poly in enumerate(mesh.polygons):
                if poly.material_index >= len(obj.material_slots):
                    unresolved_faces.append(poly_idx)
                    continue
                orig_slot = obj.material_slots[poly.material_index]
                if not orig_slot.material:
                    unresolved_faces.append(poly_idx)
                    continue
                if is_ice_cube_internal_face_material(orig_slot.material):
                    skipped_faces.append(poly_idx)
                    continue

                old_mapping = old_mappings.get(orig_slot.material)
                orig_mode = detect_material_mode(orig_slot.material)
                namespace, candidates, old_loc = extract_face_texture_info(
                    mesh, poly_idx, orig_slot.material, old_mapping
                )

                new_location = None
                for candidate in candidates:
                    new_location = texture_map.get(canonical_texture_key(namespace, candidate))
                    if new_location is not None:
                        break

                if new_location is not None:
                    chunk_ids[poly_idx] = float(new_location["chunk_id"])
                    texture_ids[poly_idx] = float(new_location["texture_id"])
                    if new_location.get("kind") == "animation":
                        anim_frames[poly_idx] = float(new_location.get("frame_count", 1))
                        anim_frametimes[poly_idx] = float(new_location.get("frametime", 1))
                        anim_interps[poly_idx] = 1.0 if new_location.get("interpolate", False) else 0.0
                        anim_widths[poly_idx] = float(new_location.get("frame_width", 16))
                        anim_heights[poly_idx] = float(new_location.get("frame_height", 16))
                    else:
                        anim_frames[poly_idx] = 1.0
                        anim_frametimes[poly_idx] = 1.0
                        anim_interps[poly_idx] = 0.0
                        anim_widths[poly_idx] = float(new_location.get("frame_width", 16))
                        anim_heights[poly_idx] = float(new_location.get("frame_height", 16))

                    poly_tint_map[poly_idx] = new_location

                    resolved_locations[poly_idx] = (new_location, old_loc, orig_mode, old_mapping)
                    target_namespace, target_texture = split_texture_key(
                        new_location.get("texture_key", candidates[0])
                    )
                    source_keys[poly_idx] = canonical_texture_key(target_namespace, target_texture)
                    source_origins[poly_idx] = (
                        get_face_source_origin(mesh, poly_idx) or material_source_origin(orig_slot.material)
                    )
                    poly_updated = True
                else:
                    # Non-atlas texture fallback
                    fallback_tex_info = None
                    for cand in candidates:
                        info = pack.get_texture_info(cand, namespace)
                        if info and info.get("albedo"):
                            fallback_tex_info = info
                            break

                    if fallback_tex_info:
                        mat, _is_new = get_or_create_replacement_material(fallback_tex_info)
                        if mat:
                            resolved_standalone[poly_idx] = (mat, old_loc, orig_mode, old_mapping)
                            source_keys[poly_idx] = canonical_texture_key(
                                fallback_tex_info["namespace"],
                                fallback_tex_info.get("texture_key", fallback_tex_info["texture_name"]),
                            )
                            source_origins[poly_idx] = (
                                get_face_source_origin(mesh, poly_idx) or material_source_origin(orig_slot.material)
                            )
                            poly_tint_map[poly_idx] = BiomeResolver().get_tint_info(fallback_tex_info["texture_name"])
                            poly_updated = True
                            continue

                    unresolved_faces.append(poly_idx)

            if skipped_faces:
                pipeline_context.report(
                    "INFO",
                    f"'{obj.name}': retained {len(skipped_faces)} Ice Cube internal face(s)."
                )

            if unresolved_faces:
                pipeline_context.report(
                    "WARNING",
                    f"'{obj.name}' was left unchanged: {len(unresolved_faces)} face(s) could not be matched exactly."
                )
                continue

            if poly_updated:
                if uv_layer is not None:
                    # 1. Straighten any rotated local UVs (e.g. jmc2obj flowing liquid) and remap atlas faces to atlas UVs
                    for poly_idx, resolved in enumerate(resolved_locations):
                        if resolved is None:
                            continue
                        new_location, old_loc, orig_mode, old_mapping = resolved
                        polygon = mesh.polygons[poly_idx]
                        target_chunk = chunks_by_id[int(new_location["chunk_id"])]

                        old_chunk = None
                        if old_loc and old_mapping:
                            old_chunks_map = {int(c["chunk_id"]): c for c in old_mapping.get("chunks", [])}
                            old_chunk = old_chunks_map.get(int(old_loc["chunk_id"]))

                        old_anim_info = None
                        if not (orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_chunk):
                            orig_mat = (
                                obj.material_slots[polygon.material_index].material
                                if polygon.material_index < len(obj.material_slots) else None
                            )
                            old_anim_info = get_material_animation_info(orig_mat)

                        # Work in source-local UV space first. This makes both
                        # re-atlased meshes and direct jmc2obj imports follow
                        # exactly the same atlas-safe path.
                        for loop_index in polygon.loop_indices:
                            uv = uv_layer.data[loop_index].uv
                            uv.x, uv.y = remap_uv_to_local(
                                uv.x, uv.y, orig_mode, old_loc, old_chunk, old_anim_info
                            )

                        # A prior Atlas pass keeps tiled UV data in face
                        # attributes. Bake it back to source-local space
                        # before building a fresh Atlas, otherwise a second
                        # conversion would silently discard the tiling.
                        if orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_chunk:
                            old_tiling_scale, old_tiling_location = _read_face_tiling(mesh, poly_idx)
                            old_tiling_rotation = _read_face_float_attribute(mesh, ATTR_UV_ROTATION, poly_idx)
                            for loop_index in polygon.loop_indices:
                                uv = uv_layer.data[loop_index].uv
                                uv.x, uv.y = restore_atlas_tiling_uv(
                                    uv.x, uv.y, old_tiling_scale, old_tiling_location, old_tiling_rotation
                                )

                        # Preserve non-orthogonal liquid UVs through the
                        # existing rotation attribute, then store any merged
                        # face span as shader tiling data instead of splitting.
                        rot_angle, was_straightened = straighten_face_uv(polygon, uv_layer)
                        uv_rotations[poly_idx] = float(rot_angle) if was_straightened else 0.0

                        # Preserve UV islands wholly inside one tile (for
                        # example adaptive pixel splits and campfire parts).
                        # Only genuine repeats, or a straightened liquid UV,
                        # require the shader-side tiling transform.
                        if was_straightened or face_uv_requires_atlas_tiling(polygon, uv_layer):
                            scale, location = normalize_face_uv_for_atlas_tiling(polygon, uv_layer)
                            uv_tiling_scales[poly_idx] = scale
                            uv_tiling_locations[poly_idx] = location

                        remap_polygon_loop_uvs(
                            polygon=polygon,
                            uv_layer=uv_layer,
                            orig_mode="STANDALONE",
                            target_location=new_location,
                            target_chunk=target_chunk,
                        )

                for attr_name, data in (
                    (ATTR_ATLAS_CHUNK_ID, chunk_ids),
                    (ATTR_ATLAS_TEXTURE_ID, texture_ids),
                    (ATTR_UV_ROTATION, uv_rotations),
                ):
                    _ensure_face_attribute(mesh, attr_name, "FLOAT").data.foreach_set("value", data)

                packed_tint_data, tint_colors = _compute_biome_tint_attributes(
                    len(mesh.polygons), poly_tint_map, biome_preset
                )
                _apply_biome_tint_attributes(mesh, packed_tint_data, tint_colors)

                for attr_name, data in (
                    (ATTR_ANIM_TIMING, zip(anim_frames, anim_frametimes, anim_interps, anim_widths)),
                    (ATTR_ANIM_FRAME_SIZE, ((width, height, 0.0, 1.0) for width, height in zip(anim_widths, anim_heights))),
                    (ATTR_UV_TILING_TRANSFORM, ((scale[0], scale[1], location[0], location[1]) for scale, location in zip(uv_tiling_scales, uv_tiling_locations))),
                ):
                    _ensure_face_attribute(mesh, attr_name, "FLOAT_COLOR").data.foreach_set(
                        "color", [component for value in data for component in value]
                    )

                # Drop obsolete split streams so a re-run repairs already
                # converted meshes as well as new meshes.
                _cleanup_legacy_mesh_attributes(mesh)

                # 2. Revert standalone fallback faces to local UVs (or Standalone Frame 0)
                for poly_idx, st_res in enumerate(resolved_standalone):
                    if st_res is None:
                        continue
                    mat, old_loc, orig_mode, old_mapping = st_res
                    polygon = mesh.polygons[poly_idx]

                    old_chunk = None
                    if old_loc and old_mapping:
                        old_chunks_map = {int(c["chunk_id"]): c for c in old_mapping.get("chunks", [])}
                        old_chunk = old_chunks_map.get(int(old_loc["chunk_id"]))

                    old_anim_info = None
                    if not (orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_chunk):
                        orig_mat = (
                            obj.material_slots[polygon.material_index].material
                            if polygon.material_index < len(obj.material_slots) else None
                        )
                        old_anim_info = get_material_animation_info(orig_mat)

                    target_anim_info = get_material_animation_info(mat)

                    remap_polygon_loop_uvs(
                        polygon=polygon,
                        uv_layer=uv_layer,
                        orig_mode=orig_mode,
                        old_loc=old_loc,
                        old_chunk=old_chunk,
                        old_anim_info=old_anim_info,
                        target_anim_info=target_anim_info,
                    )

                for poly_idx, resolved in enumerate(resolved_locations):
                    if resolved is not None:
                        face_materials[poly_idx] = atlas_materials[int(resolved[0]["chunk_id"])]

                for poly_idx, st_res in enumerate(resolved_standalone):
                    if st_res is not None:
                        face_materials[poly_idx] = st_res[0]

                apply_mesh_face_materials_and_provenance(mesh, face_materials, source_keys, source_origins)
                # Normal meshes retain the mesh-side backup used by existing
                # MoziToolKit reconstruction and replacement workflows.
                mesh["mtk:atlas_mapping"] = json.dumps(mapping_data, separators=(",", ":"))
                write_provenance_schema(mesh)
                _cleanup_object_anim_properties(obj)


            replaced_objects += 1

        yield ProgressUpdate(1.0, 1.0, f"Atlas replacement finished ({replaced_objects} object(s)).")
        yield StepResult.success(f"Successfully processed {replaced_objects} object(s) in Atlas Mode.")

    def _execute_standalone_mode_iter(
        self, pipeline_context, pack: ZipResourcePack, valid_objects: list, pack_textures: bool, biome_preset: str = "PLAINS"
    ) -> Iterator[Union[ProgressUpdate, StepResult]]:
        """Iteratively execute material replacement in Standalone Mode with fine-grained progress."""
        replaced_count = 0
        assigned_count = 0
        session_materials = {}
        biome_resolver = BiomeResolver(pack_root=pack.extract_dir)

        total_objs = len(valid_objects)

        def get_or_create_replacement_material(texture_info):
            texture_key = (pack.pack_hash, texture_info["namespace"], texture_info["texture_name"])
            canonical_mat = find_existing_replacement(texture_info, pack) or session_materials.get(texture_key)
            if canonical_mat:
                return canonical_mat, False

            mat_name = f"mtk:{texture_info['namespace']}:{texture_info['texture_name']}"
            mat = bpy.data.materials.new(name=mat_name)
            if not rebuild_material(mat, texture_info, pack_textures=pack_textures, pack_hash=pack.pack_hash):
                bpy.data.materials.remove(mat)
                return None, False

            name_replaced_material(mat, texture_info, pack)
            session_materials[texture_key] = mat
            return mat, True

        for obj_idx, obj in enumerate(valid_objects):
            if pipeline_context.is_cancelled:
                yield StepResult.cancelled("Material replacement cancelled by user.")
                return

            obj_progress = 0.10 + 0.85 * (obj_idx / max(1, total_objs))
            yield ProgressUpdate(obj_progress, 1.0, f"Reconstructing materials: {obj.name} ({obj_idx + 1}/{total_objs})")

            mesh = obj.data
            uv_layer = mesh.uv_layers.active_render or mesh.uv_layers.active

            old_mappings = _build_old_mappings(obj, mesh)

            resolved_faces = []
            unresolved_faces = []
            skipped_faces = []
            face_materials = [
                obj.material_slots[poly.material_index].material
                if poly.material_index < len(obj.material_slots) else None
                for poly in mesh.polygons
            ]

            for poly_idx, poly in enumerate(mesh.polygons):
                if poly.material_index >= len(obj.material_slots):
                    unresolved_faces.append(poly_idx)
                    continue
                orig_slot = obj.material_slots[poly.material_index]
                if not orig_slot.material:
                    unresolved_faces.append(poly_idx)
                    continue
                if is_ice_cube_internal_face_material(orig_slot.material):
                    skipped_faces.append(poly_idx)
                    continue

                old_mapping = old_mappings.get(orig_slot.material)
                orig_mode = detect_material_mode(orig_slot.material)
                namespace, candidates, old_loc = extract_face_texture_info(
                    mesh, poly_idx, orig_slot.material, old_mapping
                )

                tex_info = None
                for cand in candidates:
                    info = pack.get_texture_info(cand, namespace)
                    if info and info.get("albedo"):
                        tex_info = dict(info)
                        overlay_stem = biome_resolver.get_overlay_texture(tex_info["texture_name"])
                        if overlay_stem:
                            overlay_info = pack.get_texture_info(overlay_stem, namespace)
                            if overlay_info and overlay_info.get("albedo"):
                                tex_info["overlay"] = overlay_info["albedo"]
                        break

                if not tex_info:
                    unresolved_faces.append(poly_idx)
                    continue
                resolved_faces.append((poly_idx, tex_info, orig_slot.material, orig_mode, old_loc, old_mapping))

            if unresolved_faces:
                pipeline_context.report(
                    "WARNING",
                    f"'{obj.name}' was left unchanged: {len(unresolved_faces)} face(s) could not be matched exactly."
                )
                continue
            if skipped_faces:
                pipeline_context.report(
                    "INFO",
                    f"'{obj.name}': retained {len(skipped_faces)} Ice Cube internal face(s)."
                )

            source_keys = [get_face_source_texture_key(mesh, idx) for idx in range(len(mesh.polygons))]
            source_origins = [get_face_source_origin(mesh, idx) for idx in range(len(mesh.polygons))]
            poly_modified = False
            prepared_faces = []
            material_build_failed = False

            for poly_idx, tex_info, original_material, orig_mode, old_loc, old_mapping in resolved_faces:
                mat, is_new = get_or_create_replacement_material(tex_info)
                if not mat:
                    material_build_failed = True
                    break
                prepared_faces.append((
                    poly_idx, tex_info, original_material, orig_mode,
                    old_loc, old_mapping, mat, is_new,
                ))

            if material_build_failed:
                pipeline_context.report("ERROR", f"'{obj.name}' material construction failed; no conversion was applied.")
                continue

            for poly_idx, tex_info, original_material, orig_mode, old_loc, old_mapping, mat, is_new in prepared_faces:
                face_materials[poly_idx] = mat
                source_keys[poly_idx] = canonical_texture_key(
                    tex_info["namespace"], tex_info.get("texture_key", tex_info["texture_name"])
                )
                source_origins[poly_idx] = (
                    get_face_source_origin(mesh, poly_idx) or material_source_origin(original_material)
                )
                poly_modified = True
                assigned_count += 1
                if is_new:
                    replaced_count += 1
                    pipeline_context.report("INFO", f"Built standalone material '{mat.name}' for '{tex_info['texture_name']}'")

                if uv_layer:
                    old_chunk = None
                    if orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_mapping:
                        old_chunks_map = {int(c["chunk_id"]): c for c in old_mapping.get("chunks", [])}
                        old_chunk = old_chunks_map.get(int(old_loc["chunk_id"]))

                    old_anim_info = None
                    if not (orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_chunk):
                        old_anim_info = get_material_animation_info(original_material)

                    target_anim_info = get_texture_info_animation_info(tex_info) or get_material_animation_info(mat)

                    polygon = mesh.polygons[poly_idx]
                    if orig_mode in ("ATLAS_CHUNK", "ATLAS_UNIFIED") and old_loc and old_chunk:
                        # Atlas mesh UVs are deliberately normalized to one
                        # cell. Bake the same scale/location/rotation used by
                        # MC_Atlas_UV_Tiling before switching to a material
                        # that no longer contains that shader node.
                        tiling_scale, tiling_location = _read_face_tiling(mesh, poly_idx)
                        tiling_rotation = _read_face_float_attribute(mesh, ATTR_UV_ROTATION, poly_idx)
                        for loop_index in polygon.loop_indices:
                            uv = uv_layer.data[loop_index].uv
                            local_u, local_v = remap_uv_to_local(
                                uv.x, uv.y, orig_mode, old_loc, old_chunk, old_anim_info
                            )
                            local_u, local_v = restore_atlas_tiling_uv(
                                local_u, local_v, tiling_scale, tiling_location, tiling_rotation
                            )
                            uv.x, uv.y = remap_local_to_target_uv(
                                local_u, local_v, target_anim_info=target_anim_info
                            )
                    else:
                        remap_polygon_loop_uvs(
                            polygon=polygon,
                            uv_layer=uv_layer,
                            orig_mode=orig_mode,
                            old_loc=old_loc,
                            old_chunk=old_chunk,
                            old_anim_info=old_anim_info,
                            target_anim_info=target_anim_info,
                        )

            if poly_modified:
                poly_tint_map = {
                    poly_idx: biome_resolver.get_tint_info(tex_info["texture_name"])
                    for poly_idx, tex_info, _, _, _, _, _, _ in prepared_faces
                }
                packed_tint_data, tint_colors = _compute_biome_tint_attributes(
                    len(mesh.polygons), poly_tint_map, biome_preset
                )
                _apply_biome_tint_attributes(mesh, packed_tint_data, tint_colors)
                _cleanup_legacy_mesh_attributes(mesh)
                apply_mesh_face_materials_and_provenance(mesh, face_materials, source_keys, source_origins)

                has_retained_atlas_face = any(
                    face_materials[poly_idx]
                    and detect_material_mode(face_materials[poly_idx]) in ("ATLAS_CHUNK", "ATLAS_UNIFIED")
                    for poly_idx in unresolved_faces + skipped_faces
                )
                if not has_retained_atlas_face:
                    for attr_name in ANIM_AND_ATLAS_ATTR_NAMES:
                        attr = mesh.attributes.get(attr_name)
                        if attr:
                            mesh.attributes.remove(attr)
                    _cleanup_object_anim_properties(obj)

        if assigned_count == 0:
            yield StepResult.success("No exact material matches found; selected objects were left unchanged.")
            return

        yield ProgressUpdate(1.0, 1.0, f"Standalone replacement finished ({assigned_count} slots assigned).")
        yield StepResult.success(f"Successfully processed Standalone replacement ({assigned_count} slot(s) assigned, {replaced_count} new material(s) created).")
