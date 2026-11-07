"""Native API surface contract for the 2.0 addon/wheel pairing."""

from __future__ import annotations

from MoziToolKit.bridge.engine import get_libmtk


def test_required_native_symbols_exist():
    mtk = get_libmtk()
    assert mtk is not None
    required = [
        "api_version",
        "VoxelWorld",
        "VoxelPointCloud",
        "MeshData",
        "compute_biome_tint_attributes",
        "compute_biome_tint_attributes_paletted",
        "build_material_palette",
    ]
    for name in required:
        assert hasattr(mtk, name), f"libmtk_py is missing required symbol {name}"


def test_removed_native_symbols_do_not_return():
    mtk = get_libmtk()
    assert mtk is not None
    removed = [
        "SectionMesher",
        "process_mesh",
        "process_random_extrude_mesh",
        "process_mesh_extrude_repair",
        "compute_canonical_state_hash",
        "PyBufferOwner",
        "ValidationReport",
        "clear_cached_colormaps",
        "decode_packet",
        "mesh_attribute_schema",
        "retired_mesh_attributes",
        "is_valid_cache_package",
        "get_cache_manifest",
    ]
    for name in removed:
        assert not hasattr(mtk, name), f"removed symbol {name} leaked back into libmtk_py"

    mesh = mtk.MeshData()
    for name in (
        "from_raw_buffers",
        "set_buffers",
        "append_unit_cube_face",
        "get_flat_positions",
        "get_flat_uvs",
        "get_indices",
        "get_quad_indices",
        "get_face_materials",
        "weld_spatial_vertices",
        "has_dynamic_entity_chunks",
        "append_mesh",
        "has_attribute",
        "loop_starts_memoryview",
        "loop_totals_memoryview",
        "source_texture_palette_indices",
        "uv_layout",
    ):
        assert not hasattr(mesh, name), f"removed MeshData API {name} leaked back"

    for name in (
        "set_model_db",
        "clear",
        "get_bounds",
        "get_block",
        "set_block",
        "get_block_entity_json",
        "set_block_entity_json",
        "ensure_dynamic_entities_resolved_sync",
    ):
        assert not hasattr(mtk.VoxelWorld, name), f"removed VoxelWorld API {name} leaked back"

    cfg = mtk.MesherConfig()
    for name in (
        "has_atlas",
        "has_biome_resolver",
        "has_colormaps",
        "set_bounds",
    ):
        assert not hasattr(cfg, name), f"removed MesherConfig API {name} leaked back"

    for name in (
        "contains",
        "get_states",
        "remap_to_atlas",
    ):
        assert not hasattr(mtk.BakedModelDatabase, name), f"removed BakedModelDatabase API {name} leaked back"

    assert not hasattr(mtk.AssetCache, "extract_atlas_texture")
    assert not hasattr(mtk.AssetCache, "is_valid")

    assert not hasattr(mtk.MaterialResolver, "clean_name")

    for name in (
        "read_point_cloud",
        "read_models",
        "read_atlas",
        "read_atlas_mapping_json",
        "has_colormaps",
        "read_colormap",
        "read_colormaps",
        "install_colormaps",
        "effective_capabilities",
        "has_dynamic_entity_slots",
        "read_dynamic_entity_slots",
        "read_biome_resolver",
        "has_ctm_rules",
        "read_ctm_rules_json",
        "read_ctm_solver",
        "extract_atlas_texture",
    ):
        assert not hasattr(mtk.ScenePackageReader, name), f"removed ScenePackageReader API {name} leaked back"

    assert not hasattr(mtk, "create_test_cache_package")
    assert hasattr(mtk, "unstable")
    assert hasattr(mtk.unstable, "testing")
    assert hasattr(mtk.unstable.testing, "create_test_cache_package")
    assert not hasattr(mtk.unstable, "blender_dna")

    # Test-only APIs must stay out of the stable top-level namespace.
    test_only = [
        "AtlasBuilder",
        "ModelBaker",
        "calculate_face_target_grid",
        "calculate_pixel_grid_cut_factors",
        "slice_face_by_pixel_grid",
        "is_uv_collapsed",
        "is_orthogonal_angle",
        "detect_uv_rotation",
        "straighten_uv",
        "normalize_uv_for_atlas_tiling",
        "uv_requires_atlas_tiling",
        "restore_atlas_tiling_uv",
        "repair_quad_fluid_uv",
        "batch_repair_fluid_uv",
        "repair_extruded_side_uv",
        "sample_uv_alpha_f32",
        "encode_welcome",
        "encode_baseline_begin",
        "encode_baseline_chunk",
        "encode_baseline_end",
        "encode_delta_op",
        "encode_palette_update",
        "decode_packet",
        "mesh_attribute_schema",
        "retired_mesh_attributes",
        "extract_cache_atlas_texture",
        "model_database_get_states",
        "model_database_remap_to_atlas",
        "voxel_storage_get_non_empty_sections",
        "voxel_storage_get_block_entity_json",
        "voxel_storage_set_block_entity_json",
        "voxel_world_ensure_dynamic_entities_resolved_sync",
    ]
    for name in test_only:
        assert not hasattr(mtk, name), f"test-only symbol {name} leaked into libmtk_py"
        assert hasattr(mtk.unstable.testing, name), f"unstable.testing is missing {name}"

    for name in (
        "classify_tint_category",
        "get_hardcoded_tint",
        "get_hardcoded_tint_hex",
        "get_swamp_grass_color",
    ):
        assert not hasattr(mtk, name), f"removed biome helper {name} leaked into libmtk_py"

    resolver = mtk.BiomeResolver()
    for name in ("set_models", "load_from_directory", "load_from_zip", "get_overlay_texture"):
        assert not hasattr(resolver, name), f"test-only BiomeResolver method {name} leaked"

    for name in (
        "clear",
        "get_bounds",
        "get_non_empty_sections",
        "get_block_entity_json",
        "set_block_entity_json",
        "get_all_blocks",
        "get_generation",
        "calculate_and_store_section_crc",
        "dirty_section_count",
        "clear_dirty_sections",
        "mark_section_dirty",
        "set_section_snapshot",
    ):
        assert not hasattr(mtk.VoxelStorage, name), f"test-only VoxelStorage method {name} leaked"

    cloud = mtk.VoxelPointCloud()
    for name in ("from_arrays", "get_block_states", "get_biomes", "to_mesh_data", "from_mesh_data"):
        assert not hasattr(mtk.VoxelPointCloud, name), f"removed VoxelPointCloud API {name} leaked back"
        assert not hasattr(cloud, name)


