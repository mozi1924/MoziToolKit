"""
Tests for Material Hash Validation, Node Tree Rebuilding on Mismatch,
Authoritative Address Table Loading, and Pack Stack Hash Deduplication.
"""

import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
import bpy

from utils.materials.pack import ZipResourcePack, ResourcePackStack
from utils.materials.pipeline.provenance import (
    get_effective_pack_hash,
    is_material_hash_valid,
)
from utils.materials.pipeline.session import (
    name_replaced_material,
    find_existing_replacement,
)
from utils.materials.atlas.builder import build_atlas_chunk_materials
from utils.materials.atlas.addressing import AtlasAddressResolver
from utils.materials.yefira.atlas_integration import (
    extract_atlas_parameters,
    find_all_atlas_chunk_materials,
)
from utils.live_sync.material_manager import LiveSyncMaterialManager


class TestMaterialHashRebuildAndDedup(unittest.TestCase):

    def setUp(self):
        # Clear materials
        for m in list(bpy.data.materials):
            bpy.data.materials.remove(m)
        for img in list(bpy.data.images):
            bpy.data.images.remove(img)

    def test_get_effective_pack_hash_and_validity(self):
        """Verify get_effective_pack_hash handles string, pack, stack, dict, and material datablocks."""
        # 1. Direct string
        self.assertEqual(get_effective_pack_hash("hash_abc123"), "hash_abc123")

        # 2. Dictionary
        self.assertEqual(get_effective_pack_hash({"stack_hash": "stack_111"}), "stack_111")
        self.assertEqual(get_effective_pack_hash({"pack_hash": "pack_222"}), "pack_222")

        # 3. Material datablock
        mat = bpy.data.materials.new(name="Test_Mat_Hash")
        mat["mtk:pack_hash"] = "mat_hash_333"
        self.assertEqual(get_effective_pack_hash(mat), "mat_hash_333")

        # 4. Hash validity test
        self.assertFalse(is_material_hash_valid(mat, "target_444"))

        # When node_tree is cleared (no nodes)
        mat.node_tree.nodes.clear()
        self.assertFalse(is_material_hash_valid(mat, "mat_hash_333"))

        # When node_tree has nodes
        mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
        self.assertTrue(is_material_hash_valid(mat, "mat_hash_333"))

    def test_pack_stack_deduplication_in_session(self):
        """Verify find_existing_replacement and name_replaced_material work consistently with PackStack."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            pack_dir = Path(tmp_dir) / "test_pack"
            pack_dir.mkdir(parents=True)
            (pack_dir / "pack.mcmeta").write_text(
                json.dumps({"pack": {"pack_format": 15, "description": "Test"}})
            )
            tex_dir = pack_dir / "assets" / "minecraft" / "textures" / "block"
            tex_dir.mkdir(parents=True)
            img = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
            img.save(tex_dir / "stone.png")

            pack = ZipResourcePack(str(pack_dir))
            stack = ResourcePackStack([pack])

            tex_info = {
                "namespace": "minecraft",
                "texture_name": "stone",
                "albedo": str(tex_dir / "stone.png"),
            }

            # Initially no replacement material exists
            self.assertIsNone(find_existing_replacement(tex_info, stack))

            # Create and name replacement material using stack
            mat = bpy.data.materials.new(name="test_mat")
            mat.use_nodes = True
            mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
            name_replaced_material(mat, tex_info, stack)

            self.assertEqual(mat.get("mtk:pack_hash"), stack.stack_hash)
            self.assertIn(stack.stack_hash[:12], mat.name)

            # Now find_existing_replacement should find it
            found = find_existing_replacement(tex_info, stack)
            self.assertIsNotNone(found)
            self.assertEqual(found, mat)

            # A different target stack hash should not match
            other_stack_hash = "different_stack_hash_9999"
            self.assertIsNone(find_existing_replacement(tex_info, other_stack_hash))

    def test_node_tree_rebuild_on_hash_mismatch(self):
        """Verify build_atlas_chunk_materials completely resets and rebuilds node tree on hash mismatch."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            atlas_dir = Path(tmp_dir)
            img = Image.new("RGBA", (64, 64), (100, 100, 100, 255))
            img.save(atlas_dir / "blocks_chunk_000_albedo.png")

            mapping = {
                "format_version": 10,
                "chunks": [
                    {
                        "chunk_id": 0,
                        "category": "blocks",
                        "kind": "static",
                        "width": 64,
                        "height": 64,
                        "tile_size": 16,
                        "files": {"albedo": "blocks_chunk_000_albedo.png"},
                    }
                ],
                "textures": {
                    "minecraft:stone": {
                        "chunk_id": 0,
                        "texture_id": 0,
                        "tile_column": 0,
                        "tile_row": 0,
                    }
                },
            }
            (atlas_dir / "atlas_mapping.json").write_text(json.dumps(mapping))

            # Build initial material with hash_A
            mats_a = build_atlas_chunk_materials(atlas_dir, pack_hash="hash_A_111111", pack_textures=False)
            mat0 = mats_a[0]
            self.assertEqual(mat0.get("mtk:pack_hash"), "hash_A_111111")
            self.assertEqual(mat0.node_tree.get("mtk:pack_hash"), "hash_A_111111")

            # Simulate stale node tree: add a dummy node
            dummy_node = mat0.node_tree.nodes.new("ShaderNodeValue")
            dummy_node.name = "Stale_Dummy_Node"
            self.assertIn("Stale_Dummy_Node", mat0.node_tree.nodes)

            # Rebuild with new hash_B -> stale nodes must be wiped and fresh LabPBR tree created
            mats_b = build_atlas_chunk_materials(atlas_dir, pack_hash="hash_B_222222", pack_textures=False)
            mat0_new = mats_b[0]
            self.assertEqual(mat0_new.get("mtk:pack_hash"), "hash_B_222222")
            self.assertEqual(mat0_new.node_tree.get("mtk:pack_hash"), "hash_B_222222")
            self.assertNotIn("Stale_Dummy_Node", mat0_new.node_tree.nodes)
            self.assertIn("LabPBR 1.3 Decoder", mat0_new.node_tree.nodes)

    def test_livesync_material_manager_hash_mismatch_rebuild(self):
        """Verify LiveSyncMaterialManager detects hash mismatch and rebuilds all chunk materials from authoritative cache."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            atlas_dir = Path(tmp_dir)
            img = Image.new("RGBA", (64, 64), (100, 100, 100, 255))
            img.save(atlas_dir / "blocks_chunk_000_albedo.png")

            mapping = {
                "format_version": 10,
                "chunks": [
                    {
                        "chunk_id": 0,
                        "category": "blocks",
                        "kind": "static",
                        "width": 64,
                        "height": 64,
                        "tile_size": 16,
                        "files": {"albedo": "blocks_chunk_000_albedo.png"},
                    }
                ],
                "textures": {
                    "minecraft:stone": {
                        "chunk_id": 0,
                        "texture_id": 0,
                        "tile_column": 0,
                        "tile_row": 0,
                    }
                },
            }
            (atlas_dir / "atlas_mapping.json").write_text(json.dumps(mapping))

            # Create an existing world object with an outdated material
            mesh = bpy.data.meshes.new("TestWorldMesh")
            obj = bpy.data.objects.new("TestWorldObj", mesh)
            bpy.context.collection.objects.link(obj)

            old_mat = bpy.data.materials.new("MC_Atlas_Chunk_0")
            old_mat.use_nodes = True
            old_mat["mtk:atlas_chunk_id"] = 0
            old_mat["mtk:pack_hash"] = "outdated_hash_old"
            old_mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
            obj.data.materials.append(old_mat)

            # MaterialManager targeting "new_target_hash"
            atlas_params = {
                "pack_hash": "new_target_hash",
                "mapping": mapping,
            }

            mat_mgr = LiveSyncMaterialManager(world_obj=obj, atlas_params=atlas_params)

            # Old material must NOT be used because its hash was outdated
            self.assertNotIn(0, mat_mgr.chunk_materials)

            # Calling ensure_chunk_loaded with valid atlas directory should build fresh material
            mat_mgr._atlas_dir = atlas_dir
            slot_idx = mat_mgr.ensure_chunk_loaded(0)
            self.assertEqual(slot_idx, 0)
            self.assertIn(0, mat_mgr.chunk_materials)
            self.assertEqual(mat_mgr.chunk_materials[0].get("mtk:pack_hash"), "new_target_hash")

            # Cleanup
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(mesh)

    def test_extract_atlas_parameters_with_none_mat(self):
        """Verify extract_atlas_parameters does not crash when mat is None."""
        params = extract_atlas_parameters(mat=None)
        self.assertIsNotNone(params)
        self.assertIn("tile_size", params)
        self.assertIn("width", params)
        self.assertIn("height", params)


if __name__ == "__main__":
    unittest.main()
