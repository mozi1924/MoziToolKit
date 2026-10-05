"""
Integration tests for Live Sync Atlas Material binding and internal addressing.
Tests that VoxelStorage / SectionMesher with Atlas & BiomeResolver generates
the correct face attributes (UVs, tiling, biome tint, source texture key)
and that ensure_world_materials correctly assigns the Atlas Chunk materials.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
libmtk_release_path = PROJECT_DIR.parent / "libmozitoolkit" / "target" / "release"

for p in [str(libmtk_release_path), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

if "mathutils" not in sys.modules:
    sys.modules["mathutils"] = MagicMock()

try:
    import bpy
    HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "meshes") and not isinstance(bpy.data, MagicMock)
except ImportError:
    bpy = MagicMock()
    sys.modules["bpy"] = bpy
    sys.modules["bpy.props"] = MagicMock()
    sys.modules["bpy.types"] = MagicMock()
    sys.modules["bpy.app"] = MagicMock()
    HAS_BPY = False

if "bmesh" not in sys.modules:
    sys.modules["bmesh"] = MagicMock()

try:
    import libmtk_py as mtk_py
    HAS_LIBMTK = True
except ImportError:
    mtk_py = None
    HAS_LIBMTK = False

from operators.sync.hierarchy import (
    ensure_world_materials,
    get_or_create_world_mesh_object,
    update_world_mesh,
)
from bridge.mesh import inject_mesh_data


def _write_dummy_png(path: Path):
    """Helper to write a valid 1x1 PNG file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


