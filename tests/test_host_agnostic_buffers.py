"""
Unit tests for Host-Agnostic Tier 3 Batch Ingestion & Buffer APIs.

Validates that PyMeshData and PyVoxelPointCloud can be queried via `.to_buffers()`
in headless/pure Python environments without any dependency on Blender C++ or bpy.
"""

from __future__ import annotations

import numpy as np
import pytest

from MoziToolKit.bridge.engine import get_libmtk


def test_mesh_data_to_buffers_headless():
    mtk = get_libmtk()
    if mtk is None:
        pytest.skip("libmtk_py is not available")

    # Construct flat quad mesh
    # Quad: (0,0,0), (1,0,0), (1,1,0), (0,1,0)
    positions = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0]
    loop_verts = [0, 1, 2, 3]
    loop_uvs = [0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
    starts = [0]
    totals = [4]
    materials = [0]

    mesh = mtk.MeshData.from_flat_polygons(
        positions,
        loop_verts,
        loop_uvs,
        starts,
        totals,
        None,
        materials,
    )

    # Attach a custom numeric attribute
    attr_buf = np.array([42, 43, 44, 45], dtype=np.int32)
    mesh.add_attribute_from_buffer("test_attr", "point", "int", attr_buf)

    # Export host-agnostic buffer DTO
    buf_dict = mesh.to_buffers()
    assert isinstance(buf_dict, dict)
    assert buf_dict["vertex_count"] == 4
    assert buf_dict["face_count"] == 1
    assert buf_dict["quad_count"] == 1

    # Ingest with typed memoryview and numpy zero-copy
    assert buf_dict["positions"].format == "f"
    assert buf_dict["positions"].itemsize == 4
    assert len(buf_dict["positions"]) == 12
    pos_np = np.frombuffer(buf_dict["positions"], dtype=np.float32)
    assert len(pos_np) == 12
    np.testing.assert_allclose(pos_np[:3], [0.0, 0.0, 0.0])

    assert buf_dict["indices"].format == "I"
    assert buf_dict["indices"].itemsize == 4
    assert len(buf_dict["indices"]) == 6
    indices_np = np.frombuffer(buf_dict["indices"], dtype=np.uint32)
    assert len(indices_np) == 6  # Triangulated 2 tris = 6 indices

    assert buf_dict["loop_uvs"].format == "f"
    assert buf_dict["loop_uvs"].itemsize == 4
    assert len(buf_dict["loop_uvs"]) == 8
    uvs_np = np.frombuffer(buf_dict["loop_uvs"], dtype=np.float32)
    assert len(uvs_np) == 8

    assert buf_dict["face_materials"].format == "H"
    assert buf_dict["face_materials"].itemsize == 2
    assert len(buf_dict["face_materials"]) == 1
    mats_np = np.frombuffer(buf_dict["face_materials"], dtype=np.uint16)
    assert len(mats_np) == 1
    assert mats_np[0] == 0

    # Custom attributes in dict
    assert "attributes" in buf_dict
    assert "test_attr" in buf_dict["attributes"]
    attr_info = buf_dict["attributes"]["test_attr"]
    assert attr_info["domain"] == "point"
    assert attr_info["dtype"] == "int32"
    assert attr_info["data"].format == "i"
    assert attr_info["data"].itemsize == 4
    assert len(attr_info["data"]) == 4
    attr_data = np.frombuffer(attr_info["data"], dtype=np.int32)
    np.testing.assert_array_equal(attr_data, [42, 43, 44, 45])


def test_voxel_point_cloud_to_buffers_headless():
    mtk = get_libmtk()
    if mtk is None:
        pytest.skip("libmtk_py is not available")

    cloud = mtk.VoxelPointCloud()
    cloud.push([0.5, 0.5, 0.5], [0, 0, 0], "minecraft:stone", "minecraft:plains", 15)
    cloud.push([1.5, 0.5, 0.5], [1, 0, 0], "minecraft:dirt", "minecraft:plains", 15)

    buf_dict = cloud.to_buffers()
    assert isinstance(buf_dict, dict)
    assert buf_dict["count"] == 2

    assert buf_dict["positions"].format == "f"
    assert buf_dict["positions"].itemsize == 4
    assert len(buf_dict["positions"]) == 6
    pos_np = np.frombuffer(buf_dict["positions"], dtype=np.float32)
    assert len(pos_np) == 6
    np.testing.assert_allclose(pos_np[:3], [0.5, 0.5, 0.5])

    assert buf_dict["block_x"].format == "i"
    assert buf_dict["block_x"].itemsize == 4
    assert len(buf_dict["block_x"]) == 2
    bx_np = np.frombuffer(buf_dict["block_x"], dtype=np.int32)
    np.testing.assert_array_equal(bx_np, [0, 1])

    assert "minecraft:stone" in buf_dict["state_palette"]
    assert "minecraft:dirt" in buf_dict["state_palette"]
    assert len(buf_dict["biome_palette"]) >= 1


def test_cleaned_dead_apis_are_absent():
    """Verify that dead APIs removed in the cleanup cannot be called."""
    mtk = get_libmtk()
    if mtk is None:
        pytest.skip("libmtk_py is not available")

    mesh = mtk.MeshData()
    assert not hasattr(mesh, "get_attribute_data")
    assert not hasattr(mesh, "get_flat_secondary_uvs")
    assert not hasattr(mesh, "dynamic_skin_atlas")
    assert not hasattr(mesh, "dynamic_skin_atlases")
    assert not hasattr(mesh, "set_dynamic_skin_atlas")

    cfg = mtk.MesherConfig()
    assert not hasattr(cfg, "has_ctm_solver")
    assert not hasattr(cfg, "enable_alternate_blocks")
    assert not hasattr(cfg, "clear_bounds")

    storage = mtk.VoxelStorage()
    assert not hasattr(storage, "mark_all_sections_dirty")
    assert not hasattr(storage, "load_from_point_cloud")
