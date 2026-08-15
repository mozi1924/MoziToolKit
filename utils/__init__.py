"""
MoziToolKit Utilities Root Package.
Organized into functional domains:
- materials: Material construction, resource pack parsing, atlas generation & layout
- mesh: Geometry math, bmesh contexts, UV helpers, selection scopes
- node_groups: LabPBR and animation shader template generators
- pixel_split: Adaptive pixel subdivision algorithms
- extrude_repair: Extruded side face UV & crease repair
- system: Python dependency management and right-click menu registry
"""

# Re-export subpackages
from . import materials
from . import system
from . import mesh

try:
    from . import node_groups
    from . import pixel_split
    from . import extrude_repair
except ImportError:
    pass

# Re-export Mesh & Geometry APIs
try:
    from .mesh import (
        poll_edit_mesh,
        poll_mesh_object,
        set_select_mode,
        bmesh_context,
        apply_selection,
        get_connected_faces,
        get_target_faces,
        is_hard_edge,
        UVBounds,
        get_face_uv_bounds,
        get_face_uv_center,
        get_image_from_face,
        process_random_extrude,
        SELECTION_ACTION_ITEMS,
        SELECTION_SCOPE_ITEMS,
        SELECT_MODES,
    )
    from .pixel_split import (
        process_adaptive_pixel_split,
        SplitConfig,
    )
    from .extrude_repair import (
        repair_extruded_side_faces,
        ExtrudeRepairConfig,
    )
except ImportError:
    pass

# Re-export Materials APIs
try:
    from .materials import (
        set_materials_texture_interpolation_closest,
        process_node_tree_interpolation,
        load_image_texture,
        set_material_displacement_method,
        rebuild_material,
        inspect_material_nodes,
        repair_material_nodes,
        detect_material_mode,
        is_mozi_material,
        extract_material_texture_keys,
        extract_face_texture_info,
        get_atlas_mapping_from_material,
        ZipResourcePack,
        get_cache_dir,
        clear_resource_pack_cache,
        get_pack_hash,
        get_directory_hash,
        parse_mcmeta,
        face_index_from_normal,
        static_cell,
        chunk_cell,
        atlas_uv_from_local,
        atlas_uv_from_rect,
        local_uv_from_atlas,
        local_uv_from_rect,
        find_texture_id_from_atlas_uv,
        AtlasGenerator,
        build_atlas_material,
        build_atlas_chunk_materials,
        DEFAULT_NAMESPACE,
        PROP_PACK_HASH,
        PROP_PACK_HASH_SHORT,
        PROP_SOURCE_NAMESPACE,
        PROP_SOURCE_TEXTURE,
        PROP_SOURCE_FILE,
        PROP_MATERIAL_ID,
        PROP_ATLAS_CHUNK_ID,
        PROP_ATLAS_CHUNK_KIND,
        PROP_ATLAS_MAPPING,
        ATTR_ATLAS_CHUNK_ID,
        ATTR_ATLAS_TEXTURE_ID,
        ATTR_FACE_MATERIAL_ID,
        FACE_ORDER,
        ATLAS_FORMAT_VERSION,
    )
except ImportError:
    try:
        from .materials.atlas_generator import AtlasGenerator
    except ImportError:
        pass

# Re-export System APIs
from .system import (
    Dependency,
    DEPENDENCIES,
    PYPI_MIRRORS,
    ensure_sys_paths,
    get_python_executable,
    is_module_installed,
    get_installed_version,
    get_dependency_status,
    get_all_dependency_statuses,
    has_all_dependencies,
    has_pillow,
    install_package,
    register_menu_item,
    register_operator_menu_item,
    normalize_operator_id,
    get_all_operators,
    get_default_presets,
    ALL_OPERATORS,
    DEFAULT_PRESETS,
    get_config_path,
    load_config,
    save_config,
    reset_config,
    export_config,
    import_config,
    draw_dynamic_menu,
)

__all__ = [
    "materials",
    "mesh",
    "node_groups",
    "pixel_split",
    "extrude_repair",
    "system",
    "AtlasGenerator",
]
