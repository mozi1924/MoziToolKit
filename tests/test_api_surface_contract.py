"""Native API surface contract for the 2.0 addon/wheel pairing."""

from __future__ import annotations

from bridge.engine import get_libmtk


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

    cloud = mtk.VoxelPointCloud()
    for name in ("from_arrays", "get_block_states", "get_biomes"):
        assert not hasattr(mtk.VoxelPointCloud, name), f"removed VoxelPointCloud API {name} leaked back"
        assert not hasattr(cloud, name)
