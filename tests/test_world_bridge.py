"""
Unit tests for the Unified Offline Voxel World Pipeline (bridge.world, bridge.debug, dev.api).
Verifies that voxel storage can be meshed and ingested without any network/sync dependencies.
"""

import pytest
import sys
import ast
from pathlib import Path

# Add dev/lib to sys.path if not present
dev_lib = Path(__file__).parent.parent / "dev" / "lib"
if dev_lib.exists() and str(dev_lib) not in sys.path:
    sys.path.insert(0, str(dev_lib))

try:
    import libmtk_py
    HAS_LIBMTK = True
except ImportError:
    HAS_LIBMTK = False


@pytest.mark.skipif(not HAS_LIBMTK, reason="libmtk_py not available")
class TestWorldBridgePipeline:
    def test_load_debug_world_storage(self):
        from MoziToolKit.bridge.debug import load_debug_world_storage, is_debug_world_available
        assert is_debug_world_available()
        storage = load_debug_world_storage()
        assert storage is not None
        non_empty = storage.get_non_empty_sections()
        assert len(non_empty) > 100
        bounds = storage.get_bounds()
        assert bounds[3] > 0  # size_x > 0

    def test_mesh_voxel_storage_offline(self):
        from MoziToolKit.bridge.debug import load_debug_world_storage
        from MoziToolKit.bridge.world import mesh_voxel_storage

        storage = load_debug_world_storage()
        # Mesh without requiring network or sync
        mesh_data, elapsed_ms = mesh_voxel_storage(
            storage=storage,
            enable_ao=True,
            mesh_fluids=True,
            weld_vertices=True,
            origin_centered=True,
        )

        assert mesh_data is not None
        assert mesh_data.vertex_count > 0
        assert mesh_data.quad_count > 0
        assert elapsed_ms > 0

    def test_dev_api_diagnostics_and_benchmark(self):
        from MoziToolKit.dev.api import get_diagnostics, run_mesher_benchmark

        diag = get_diagnostics()
        assert diag["available"] is True
        assert diag["debug_world_available"] is True

        bench = run_mesher_benchmark(iterations=1, with_models=False)
        assert bench["iterations"] == 1
        assert bench["quad_count"] > 0
        assert bench["avg_ms"] > 0
        assert bench["quads_per_second"] > 0

    def test_world_bridge_has_no_sync_imports(self):
        """Verify that bridge.world AST imports no networking or LiveSync modules."""
        world_py = Path(__file__).parent.parent / "bridge" / "world.py"
        tree = ast.parse(world_py.read_text(encoding="utf-8"))

        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module)

        for mod in imported_modules:
            assert "sync" not in mod.lower(), f"Unexpected sync import: {mod}"
            assert "websocket" not in mod.lower(), f"Unexpected websocket import: {mod}"
            assert "socket" not in mod.lower(), f"Unexpected socket import: {mod}"
            assert "http" not in mod.lower(), f"Unexpected http import: {mod}"

    def test_voxel_world_used_materials_and_chunks(self):
        """Verifies VoxelWorld rebuild and used materials tracking."""
        from MoziToolKit.bridge.debug import load_debug_world_storage
        storage = load_debug_world_storage()

        world = libmtk_py.VoxelWorld.from_storage(storage)
        assert world is not None

        mesh = world.rebuild_all()
        assert mesh.vertex_count > 0
        used_mats = mesh.used_materials()
        used_chunks = world.used_chunk_ids()
        assert isinstance(used_mats, list)
        assert isinstance(used_chunks, list)
        # Verify materials tracking correctly matches world chunk IDs
        assert set(used_mats) == set(used_chunks)

    def test_selective_material_loading_avoids_redundancy(self):
        """
        Verifies that ensure_world_materials ONLY loads the materials for actually used chunks,
        completely skipping unused atlas chunks even when 50+ chunks exist in the atlas mapping.
        """
        import tempfile
        import json
        from unittest.mock import patch, MagicMock
        from MoziToolKit.bridge.world import ensure_world_materials

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            atlas_dir = tmp_path / "atlas"
            atlas_dir.mkdir(parents=True)

            # Generate 50 chunks in atlas_mapping.json
            chunks = []
            for cid in range(50):
                chunks.append({
                    "chunk_id": cid,
                    "category": "blocks",
                    "category_chunk_index": cid + 1,
                    "width": 1024,
                    "height": 1024,
                    "is_animated": False,
                })

            mapping_data = {
                "format_version": 1,
                "category": "blocks",
                "chunks": chunks,
                "sprites": {},
            }
            (atlas_dir / "atlas_mapping.json").write_text(json.dumps(mapping_data))

            # Only chunk 2 and chunk 5 are created on disk
            (atlas_dir / "blocks_chunk_003.png").write_bytes(b"\x89PNG\r\n\x1a\n")  # chunk 2 (1-based index 3)
            (atlas_dir / "blocks_chunk_006.png").write_bytes(b"\x89PNG\r\n\x1a\n")  # chunk 5 (1-based index 6)

            # Mock mesh object
            class MockPoly:
                def __init__(self, mat_idx):
                    self.material_index = mat_idx

            class MockMesh:
                def __init__(self):
                    self.polygons = [MockPoly(2), MockPoly(5)]
                    self.materials = []

            class MockObject:
                def __init__(self):
                    self.type = "MESH"
                    self.data = MockMesh()

            test_obj = MockObject()

            with patch.dict("os.environ", {"MOZI_CACHE_DIR": str(tmp_path)}):
                # Call ensure_world_materials with used_chunk_ids=[2, 5]
                built_chunks = []
                def mock_build(chunk_id, **kwargs):
                    built_chunks.append(chunk_id)
                    mat = MagicMock()
                    mat.name = f"MTK:Atlas:blocks:{chunk_id+1:03}"
                    return mat

                with patch("MoziToolKit.utils.materials.builder.atlas_builder.build_atlas_chunk_material", side_effect=mock_build):
                    ensure_world_materials(test_obj, used_chunk_ids=[2, 5])

                # CRITICAL VERIFICATION:
                # build_atlas_chunk_material should ONLY be called for chunk 2 and chunk 5 (2 times)!
                # It must NOT be called 50 times!
                assert sorted(built_chunks) == [2, 5], f"Expected only chunks [2, 5] built, got {built_chunks}"
                # The material slots should be allocated up to max chunk ID (5)
                assert len(test_obj.data.materials) == 6
                assert test_obj.data.materials[2] is not None
                assert test_obj.data.materials[5] is not None
                # Unused chunks (0, 1, 3, 4) must be None
                for unused_idx in [0, 1, 3, 4]:
                    assert test_obj.data.materials[unused_idx] is None