def test_live_sync_surface_has_no_retired_aliases():
    """The persisted-state fast path and the singular atlas accessor are retired."""
    mtk = get_libmtk()
    assert mtk is not None

    session = mtk.LiveSyncSession
    # The dead persisted-state entry points must not return.
    for name in ("start_with_persisted_state", "export_persisted_state_json"):
        assert not hasattr(session, name), f"removed LiveSyncSession API {name} leaked back"

    # `start()` only carries the live connection args (no cached_* handshake fields).
    signature = session.start.__text_signature__ or ""
    assert signature, "LiveSyncSession.start must expose a signature"
    for retired in (
        "cached_uuid",
        "cached_epoch",
        "cached_seq",
        "cached_min",
        "cached_size",
        "cached_state_hash",
        "cached_dimension",
        "state_json",
    ):
        assert retired not in signature, f"retired handshake arg {retired} leaked into start()"
    assert "auth_token" in signature

    # Dynamic entity atlases are a multi-chunk map only; the singular blob is gone.
    for owner in (session, mtk.VoxelWorld):
        assert hasattr(owner, "get_dynamic_entity_atlases")
        assert not hasattr(owner, "get_dynamic_entity_atlas")
    mesh = mtk.MeshData()
    assert hasattr(mesh, "dynamic_entity_atlases")
    assert not hasattr(mesh, "dynamic_entity_atlas")



def test_standalone_dna_adapter_contract():
    import pytest

    dna = pytest.importorskip("libmtk_blender_dna")
    assert dna.api_version() == 2
    for name in (
        "copy_f32",
        "copy_i32",
        "copy_u32",
        "copy_u8",
        "as_memoryview_f32",
        "as_memoryview_i32",
        "as_memoryview_u32",
        "as_memoryview_u8",
    ):
        assert hasattr(dna, name)
    for removed in (
        "read_f32",
        "read_i32",
        "read_u32",
        "read_u8",
        "as_memoryview_raw",
        "copy_positions_to_ptr",
    ):
        assert not hasattr(dna, removed), f"removed DNA function {removed} leaked into libmtk_blender_dna"
