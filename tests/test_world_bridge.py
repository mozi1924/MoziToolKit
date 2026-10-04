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
