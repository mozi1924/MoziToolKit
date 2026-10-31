"""
Tests for Dynamic Entities Material Pipeline and VoxelWorld Entity Integration.
"""

import json
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
libmtk_release_path = PROJECT_DIR.parent / "libmozitoolkit" / "target" / "release"

for p in [str(libmtk_release_path), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import bpy
    from unittest.mock import MagicMock
    HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "materials") and not isinstance(bpy.data, MagicMock)
except ImportError:
    bpy = None
    HAS_BPY = False

try:
    import libmtk_py
    HAS_LIBMTK = True
except ImportError:
    libmtk_py = None
    HAS_LIBMTK = False

from MoziToolKit.utils.materials.builder.dynamic_entities import (
    DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID,
    DYNAMIC_CHUNK_END,
    DYNAMIC_CHUNK_START,
    DYNAMIC_ENTITIES_IMAGE_NAME,
    DYNAMIC_ENTITIES_MATERIAL_NAME,
    build_dynamic_entities_material,
    dynamic_entities_image_name,
    dynamic_entities_material_name,
    update_dynamic_entities_image,
)


class TestDynamicEntitiesMaterial(unittest.TestCase):
    def test_dynamic_entities_chunk_id_constant(self):
        """Dynamic entity atlas chunk ID must be 0xFFF0 (65520)."""
        self.assertEqual(DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID, 0xFFF0)
        self.assertEqual(DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID, 65520)

    def test_update_dynamic_entities_image_guard(self):
        """Guards against short or invalid buffer without crashing."""
        # Buffer smaller than 1024*1024*4 must be rejected
        short_buf = b"\x00" * 100
        result = update_dynamic_entities_image(short_buf)
        self.assertIsNone(result)

    @unittest.skipUnless(HAS_LIBMTK, "libmtk_py is required for voxel world dynamic entity test")
    def test_voxel_world_dynamic_entity_atlas_generation(self):
        """VoxelWorld resolves skull, allocates slot in 1024x1024 atlas, and meshes to slot 0xFFF0."""
        world = libmtk_py.VoxelWorld()
        # Atlas is pre-warmed with 16 vanilla banner dye base slots in chunk 0xFFF0
        init_atlas = world.get_dynamic_entity_atlas()
        self.assertIsNotNone(init_atlas)
        self.assertEqual(len(init_atlas), 1024 * 1024 * 4)

        world.set_block(2, 2, 2, "minecraft:player_head[rotation=0]", None)
        skull_json = {
            "id": "minecraft:skull",
            "kind": "player",
            "rotation": 0,
            "profile": {
                "name": "Steve",
                "id": "00000000-0000-0000-0000-000000000000",
                "skin_url": "https://textures.minecraft.net/texture/2724ab65dec7d77b07238a4c9bc075501630608aed6f0c1118777017bd2c0cb",
            },
        }
        world.set_block_entity_json(2, 2, 2, json.dumps(skull_json))

        # Block entity JSON retrieval
        stored = world.get_block_entity_json(2, 2, 2)
        self.assertIsNotNone(stored)
        stored_dict = json.loads(stored)
        self.assertEqual(stored_dict.get("id"), "minecraft:skull")
        self.assertEqual(stored_dict.get("kind"), "player")

        # Point cloud preservation
        cloud = world.to_point_cloud()
        palette = cloud.get_entity_palette()
        self.assertEqual(len(palette), 1)
        self.assertIn("minecraft:skull", palette[0])

        # Storage roundtrip
        st2 = cloud.to_storage()
        stored2 = st2.get_block_entity_json(2, 2, 2)
        self.assertIsNotNone(stored2)
        self.assertEqual(json.loads(stored2).get("id"), "minecraft:skull")

        # 1. Non-blocking initial rebuild builds world immediately without stalling
        mesh_initial = world.rebuild_all()
        self.assertGreater(mesh_initial.face_count, 0)

        # 2. Synchronous resolve (simulating background download arrival)
        if hasattr(world, "ensure_dynamic_entities_resolved_sync"):
            world.ensure_dynamic_entities_resolved_sync()

        mesh = world.rebuild_all()
        self.assertGreater(mesh.face_count, 0)
        used_mats = mesh.used_materials()
        self.assertIn(DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID, used_mats)

        atlas_bytes = world.get_dynamic_entity_atlas()
        self.assertIsNotNone(atlas_bytes)
        self.assertEqual(len(atlas_bytes), 1024 * 1024 * 4)

        # Dynamic entity atlases dictionary
        atlases_dict = world.get_dynamic_entity_atlases()
        self.assertIsNotNone(atlases_dict)
        self.assertIn(DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID, atlases_dict)
        self.assertEqual(bytes(atlases_dict[DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID]), bytes(atlas_bytes))

        # PyMeshData dynamic_entity_atlases
        self.assertIsNotNone(mesh.dynamic_entity_atlases)
        self.assertIn(DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID, mesh.dynamic_entity_atlases)
        self.assertEqual(bytes(mesh.dynamic_entity_atlases[DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID]), bytes(atlas_bytes))

    @unittest.skipUnless(HAS_BPY, "bpy is required for Blender material node tree test")
    def test_build_dynamic_entities_material_bpy(self):
        """build_dynamic_entities_material creates Principled BSDF with Closest texture."""
        mat = build_dynamic_entities_material()
        self.assertIsNotNone(mat)
        self.assertEqual(mat.get("mtk_atlas_chunk_id"), DEFAULT_DYNAMIC_ENTITIES_CHUNK_ID)
        self.assertEqual(mat.name, DYNAMIC_ENTITIES_MATERIAL_NAME)

        nodes = mat.node_tree.nodes
        tex_node = nodes.get("DynamicAtlasTex")
        self.assertIsNotNone(tex_node)
        self.assertEqual(tex_node.interpolation, "Closest")

    @unittest.skipUnless(HAS_BPY and HAS_LIBMTK, "bpy and libmtk_py required for full DCC hierarchy test")
    def test_update_world_mesh_dynamic_entity_binding_bpy(self):
        """update_world_mesh injects geometry, creates image in memory, and binds dynamic entity material slot."""
        world = libmtk_py.VoxelWorld()
        world.set_block(2, 2, 2, "minecraft:player_head[rotation=0]", None)
        hash_str = "2724ab65dec7d77b07238a4c9bc075501630608aed6f0c1118777017bd2c0cb"
        skull_json = {
            "id": "minecraft:skull",
            "kind": "player",
            "rotation": 0,
            "profile": {
                "name": "Steve",
                "id": "00000000-0000-0000-0000-000000000000",
                "skin_url": f"http://textures.minecraft.net/texture/{hash_str}",
            },
        }
        world.set_block_entity_json(2, 2, 2, json.dumps(skull_json))
        world.ensure_dynamic_entities_resolved_sync()
        mesh = world.rebuild_all()
        atlas_bytes = world.get_dynamic_entity_atlas()
        self.assertIsNotNone(atlas_bytes)

        # PyMeshData itself must now carry dynamic_entity_atlas directly
        self.assertIsNotNone(mesh.dynamic_entity_atlas)
        self.assertEqual(len(mesh.dynamic_entity_atlas), 1024 * 1024 * 4)
        self.assertEqual(bytes(mesh.dynamic_entity_atlas), bytes(atlas_bytes))

        # Create host object
        b_mesh = bpy.data.meshes.new("TestDynamicWorldMesh")
        b_obj = bpy.data.objects.new("TestDynamicWorldObj", b_mesh)
        bpy.context.scene.collection.objects.link(b_obj)

        try:
            from MoziToolKit.operators.sync.hierarchy import update_world_mesh
            # Call without passing dynamic_entity_atlas explicitly; should auto-extract from mesh.dynamic_entity_atlas
            v_cnt, f_cnt = update_world_mesh(b_obj, mesh)
            self.assertGreater(v_cnt, 0)
            self.assertGreater(f_cnt, 0)

            # Verify image exists in bpy.data.images with direct memory injection
            img = bpy.data.images.get(DYNAMIC_ENTITIES_IMAGE_NAME)
            self.assertIsNotNone(img)
            self.assertEqual(img.size[0], 1024)
            self.assertEqual(img.size[1], 1024)

            # Verify material slot on object
            mat_names = [m.name for m in b_obj.data.materials if m is not None]
            self.assertIn(DYNAMIC_ENTITIES_MATERIAL_NAME, mat_names)

            # Verify skull face material index
            slot_idx = mat_names.index(DYNAMIC_ENTITIES_MATERIAL_NAME)
            poly_mats = [p.material_index for p in b_obj.data.polygons]
            self.assertIn(slot_idx, poly_mats)

            # Verify texture image is attached to DynamicAtlasTex node
            dyn_mat = b_obj.data.materials[slot_idx]
            tex_node = dyn_mat.node_tree.nodes.get("DynamicAtlasTex")
            self.assertIsNotNone(tex_node)
            self.assertEqual(tex_node.image, img)

            # Test fast-path re-binding: clear image node, update again, verify it gets restored
            tex_node.image = None
            update_world_mesh(b_obj, mesh)
            self.assertEqual(tex_node.image, img)
        finally:
            bpy.data.objects.remove(b_obj, do_unlink=True)
            bpy.data.meshes.remove(b_mesh)

    @unittest.skipUnless(HAS_BPY, "bpy is required for multi-chunk material test")
    def test_multi_chunk_dynamic_entities_material_bpy(self):
        """Dynamic entities material builder creates unique materials and images per chunk ID."""
        chunk_0 = 0xFFF0
        chunk_1 = 0xFFF1
        self.assertEqual(dynamic_entities_material_name(chunk_0), DYNAMIC_ENTITIES_MATERIAL_NAME)
        self.assertEqual(dynamic_entities_material_name(chunk_1), "MTK:Atlas:entities:dynamic_FFF1")
        self.assertEqual(dynamic_entities_image_name(chunk_0), DYNAMIC_ENTITIES_IMAGE_NAME)
        self.assertEqual(dynamic_entities_image_name(chunk_1), "MTK_Dynamic_Entities_Atlas_FFF1")

        mat1 = build_dynamic_entities_material(chunk_id=chunk_1)
        self.assertIsNotNone(mat1)
        self.assertEqual(mat1.get("mtk_atlas_chunk_id"), chunk_1)
        self.assertEqual(mat1.name, "MTK:Atlas:entities:dynamic_FFF1")

    @unittest.skipUnless(HAS_BPY, "bpy is required for multi-chunk world binding test")
    def test_multi_chunk_world_binding_bpy(self):
        """ensure_world_materials binds multiple dynamic entity chunk materials from a dict."""
        from MoziToolKit.utils.materials.builder.world_binding import ensure_world_materials

        b_mesh = bpy.data.meshes.new("TestMultiChunkMesh")
        verts = [
            (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
            (2, 0, 0), (3, 0, 0), (3, 1, 0), (2, 1, 0),
        ]
        faces = [(0, 1, 2, 3), (4, 5, 6, 7)]
        b_mesh.from_pydata(verts, [], faces)

        b_mesh.attributes.new(name="mtk_atlas_chunk_id", type="INT", domain="FACE")
        b_mesh.attributes["mtk_atlas_chunk_id"].data[0].value = 0xFFF0
        b_mesh.attributes["mtk_atlas_chunk_id"].data[1].value = 0xFFF1

        b_obj = bpy.data.objects.new("TestMultiChunkObj", b_mesh)
        bpy.context.scene.collection.objects.link(b_obj)

        dummy_buf_0 = b"\x11" * (1024 * 1024 * 4)
        dummy_buf_1 = b"\x22" * (1024 * 1024 * 4)

        try:
            ensure_world_materials(
                b_obj,
                used_chunk_ids=[0xFFF0, 0xFFF1],
                dynamic_entity_atlas={
                    0xFFF0: dummy_buf_0,
                    0xFFF1: dummy_buf_1,
                },
            )

            mat_names = [m.name for m in b_obj.data.materials if m is not None]
            self.assertIn("MTK:Atlas:entities:dynamic", mat_names)
            self.assertIn("MTK:Atlas:entities:dynamic_FFF1", mat_names)

            # Polygons mapped to their respective slots
            p0_mat = b_obj.data.materials[b_obj.data.polygons[0].material_index]
            p1_mat = b_obj.data.materials[b_obj.data.polygons[1].material_index]
            self.assertEqual(p0_mat.name, "MTK:Atlas:entities:dynamic")
            self.assertEqual(p1_mat.name, "MTK:Atlas:entities:dynamic_FFF1")
        finally:
            bpy.data.objects.remove(b_obj, do_unlink=True)
            bpy.data.meshes.remove(b_mesh)


if __name__ == "__main__":
    unittest.main()
