"""
Unit and integration tests for Voxel Point Cloud persistent storage,
Blender Mask modifier controls, and user-driven carving/remeshing.
"""

import sys
from pathlib import Path
import pytest

dev_lib = Path(__file__).parent.parent / "dev" / "lib"
if dev_lib.exists() and str(dev_lib) not in sys.path:
    sys.path.insert(0, str(dev_lib))

try:
    import libmtk_py
    HAS_LIBMTK = True
except ImportError:
    HAS_LIBMTK = False

from unittest.mock import MagicMock

try:
    import bpy
    HAS_REAL_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "app")
except ImportError:
    bpy = None
    HAS_REAL_BPY = False


@pytest.mark.skipif(not HAS_LIBMTK, reason="libmtk_py not available")
class TestVoxelPointCloudBridge:
    def test_point_cloud_python_roundtrip(self):
        """Tests VoxelPointCloud creation, attribute extraction, and storage roundtrip."""
        storage = libmtk_py.VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        storage.set_block(0, 0, 0, "minecraft:stone", "minecraft:plains")
        storage.set_block(1, 2, 3, "minecraft:oak_stairs[facing=east]", "minecraft:desert")
        storage.set_block(5, 5, 5, "minecraft:gold_block", "minecraft:plains")

        cloud = storage.to_point_cloud()
        assert len(cloud) == 3
        assert not cloud.is_empty()

        states = cloud.get_block_states()
        assert "minecraft:stone" in states
        assert "minecraft:oak_stairs[facing=east]" in states
        assert "minecraft:gold_block" in states

        # Test pure-point MeshData conversion
        mesh_data = cloud.to_mesh_data()
        assert mesh_data.vertex_count == 3
        assert mesh_data.quad_count == 0

        # Roundtrip back from MeshData
        cloud2 = libmtk_py.VoxelPointCloud.from_mesh_data(mesh_data)
        assert len(cloud2) == 3

        # Reconstruct VoxelStorage
        s2 = libmtk_py.VoxelStorage.from_point_cloud(cloud2)
        assert s2.get_block(0, 0, 0) == "minecraft:stone"
        assert s2.get_block(1, 2, 3) == "minecraft:oak_stairs[facing=east]"
        assert s2.get_block(5, 5, 5) == "minecraft:gold_block"
        assert s2.get_biome(1, 2, 3) == "minecraft:desert"

    @pytest.mark.skipif(not HAS_REAL_BPY, reason="Blender (bpy) required for scene integration")
    def test_blender_point_cloud_injection_and_mask_modifier(self):
        """Verifies point cloud injection into Blender Mesh, attributes, and Mask modifier."""
        from MoziToolKit.bridge.point_cloud import (
            inject_voxel_point_cloud,
            extract_voxel_point_cloud,
            setup_voxel_mask_modifier,
            set_voxel_cloud_visibility,
            is_voxel_cloud_visible,
            MASK_MODIFIER_NAME,
            VOXEL_VERTEX_GROUP,
        )

        storage = libmtk_py.VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        storage.set_block(2, 2, 2, "minecraft:iron_block", "minecraft:plains")
        storage.set_block(3, 3, 3, "minecraft:diamond_block", "minecraft:desert")
        cloud = storage.to_point_cloud()

        b_mesh = bpy.data.meshes.new("Test_VoxelCloud_Mesh")
        b_obj = bpy.data.objects.new("Test_VoxelCloud_Obj", b_mesh)
        bpy.context.scene.collection.objects.link(b_obj)

        try:
            # 1. Inject point cloud
            success = inject_voxel_point_cloud(b_obj, cloud, update_mask=True, initial_hidden=True)
            assert success is True
            assert len(b_mesh.vertices) == 2

            # 2. Check Mask Modifier setup
            mod = b_obj.modifiers.get(MASK_MODIFIER_NAME)
            assert mod is not None
            assert mod.type == "MASK"
            assert mod.vertex_group == VOXEL_VERTEX_GROUP
            assert mod.invert_vertex_group is True  # Initial hidden
            assert not is_voxel_cloud_visible(b_obj)

            # 3. Toggle visibility
            set_voxel_cloud_visibility(b_obj, True)
            assert is_voxel_cloud_visible(b_obj)
            assert mod.invert_vertex_group is False

            set_voxel_cloud_visibility(b_obj, False)
            assert not is_voxel_cloud_visible(b_obj)

            # 4. Extract point cloud back from Blender Mesh
            extracted_cloud = extract_voxel_point_cloud(b_obj)
            assert extracted_cloud is not None
            assert len(extracted_cloud) == 2
            extracted_states = extracted_cloud.get_block_states()
            assert "minecraft:iron_block" in extracted_states
            assert "minecraft:diamond_block" in extracted_states

        finally:
            bpy.data.objects.remove(b_obj, do_unlink=True)
            bpy.data.meshes.remove(b_mesh, do_unlink=True)

    @pytest.mark.skipif(not HAS_REAL_BPY, reason="Blender (bpy) required for scene integration")
    def test_ingest_and_user_carving_remesh_flow(self):
        """Simulates end-to-end user carving workflow in Blender."""
        from MoziToolKit.bridge.world import ingest_voxel_world
        from MoziToolKit.bridge.point_cloud import extract_voxel_point_cloud, inject_voxel_point_cloud

        # 1. Ingest a 3x3x3 solid stone cube
        storage = libmtk_py.VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        for x in range(3):
            for y in range(3):
                for z in range(3):
                    storage.set_block(x, y, z, "minecraft:stone", "minecraft:plains")

        obj, stats = ingest_voxel_world(storage, name="Test_Carving_World")
        try:
            assert stats["voxel_count"] == 27
            cloud_name = stats["voxel_cloud_name"]
            assert cloud_name in bpy.data.objects
            cloud_obj = bpy.data.objects[cloud_name]

            # Initial surface polygons: 3*3 = 9 faces per side * 6 sides = 54 quads
            initial_polys = len(obj.data.polygons)
            assert initial_polys == 54

            # 2. Simulate user deleting the center block (1, 1, 1) in Blender
            extracted_cloud = extract_voxel_point_cloud(cloud_obj)
            assert len(extracted_cloud) == 27

            # Rebuild a point cloud excluding center block (1, 1, 1) -> 26 points
            carved_cloud = libmtk_py.VoxelPointCloud()
            positions = extracted_cloud.positions_memoryview().cast("f")
            for i in range(len(extracted_cloud)):
                bx = extracted_cloud.block_x_memoryview().cast("i")[i]
                by = extracted_cloud.block_y_memoryview().cast("i")[i]
                bz = extracted_cloud.block_z_memoryview().cast("i")[i]
                st = extracted_cloud.get_block_states()[i]
                bm = extracted_cloud.get_biomes()[i]
                if not (bx == 1 and by == 1 and bz == 1):
                    p_off = i * 3
                    carved_cloud.push(
                        [positions[p_off], positions[p_off + 1], positions[p_off + 2]],
                        [bx, by, bz],
                        st,
                        bm,
                        0,
                    )
            assert len(carved_cloud) == 26

            # Write carved cloud back to cloud object
            inject_voxel_point_cloud(cloud_obj, carved_cloud)

            # 3. Execute Remesh Operator
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            res = bpy.ops.mozi.remesh_from_voxel_cloud()
            assert res == {"FINISHED"}

            # After removing center block, the 6 interior cavity faces are newly exposed!
            # New polygon count = 54 outer + 6 inner = 60 polygons!
            new_polys = len(obj.data.polygons)
            assert new_polys == 60
            assert new_polys > initial_polys

        finally:
            cloud_name = f"{obj.name}_VoxelCloud"
            if cloud_name in bpy.data.objects:
                bpy.data.objects.remove(bpy.data.objects[cloud_name], do_unlink=True)
            if obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
