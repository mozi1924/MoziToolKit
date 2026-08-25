"""
Unit tests for Live Sync multi-chunk atlas adaptation.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
import bpy

from utils.geometry_nodes.groups.atlas_uv import (
    GROUP_NAME_ATLAS_UV_CALCULATOR,
    ATLAS_UV_CALCULATOR_VERSION,
    get_or_create_atlas_uv_calculator_group,
)
from utils.geometry_nodes.world_tree import (
    WORLD_TREE_NAME,
    WORLD_TREE_SCHEMA_VERSION,
    setup_world_geometry_nodes,
)
from utils.materials.yefira.atlas_integration import (
    extract_atlas_parameters,
    find_active_atlas_material,
)
from utils.live_sync.point_cloud import refresh_baker_sources as sync_refresh_baker
from utils.materials.yefira import refresh_baker_sources as yefira_refresh_baker


class TestLiveSyncMultiChunkAtlas(unittest.TestCase):
    def setUp(self):
        # Clear existing materials & node groups created during tests
        for mat in list(bpy.data.materials):
            bpy.data.materials.remove(mat)
        for group in list(bpy.data.node_groups):
            bpy.data.node_groups.remove(group)
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj)

    def test_atlas_uv_calculator_anim_frame_count(self):
        """Verify Yefira_Atlas_UV_Calculator compares Anim Frame Count > 1.0."""
        tree = get_or_create_atlas_uv_calculator_group()
        self.assertIsNotNone(tree)
        self.assertEqual(tree.get("mozi_group_version"), ATLAS_UV_CALCULATOR_VERSION)

        # Check interface sockets
        socket_names = [item.name for item in tree.interface.items_tree if item.item_type == "SOCKET"]
        self.assertIn("Anim Frame Count", socket_names)
        self.assertIn("Chunk ID", socket_names)
        self.assertIn("Atlas UV", socket_names)

        # Find the compare node
        compare_nodes = [n for n in tree.nodes if n.bl_idname == "FunctionNodeCompare"]
        self.assertTrue(len(compare_nodes) > 0)
        cmp_node = compare_nodes[0]
        self.assertEqual(cmp_node.data_type, "FLOAT")
        self.assertEqual(cmp_node.operation, "GREATER_THAN")
        self.assertAlmostEqual(cmp_node.inputs["B"].default_value, 1.0)

        # Verify cmp_node input A is connected from Anim Frame Count
        links_to_cmp = [l for l in tree.links if l.to_node == cmp_node and l.to_socket == cmp_node.inputs["A"]]
        self.assertEqual(len(links_to_cmp), 1)
        self.assertEqual(links_to_cmp[0].from_socket.name, "Anim Frame Count")

    def test_extract_atlas_parameters_multi_chunk(self):
        """Verify extract_atlas_parameters dynamically resolves blocks vs animation chunks."""
        mat = bpy.data.materials.new(name="mtk:minecraft:blocks_chunk_000")
        mapping = {
            "format_version": 10,
            "tile_size": 16,
            "chunks": [
                {
                    "chunk_id": 0,
                    "category": "blocks",
                    "kind": "static",
                    "width": 2048,
                    "height": 2048,
                    "tile_size": 16,
                    "tiles_per_row": 128,
                },
                {
                    "chunk_id": 1,
                    "category": "items",
                    "kind": "static",
                    "width": 1024,
                    "height": 1024,
                    "tile_size": 16,
                    "tiles_per_row": 64,
                },
                {
                    "chunk_id": 2,
                    "category": "particles",
                    "kind": "animation",
                    "width": 512,
                    "height": 1024,
                    "tile_size": 16,
                },
            ],
            "textures": {},
            "materials": [],
        }
        mat["mtk:atlas_mapping"] = json.dumps(mapping)

        params = extract_atlas_parameters(mat)
        # Static blocks chunk should determine main width/height
        self.assertEqual(params["width"], 2048.0)
        self.assertEqual(params["height"], 2048.0)
        self.assertEqual(params["tiles_per_row"], 128)

        # Animation chunk (chunk 2) should be dynamically extracted
        self.assertEqual(params["anim_atlas_width"], 512.0)
        self.assertEqual(params["anim_atlas_height"], 1024.0)
        self.assertEqual(params["anim_frame_width"], 16.0)
        self.assertEqual(params["anim_frame_height"], 16.0)

    def test_find_active_atlas_material_new_naming(self):
        """Verify find_active_atlas_material detects new mtk:namespace:category_chunk_id naming."""
        mat = bpy.data.materials.new(name="mtk:minecraft:blocks_chunk_000")
        found = find_active_atlas_material()
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "mtk:minecraft:blocks_chunk_000")

    def test_refresh_baker_sources(self):
        """Verify refresh_baker_sources executes cleanly."""
        sync_refresh_baker()
        yefira_refresh_baker()

    def test_template_indices_follow_collection_info_instance_order(self):
        """Template indices must not depend on collection insertion order.

        Geometry Nodes sorts direct Collection Info children by name before
        Pick Instance consumes Instance Index.  Extracted JSON models are
        appended to the collection, so using ``collection.objects`` here
        would make a point choose a different block's mesh.
        """
        from utils.live_sync.template_catalog import get_template_index_map

        col = bpy.data.collections.new("Test_Template_Instance_Order")
        bpy.context.scene.collection.children.link(col)
        for name in ("z_model", "a_model", "m_model"):
            mesh = bpy.data.meshes.new(f"{name}_mesh")
            obj = bpy.data.objects.new(name, mesh)
            col.objects.link(obj)

        indices = get_template_index_map(col)
        self.assertEqual(indices["a_model"], 0)
        self.assertEqual(indices["m_model"], 1)
        self.assertEqual(indices["z_model"], 2)

    def test_point_cloud_directional_uv_rotations_not_overwritten(self):
        """Verify oak_log[axis=y] maintains 0.0 UV rotation and is not corrupted by atlas static LUT."""
        from utils.live_sync import VoxelStorage, update_world_point_cloud
        from utils.materials.yefira.atlas_integration import build_block_face_uv_rot_lut

        storage = VoxelStorage()
        storage.min_x = storage.min_y = storage.min_z = 0
        storage.size_x = storage.size_y = storage.size_z = 1
        storage.block_map[(0, 0, 0)] = "minecraft:oak_log[axis=y]"

        mock_mapping = {
            "materials": [
                {
                    "name": "minecraft:oak_log",
                    "faces": {
                        "+X": {"uv_rotation": 90.0},
                        "-X": {"uv_rotation": 90.0},
                        "+Y": {"uv_rotation": 0.0},
                        "-Y": {"uv_rotation": 0.0},
                        "+Z": {"uv_rotation": 90.0},
                        "-Z": {"uv_rotation": 90.0},
                    },
                }
            ]
        }
        rot_lut = build_block_face_uv_rot_lut(mock_mapping)

        res = update_world_point_cloud(bpy.context, storage, block_face_uv_rot_lut=rot_lut)
        self.assertIsNotNone(res.world_obj)
        mesh = res.world_obj.data
        for face in ("east", "west", "top", "bottom", "south", "north"):
            val = mesh.attributes[f"mtk_uv_rot_{face}"].data[0].value
            self.assertEqual(val, 0.0, f"Face {face} for oak_log[axis=y] had non-zero rotation: {val}")

    def test_default_template_mesh_normals_and_face_ids(self):
        """Verify procedural default templates (torch, lantern, slab, fence, carpet) have outward normals."""
        from utils.live_sync.template_catalog import (
            _create_torch_mesh, _create_lantern_mesh, _create_slab_mesh,
            _create_fence_mesh, _create_carpet_mesh, _create_stairs_mesh
        )
        for creator in (_create_torch_mesh, _create_lantern_mesh, _create_slab_mesh, _create_fence_mesh, _create_carpet_mesh):
            mesh = creator("test_template")
            self.assertEqual(len(mesh.polygons), 6)
            fid_attr = mesh.attributes.get("yefira_local_face_id")
            self.assertIsNotNone(fid_attr)
            
            # Check outward normals
            normals = [p.normal for p in mesh.polygons]
            fids = [fid_attr.data[p.index].value for p in mesh.polygons]
            
            # Face 0: Bottom (-Z) -> normal.z < -0.5, fid == 1
            self.assertLess(normals[0].z, -0.5)
            self.assertEqual(fids[0], 1)
            # Face 1: Top (+Z) -> normal.z > 0.5, fid == 0
            self.assertGreater(normals[1].z, 0.5)
            self.assertEqual(fids[1], 0)
            # Face 2: South (-Y) -> normal.y < -0.5, fid == 3
            self.assertLess(normals[2].y, -0.5)
            self.assertEqual(fids[2], 3)
            # Face 3: East (+X) -> normal.x > 0.5, fid == 4
            self.assertGreater(normals[3].x, 0.5)
            self.assertEqual(fids[3], 4)
            # Face 4: North (+Y) -> normal.y > 0.5, fid == 2
            self.assertGreater(normals[4].y, 0.5)
            self.assertEqual(fids[4], 2)
            # Face 5: West (-X) -> normal.x < -0.5, fid == 5
            self.assertLess(normals[5].x, -0.5)
            self.assertEqual(fids[5], 5)

    def test_direct_mesh_multi_chunk_and_uv_rotations(self):
        """Verify Direct Mesh correctly handles multi-chunk atlas textures and native UVMap."""
        from utils.live_sync import VoxelStorage, build_world_mesh

        storage = VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:oak_log[axis=y]")
        storage.set_block(1, 0, 0, "minecraft:water")

        atlas_params = {
            "width": 1024,
            "height": 512,
            "tile_size": 16,
            "tiles_per_row": 64,
            "anim_atlas_width": 896,
            "anim_atlas_height": 1024,
            "mapping": {
                "textures": {
                    "minecraft:block/oak_log": {"chunk_id": 0, "tile_column": 10, "tile_row": 2},
                    "minecraft:block/oak_log_top": {"chunk_id": 0, "tile_column": 11, "tile_row": 2},
                    "minecraft:block/water_still": {
                        "chunk_id": 1,
                        "kind": "animation",
                        "pixel_x": 0,
                        "pixel_y": 0,
                        "frame_width": 16,
                        "frame_height": 16,
                    },
                }
            }
        }

        res = build_world_mesh(bpy.context, storage, atlas_params=atlas_params)
        self.assertIsNotNone(res.world_obj)
        mesh = res.world_obj.data

        self.assertIn("UVMap", mesh.uv_layers)
        self.assertIn("Color", mesh.color_attributes)
        self.assertEqual(res.cubes_count, 1)
        self.assertEqual(res.fluids_count, 1)


if __name__ == "__main__":
    unittest.main()
