"""
Tests for Connected Textures Mod (CTM) integration:
- Modrinth API fetcher bridge
- CTM solver loading from resource packs
- Voxel world meshing in Atlas and Standalone modes with CTM
- Standalone material resolution and scene mesh loading in Blender
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
libmtk_release_path = PROJECT_DIR.parent / "libmozitoolkit" / "target" / "release"

for p in [str(libmtk_release_path), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import bpy
    HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "meshes") and not isinstance(bpy.data, MagicMock)
except ImportError:
    bpy = MagicMock()
    sys.modules["bpy"] = bpy
    HAS_BPY = False

from bridge.engine import get_libmtk
from bridge.assets.modrinth import (
    RECOMMENDED_CTM_PACKS,
    search_modrinth_packs,
    get_project_versions,
    fetch_modrinth_pack,
)
from bridge.assets.pack import get_configured_ctm_solver
from bridge.world import mesh_voxel_storage, apply_voxel_mesh_to_blender
from tests._assets import require_ctm_resource_pack, ctm_resource_pack_zip


def _create_synthetic_ctm_pack(zip_path: Path) -> Path:
    """Creates a minimal synthetic resource pack with Compact CTM for testing."""
    with zipfile.ZipFile(zip_path, "w") as zf:
        # pack.mcmeta
        pack_mcmeta = {
            "pack": {
                "pack_format": 15,
                "description": "Synthetic CTM Test Pack"
            }
        }
        zf.writestr("pack.mcmeta", json.dumps(pack_mcmeta))

        # CTM properties for glass (compact)
        props = (
            "matchBlocks=minecraft:glass\n"
            "method=ctm_compact\n"
            "tiles=0-4\n"
            "connect=block\n"
        )
        zf.writestr("assets/minecraft/optifine/ctm/glass/glass.properties", props)

        # 5 dummy 1x1 png images (compact ctm tiles 0..4)
        png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        for i in range(5):
            zf.writestr(f"assets/minecraft/optifine/ctm/glass/{i}.png", png_bytes)

        # Full 47-tile CTM properties for white_stained_glass
        props_47 = (
            "matchBlocks=minecraft:white_stained_glass\n"
            "method=ctm\n"
            "tiles=0-46\n"
            "connect=block\n"
        )
        zf.writestr("assets/minecraft/optifine/ctm/white_glass/glass.properties", props_47)
        for i in range(47):
            zf.writestr(f"assets/minecraft/optifine/ctm/white_glass/{i}.png", png_bytes)

    return zip_path


class TestCtmBridge(unittest.TestCase):

    def setUp(self):
        self.mtk = get_libmtk()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.synthetic_pack_zip = Path(self.tmp_dir.name) / "synthetic_ctm.zip"
        _create_synthetic_ctm_pack(self.synthetic_pack_zip)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_modrinth_constants_and_structure(self):
        """Verify recommended CTM packs metadata structure."""
        self.assertTrue(len(RECOMMENDED_CTM_PACKS) >= 3)
        slugs = [p["slug"] for p in RECOMMENDED_CTM_PACKS]
        self.assertIn("clean-connected-glass", slugs)
        self.assertIn("vanilla-connected-glass", slugs)

    def test_synthetic_ctm_solver_construction(self):
        """Verify CtmSolver parses the synthetic CTM pack properly."""
        if self.mtk is None or not hasattr(self.mtk, "ResourcePackStack"):
            self.skipTest("libmtk_py ResourcePackStack not available")

        stack = self.mtk.ResourcePackStack()
        stack.add_zip_pack(str(self.synthetic_pack_zip))

        self.assertEqual(stack.get_ctm_rule_count(), 2)
        solver = stack.build_ctm_solver()
        self.assertIsNotNone(solver)
        self.assertEqual(solver.rule_count, 2)

    def test_configured_ctm_solver_helper(self):
        """Verify bridge helper get_configured_ctm_solver loads rules."""
        if self.mtk is None or not hasattr(self.mtk, "ResourcePackStack"):
            self.skipTest("libmtk_py ResourcePackStack not available")

        mock_prefs = MagicMock()
        mock_prefs.resource_pack_path = str(self.synthetic_pack_zip)
        mock_prefs.resource_packs = []

        solver = get_configured_ctm_solver(mock_prefs)
        self.assertIsNotNone(solver)
        self.assertGreaterEqual(solver.rule_count, 1)

    def test_ctm_meshing_standalone_mode(self):
        """Verify voxel storage meshing in Standalone mode resolves CTM face texture keys."""
        if self.mtk is None or not hasattr(self.mtk, "VoxelStorage"):
            self.skipTest("libmtk_py VoxelStorage not available")

        stack = self.mtk.ResourcePackStack()
        stack.add_zip_pack(str(self.synthetic_pack_zip))
        solver = stack.build_ctm_solver()

        # Place 2 adjacent glass blocks at (0,0,0) and (1,0,0)
        storage = self.mtk.VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:glass")
        storage.set_block(1, 0, 0, "minecraft:glass")

        # Mesh in Standalone mode (atlas=None)
        mesh_data, elapsed_ms = mesh_voxel_storage(
            storage=storage,
            atlas=None,
            ctm_solver=solver,
            material_mode="STANDALONE",
            origin_centered=False,
            weld_vertices=False,
        )

        self.assertIsNotNone(mesh_data)
        self.assertGreater(mesh_data.vertex_count, 0)
        self.assertGreater(mesh_data.quad_count, 0)

        # Standalone mode must emit mtk_source_texture_key
        self.assertTrue(mesh_data.has_attribute("mtk_source_texture_key"))
        keys = mesh_data.get_string_attribute("mtk_source_texture_key")
        self.assertEqual(len(keys), mesh_data.quad_count)

        # Verify that resolved keys contain CTM sub-tile locations
        # For glass with compact CTM, connected faces should resolve to optifine/ctm/glass sub-tiles
        ctm_subtile_found = any("optifine/ctm/glass" in k or "minecraft:optifine" in k for k in keys)
        self.assertTrue(
            ctm_subtile_found,
            f"Expected CTM sub-tile in resolved keys, got: {set(keys)}"
        )

    def test_ctm_meshing_with_real_clean_connected_glass(self):
        """Verify CTM meshing with real clean-connected-glass pack if available."""
        if self.mtk is None or not hasattr(self.mtk, "VoxelStorage"):
            self.skipTest("libmtk_py VoxelStorage not available")

        pack_path = ctm_resource_pack_zip()
        if pack_path is None or not pack_path.exists():
            self.skipTest("Real CTM pack not available")

        stack = self.mtk.ResourcePackStack()
        stack.add_zip_pack(str(pack_path))
        rule_count = stack.get_ctm_rule_count()
        self.assertGreater(rule_count, 0)

        solver = stack.build_ctm_solver()
        self.assertIsNotNone(solver)

        # Place a 2x2 flat glass surface
        storage = self.mtk.VoxelStorage()
        for x in (0, 1):
            for y in (0, 1):
                storage.set_block(x, y, 0, "minecraft:glass")

        mesh_data, _ = mesh_voxel_storage(
            storage=storage,
            atlas=None,
            ctm_solver=solver,
            material_mode="STANDALONE",
            origin_centered=False,
        )

        self.assertIsNotNone(mesh_data)
        self.assertTrue(mesh_data.has_attribute("mtk_source_texture_key"))
        keys = mesh_data.get_string_attribute("mtk_source_texture_key")

        # Corner glass faces should resolve to connected sub-tiles
        ctm_keys = [k for k in keys if "optifine/ctm" in k]
        self.assertGreater(len(ctm_keys), 0, f"Expected CTM sub-tiles in keys: {set(keys)}")

    def test_scene_loading_standalone_materials(self):
        """Verify apply_voxel_mesh_to_blender assigns standalone materials and slots."""
        if not HAS_BPY:
            self.skipTest("Live bpy host required for scene material binding test")

        if self.mtk is None or not hasattr(self.mtk, "VoxelStorage"):
            self.skipTest("libmtk_py VoxelStorage not available")

        stack = self.mtk.ResourcePackStack()
        stack.add_zip_pack(str(self.synthetic_pack_zip))
        solver = stack.build_ctm_solver()

        storage = self.mtk.VoxelStorage()
        storage.set_block(0, 0, 0, "minecraft:glass")
        storage.set_block(1, 0, 0, "minecraft:glass")

        mesh_data, elapsed_ms = mesh_voxel_storage(
            storage=storage,
            atlas=None,
            ctm_solver=solver,
            material_mode="STANDALONE",
        )

        # Inject into Blender scene
        obj, stats = apply_voxel_mesh_to_blender(
            mesh_data=mesh_data,
            storage=storage,
            elapsed_ms=elapsed_ms,
            name="Test_CTM_World",
            atlas=None,
            material_mode="STANDALONE",
            reuse_existing=False,
        )

        self.assertIsNotNone(obj)
        self.assertEqual(obj.type, "MESH")
        self.assertGreater(len(obj.data.vertices), 0)
        self.assertGreater(len(obj.data.polygons), 0)

        # Verify mesh provenance attributes
        self.assertTrue(
            "mtk_source_texture_key" in obj.data.attributes or "mtk_source_texture_idx" in obj.data.attributes
        )

        # Cleanup
        bpy.data.objects.remove(obj, do_unlink=True)

    def test_ctm_tangent_orientation_across_axes(self):
        """Verify full 47-tile CTM resolves seamless connection tiles correctly across all axes."""
        if self.mtk is None or not hasattr(self.mtk, "VoxelStorage"):
            self.skipTest("libmtk_py VoxelStorage not available")

        stack = self.mtk.ResourcePackStack()
        stack.add_zip_pack(str(self.synthetic_pack_zip))
        solver = stack.build_ctm_solver()

        def get_face_key_for(mesh_data, target_x, target_y, target_z, target_dir):
            keys = mesh_data.get_string_attribute("mtk_source_texture_key")
            bxs = mesh_data.attribute_memoryview("mtk_block_x").cast("i")
            bys = mesh_data.attribute_memoryview("mtk_block_y").cast("i")
            bzs = mesh_data.attribute_memoryview("mtk_block_z").cast("i")
            dirs = mesh_data.attribute_memoryview("mtk_face_dir").cast("B")
            for i in range(mesh_data.quad_count):
                if (bxs[i] == target_x and bys[i] == target_y and
                    bzs[i] == target_z and dirs[i] == target_dir):
                    return keys[i]
            return None

        # 1. Horizontal connection along X axis (East-West)
        storage_x = self.mtk.VoxelStorage()
        storage_x.set_block(0, 0, 0, "minecraft:white_stained_glass")
        storage_x.set_block(1, 0, 0, "minecraft:white_stained_glass")
        mesh_x, _ = mesh_voxel_storage(storage=storage_x, atlas=None, ctm_solver=solver, material_mode="STANDALONE")

        # North face (dir 5): looking +Z
        # Block (0,0,0) has neighbor at (1,0,0) (East = left) -> Tile 3
        key_0_north = get_face_key_for(mesh_x, 0, 0, 0, 5)
        self.assertIsNotNone(key_0_north)
        self.assertTrue(key_0_north.endswith("white_glass/3"), f"Expected tile 3 for left connect, got {key_0_north}")

        # Block (1,0,0) has neighbor at (0,0,0) (West = right) -> Tile 1
        key_1_north = get_face_key_for(mesh_x, 1, 0, 0, 5)
        self.assertIsNotNone(key_1_north)
        self.assertTrue(key_1_north.endswith("white_glass/1"), f"Expected tile 1 for right connect, got {key_1_north}")

        # 2. Horizontal connection along Z axis (North-South)
        storage_z = self.mtk.VoxelStorage()
        storage_z.set_block(0, 0, 0, "minecraft:white_stained_glass")
        storage_z.set_block(0, 0, 1, "minecraft:white_stained_glass")
        mesh_z, _ = mesh_voxel_storage(storage=storage_z, atlas=None, ctm_solver=solver, material_mode="STANDALONE")

        # East face (dir 0): looking -X
        # Block (0,0,0) has neighbor at (0,0,1) (South = left of East face) -> Tile 3
        key_0_east = get_face_key_for(mesh_z, 0, 0, 0, 0)
        self.assertIsNotNone(key_0_east)
        self.assertTrue(key_0_east.endswith("white_glass/3"), f"Expected tile 3 for left connect, got {key_0_east}")

        # Block (0,0,1) has neighbor at (0,0,0) (North = right of East face) -> Tile 1
        key_1_east = get_face_key_for(mesh_z, 0, 0, 1, 0)
        self.assertIsNotNone(key_1_east)
        self.assertTrue(key_1_east.endswith("white_glass/1"), f"Expected tile 1 for right connect, got {key_1_east}")

        # 3. Vertical connection along Y axis (Up-Down)
        storage_y = self.mtk.VoxelStorage()
        storage_y.set_block(0, 0, 0, "minecraft:white_stained_glass")
        storage_y.set_block(0, 1, 0, "minecraft:white_stained_glass")
        mesh_y, _ = mesh_voxel_storage(storage=storage_y, atlas=None, ctm_solver=solver, material_mode="STANDALONE")

        # North face (dir 5):
        # Block (0,0,0) has neighbor at (0,1,0) (Up = top of North face) -> Tile 36
        key_0_up = get_face_key_for(mesh_y, 0, 0, 0, 5)
        self.assertIsNotNone(key_0_up)
        self.assertTrue(key_0_up.endswith("white_glass/36"), f"Expected tile 36 for up connect, got {key_0_up}")

        # Block (0,1,0) has neighbor at (0,0,0) (Down = bottom of North face) -> Tile 12
        key_1_down = get_face_key_for(mesh_y, 0, 1, 0, 5)
        self.assertIsNotNone(key_1_down)
        self.assertTrue(key_1_down.endswith("white_glass/12"), f"Expected tile 12 for down connect, got {key_1_down}")


if __name__ == "__main__":
    unittest.main()