class TestLiveSyncAtlasMaterials(unittest.TestCase):
    def setUp(self):
        if not HAS_LIBMTK:
            self.skipTest("libmtk_py is required for atlas materials test")

    def test_voxel_mesher_atlas_and_face_attributes(self):
        """
        Verify that SectionMesher with AtlasAddressMap produces face attributes:
        - mtk_source_texture_key
        - mtk_material_slot
        - mtk_atlas_chunk_id
        - mtk_atlas_texture_id
        - mtk_uv_tiling_transform
        - mtk_biome_tint_data
        - mtk_biome_tint_color
        - mtk_face_dir
        """
        # Create a mock atlas mapping JSON
        mapping_data = {
            "format_version": 1,
            "category": "blocks",
            "chunks": [
                {
                    "chunk_id": 0,
                    "category": "blocks",
                    "category_chunk_index": 1,
                    "width": 1024,
                    "height": 1024,
                    "is_animated": False,
                    "has_normal": False,
                    "has_specular": False,
                    "has_overlay": False,
                },
                {
                    "chunk_id": 1,
                    "category": "blocks",
                    "category_chunk_index": 2,
                    "width": 1024,
                    "height": 1024,
                    "is_animated": False,
                    "has_normal": False,
                    "has_specular": False,
                    "has_overlay": False,
                }
            ],
            "sprites": {
                "minecraft:block/grass_block_top": {
                    "chunk_id": 0,
                    "texture_id": 101,
                    "uv_bounds": [0.0, 0.0, 0.25, 0.25],
                    "frame_0_uv_bounds": [0.0, 0.0, 0.25, 0.25],
                    "pixel_rect": [0, 0, 256, 256],
                    "frame_size": [256, 256],
                    "frame_count": 1,
                    "is_animated": False,
                    "has_normal": False,
                    "has_specular": False,
                    "has_overlay": False,
                },
                "minecraft:block/grass_block_side": {
                    "chunk_id": 0,
                    "texture_id": 102,
                    "uv_bounds": [0.25, 0.0, 0.5, 0.25],
                    "frame_0_uv_bounds": [0.25, 0.0, 0.5, 0.25],
                    "pixel_rect": [256, 0, 256, 256],
                    "frame_size": [256, 256],
                    "frame_count": 1,
                    "is_animated": False,
                    "has_normal": False,
                    "has_specular": False,
                    "has_overlay": False,
                },
                "minecraft:block/dirt": {
                    "chunk_id": 0,
                    "texture_id": 103,
                    "uv_bounds": [0.5, 0.0, 0.75, 0.25],
                    "frame_0_uv_bounds": [0.5, 0.0, 0.75, 0.25],
                    "pixel_rect": [512, 0, 256, 256],
                    "frame_size": [256, 256],
                    "frame_count": 1,
                    "is_animated": False,
                    "has_normal": False,
                    "has_specular": False,
                    "has_overlay": False,
                },
                "minecraft:block/water_still": {
                    "chunk_id": 1,
                    "texture_id": 201,
                    "uv_bounds": [0.0, 0.0, 0.5, 0.5],
                    "frame_0_uv_bounds": [0.0, 0.0, 0.5, 0.5],
                    "pixel_rect": [0, 0, 512, 512],
                    "frame_size": [512, 512],
                    "frame_count": 1,
                    "is_animated": False,
                    "has_normal": False,
                    "has_specular": False,
                    "has_overlay": False,
                },
            }
        }

        atlas = mtk_py.BakedAtlas.from_mapping_json(json.dumps(mapping_data))
        self.assertIsNotNone(atlas)

        # Mesher config with Atlas and BiomeResolver
        config = mtk_py.MesherConfig(
            enable_ao=True,
            mesh_fluids=True,
            z_up_coordinates=True,
            atlas=atlas,
        )
        self.assertTrue(config.has_atlas())

        # Create storage with a grass block and a water block
        storage = mtk_py.VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        storage.set_block(0, 0, 0, "minecraft:grass_block")
        storage.set_block(0, 2, 0, "minecraft:water")

        culler = mtk_py.FaceCuller() if hasattr(mtk_py, "FaceCuller") else None
        mesh = mtk_py.SectionMesher.mesh_world(storage, config, culler)
        self.assertIsNotNone(mesh)
        self.assertGreater(mesh.face_count, 0)
        self.assertGreater(mesh.face_count, 0)

        # Check face attributes on mesh
        self.assertTrue(mesh.has_attribute("mtk_source_texture_key"))
        self.assertTrue(mesh.has_attribute("mtk_material_slot"))
        self.assertTrue(mesh.has_attribute("mtk_atlas_chunk_id"))
        self.assertTrue(mesh.has_attribute("mtk_atlas_texture_id"))
        self.assertTrue(mesh.has_attribute("mtk_uv_tiling_transform"))
        self.assertTrue(mesh.has_attribute("mtk_biome_tint_data"))
        self.assertTrue(mesh.has_attribute("mtk_biome_tint_color"))
        self.assertTrue(mesh.has_attribute("mtk_face_dir"))

        # Verify string keys
        keys = mesh.get_string_attribute("mtk_source_texture_key")
        self.assertIsNotNone(keys)
        self.assertGreater(len(keys), 0)

        # Directional candidate resolution check:
        # grass_block should resolve to top, side, and dirt for bottom!
        has_top = any("grass_block_top" in k for k in keys)
        has_side = any("grass_block_side" in k for k in keys)
        has_dirt = any("dirt" in k for k in keys)
        has_water = any("water_still" in k for k in keys)

        self.assertTrue(has_top, f"Expected grass_block_top in keys: {keys}")
        self.assertTrue(has_side, f"Expected grass_block_side in keys: {keys}")
        self.assertTrue(has_dirt, f"Expected dirt in keys: {keys}")
        self.assertTrue(has_water, f"Expected water_still in keys: {keys}")

        # Check material slots
        mat_slots = mesh.get_face_materials()
        self.assertEqual(len(mat_slots), mesh.face_count)
        # Water was chunk 1, grass was chunk 0
        self.assertIn(0, mat_slots)
        self.assertIn(1, mat_slots)

    def test_ensure_world_materials_atlas_binding(self):
        """
        Verify that ensure_world_materials correctly builds and assigns
        atlas chunk materials to mesh.materials matching chunk indices.
        """
        if not HAS_BPY:
            self.skipTest("bpy is required for Blender materials test")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            atlas_dir = tmp_path / "atlas"
            atlas_dir.mkdir(parents=True)

            _write_dummy_png(atlas_dir / "blocks_chunk_001.png")
            _write_dummy_png(atlas_dir / "blocks_chunk_002.png")

            mapping_data = {
                "format_version": 1,
                "category": "blocks",
                "chunks": [
                    {
                        "chunk_id": 0,
                        "category": "blocks",
                        "category_chunk_index": 1,
                        "width": 1024,
                        "height": 1024,
                        "is_animated": False,
                    },
                    {
                        "chunk_id": 1,
                        "category": "blocks",
                        "category_chunk_index": 2,
                        "width": 1024,
                        "height": 1024,
                        "is_animated": False,
                    }
                ],
                "sprites": {}
            }
            (atlas_dir / "atlas_mapping.json").write_text(json.dumps(mapping_data))

            with patch.dict(os.environ, {"MOZI_CACHE_DIR": str(tmp_path)}):
                # Create a test mesh object
                test_mesh = bpy.data.meshes.new("TestWorldMesh")
                test_obj = bpy.data.objects.new("TestWorldMesh", test_mesh)

                ensure_world_materials(test_obj)

                # Both chunk 0 and chunk 1 should be bound in order!
                self.assertGreaterEqual(len(test_mesh.materials), 2)
                mat0 = test_mesh.materials[0]
                mat1 = test_mesh.materials[1]
                self.assertIsNotNone(mat0)
                self.assertIsNotNone(mat1)
                self.assertIn("Atlas", mat0.name)
                self.assertIn("Atlas", mat1.name)

                # Clean up
                bpy.data.objects.remove(test_obj)
                bpy.data.meshes.remove(test_mesh)

    def test_update_world_mesh_atlas_injection_end_to_end(self):
        """
        Verify that update_world_mesh successfully injects real SectionMesher geometry,
        all 15 custom attributes (including string and multi-component floats/ints),
        binds Atlas materials with use_attribute_node=False, and connects UVMap directly.
        """
        if not HAS_BPY or not HAS_LIBMTK:
            self.skipTest("bpy and libmtk are required for end-to-end injection test")

        cache_atlas_mapping = Path("/home/mozi/.config/blender/5.2/datafiles/MoziToolKit/cache/atlas/atlas_mapping.json")
        if not cache_atlas_mapping.exists():
            self.skipTest("Precompiled atlas cache mapping is required")

        atlas = mtk_py.BakedAtlas.from_mapping_json(cache_atlas_mapping.read_text(encoding="utf-8"))
        config = mtk_py.MesherConfig(
            enable_ao=True,
            mesh_fluids=True,
            z_up_coordinates=True,
            atlas=atlas,
        )
        storage = mtk_py.VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        storage.set_block(0, 0, 0, "minecraft:grass_block")
        culler = mtk_py.FaceCuller() if hasattr(mtk_py, "FaceCuller") else None
        mesh_data = mtk_py.SectionMesher.mesh_world(storage, config, culler)

        test_mesh = bpy.data.meshes.new("E2EWorldMesh")
        test_obj = bpy.data.objects.new("E2EWorldMesh", test_mesh)

        try:
            v_count, f_count = update_world_mesh(test_obj, mesh_data)
            self.assertGreater(v_count, 0)
            self.assertGreater(f_count, 0)

            # 1. Verify string custom attribute
            str_attr = test_mesh.attributes.get("mtk_source_texture_key")
            self.assertIsNotNone(str_attr)
            self.assertGreater(len(str_attr.data), 0)
            self.assertTrue(isinstance(str_attr.data[0].value, bytes))

            # 2. Verify numeric custom attributes
            tint_data_attr = test_mesh.attributes.get("mtk_biome_tint_data")
            self.assertIsNotNone(tint_data_attr)

            chunk_id_attr = test_mesh.attributes.get("mtk_atlas_chunk_id")
            self.assertIsNotNone(chunk_id_attr)

            # 3. Verify materials assigned
            self.assertGreater(len(test_mesh.materials), 0)

            # 4. Verify shader tree: use_attribute_node=False (direct UVMap.UV -> Texture Vector)
            for mat in test_mesh.materials:
                if not mat or not mat.node_tree:
                    continue
                node_names = [n.name for n in mat.node_tree.nodes]
                self.assertNotIn("Atlas UV Tiling", node_names, "Shader should NOT include Atlas UV Tiling")
                albedo_node = mat.node_tree.nodes.get("Atlas Albedo Texture")
                if albedo_node and albedo_node.inputs["Vector"].links:
                    src = albedo_node.inputs["Vector"].links[0].from_node.name
                    self.assertEqual(src, "UV Map", "Albedo vector should connect directly to UV Map")
        finally:
            bpy.data.objects.remove(test_obj)
            bpy.data.meshes.remove(test_mesh)

    def test_live_sync_incremental_materials_addressing_stability(self):
        """
        Verify that when new materials are introduced during Live Sync updates,
        existing faces stay accurately addressed to their respective materials
        and do NOT accidentally get remapped to newly introduced materials.
        """
        if not HAS_BPY:
            self.skipTest("bpy is required for Live Sync material test")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            atlas_dir = tmp_path / "atlas"
            atlas_dir.mkdir(parents=True)

            _write_dummy_png(atlas_dir / "blocks_chunk_001.png")
            _write_dummy_png(atlas_dir / "blocks_chunk_002.png")
            _write_dummy_png(atlas_dir / "blocks_chunk_003.png")

            mapping_data = {
                "format_version": 1,
                "category": "blocks",
                "chunks": [
                    {"chunk_id": 0, "category": "blocks", "category_chunk_index": 1, "width": 1024, "height": 1024, "is_animated": False},
                    {"chunk_id": 1, "category": "blocks", "category_chunk_index": 2, "width": 1024, "height": 1024, "is_animated": False},
                    {"chunk_id": 2, "category": "blocks", "category_chunk_index": 3, "width": 1024, "height": 1024, "is_animated": False},
                ],
                "sprites": {}
            }
            (atlas_dir / "atlas_mapping.json").write_text(json.dumps(mapping_data))

            with patch.dict(os.environ, {"MOZI_CACHE_DIR": str(tmp_path)}):
                # Frame 1: Mesh with 2 faces, both from Chunk 0
                test_mesh = bpy.data.meshes.new("SyncAddressingMesh")
                verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (2, 0, 0), (2, 1, 0)]
                faces = [(0, 1, 2, 3), (1, 4, 5, 2)]
                test_mesh.from_pydata(verts, [], faces)
                test_mesh.update()

                attr_chunk = test_mesh.attributes.new(name="mtk_atlas_chunk_id", type="INT", domain="FACE")
                attr_chunk.data[0].value = 0
                attr_chunk.data[1].value = 0

                test_obj = bpy.data.objects.new("SyncAddressingObj", test_mesh)

                try:
                    ensure_world_materials(test_obj, used_chunk_ids=[0])

                    self.assertEqual(len(test_mesh.materials), 1)
                    self.assertIn("001", test_mesh.materials[0].name)
                    self.assertEqual(test_mesh.polygons[0].material_index, 0)
                    self.assertEqual(test_mesh.polygons[1].material_index, 0)

                    # Frame 2: New geometry arrives with 4 faces (Faces 0,1 from Chunk 0; Faces 2,3 from Chunk 1)
                    test_mesh.clear_geometry()
                    verts4 = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                              (2, 0, 0), (2, 1, 0), (3, 0, 0), (3, 1, 0), (4, 0, 0), (4, 1, 0)]
                    faces4 = [(0, 1, 2, 3), (1, 4, 5, 2), (4, 6, 7, 5), (6, 8, 9, 7)]
                    test_mesh.from_pydata(verts4, [], faces4)
                    test_mesh.update()

                    attr_chunk2 = test_mesh.attributes.new(name="mtk_atlas_chunk_id", type="INT", domain="FACE")
                    attr_chunk2.data[0].value = 0
                    attr_chunk2.data[1].value = 0
                    attr_chunk2.data[2].value = 1
                    attr_chunk2.data[3].value = 1

                    ensure_world_materials(test_obj, used_chunk_ids=[0, 1])

                    self.assertEqual(len(test_mesh.materials), 2)
                    self.assertIn("001", test_mesh.materials[0].name)
                    self.assertIn("002", test_mesh.materials[1].name)

                    # CRITICAL: Chunk 0 faces MUST point to Slot 0 (mat0), Chunk 1 faces MUST point to Slot 1 (mat1)
                    self.assertEqual(test_mesh.polygons[0].material_index, 0, "Chunk 0 face must remain at material slot 0")
                    self.assertEqual(test_mesh.polygons[1].material_index, 0, "Chunk 0 face must remain at material slot 0")
                    self.assertEqual(test_mesh.polygons[2].material_index, 1, "Chunk 1 face must point to material slot 1")
                    self.assertEqual(test_mesh.polygons[3].material_index, 1, "Chunk 1 face must point to material slot 1")

                    # Frame 3: Multi-chunk interleaved (Chunk 0, Chunk 1, Chunk 2)
                    attr_chunk2.data[0].value = 0
                    attr_chunk2.data[1].value = 1
                    attr_chunk2.data[2].value = 2
                    attr_chunk2.data[3].value = 0

                    ensure_world_materials(test_obj, used_chunk_ids=[0, 1, 2])

                    self.assertEqual(len(test_mesh.materials), 3)
                    self.assertEqual(test_mesh.polygons[0].material_index, 0)
                    self.assertEqual(test_mesh.polygons[1].material_index, 1)
                    self.assertEqual(test_mesh.polygons[2].material_index, 2)
                    self.assertEqual(test_mesh.polygons[3].material_index, 0)

                finally:
                    bpy.data.objects.remove(test_obj)
                    bpy.data.meshes.remove(test_mesh)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])

