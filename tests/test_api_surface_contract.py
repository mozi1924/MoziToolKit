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
    ):
        assert not hasattr(mesh, name), f"removed MeshData API {name} leaked back"

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
        "is_face_transparent_f32",
        "encode_welcome",
        "encode_baseline_begin",
        "encode_baseline_chunk",
        "encode_baseline_end",
        "encode_delta_op",
        "encode_palette_update",
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
    for name in ("from_arrays", "get_block_states", "get_biomes"):
        assert not hasattr(mtk.VoxelPointCloud, name), f"removed VoxelPointCloud API {name} leaked back"
        assert not hasattr(cloud, name)



def test_standalone_dna_adapter_contract():
    import pytest

    dna = pytest.importorskip("libmtk_blender_dna")
    assert dna.api_version() == 1
    for name in ("copy_f32", "copy_i32", "copy_u32", "copy_u8"):
        assert hasattr(dna, name)
    assert not hasattr(dna, "copy_positions_to_ptr")
