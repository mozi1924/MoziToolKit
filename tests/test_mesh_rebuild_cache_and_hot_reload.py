"""
Tests for Mesh Reconstruction Dirty Cache Validation and Hot Reload.
Verifies cache manifest fingerprint checking, timestamp tracking,
dynamic VoxelWorld/LiveSyncSession cache purging, and Blender image reloading.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

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
    sys.modules["bpy.props"] = MagicMock()
    sys.modules["bpy.types"] = MagicMock()
    sys.modules["bpy.app"] = MagicMock()
    HAS_BPY = False

from bridge.assets import (
    check_cache_dirty,
    get_cache_dir,
    get_cache_fingerprint,
    get_cache_manifest,
    get_cache_timestamp,
    reload_atlas_images,
)
from bridge.sync import (
    SyncBridgeSession,
    get_sync_bridge_session,
    is_sync_available,
    reset_sync_bridge_session,
)


class TestMeshRebuildCacheAndHotReload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if HAS_BPY:
            import operators
            try:
                operators.register()
            except Exception:
                pass

    @classmethod
    def tearDownClass(cls):
        if HAS_BPY:
            import operators
            try:
                operators.unregister()
            except Exception:
                pass

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.tmp_dir.name)
        self.old_env = os.environ.get("MOZI_CACHE_DIR")
        os.environ["MOZI_CACHE_DIR"] = str(self.cache_dir)

    def tearDown(self):
        if self.old_env is not None:
            os.environ["MOZI_CACHE_DIR"] = self.old_env
        else:
            os.environ.pop("MOZI_CACHE_DIR", None)
        self.tmp_dir.cleanup()
        reset_sync_bridge_session()

    def _create_package(self, fingerprint: str, created_at: int = 0) -> Path:
        from bridge.engine import get_libmtk
        mtk = get_libmtk()
        pkg_path = self.cache_dir / f"{fingerprint}.mtkcache"
        if mtk and hasattr(mtk, "create_test_cache_package"):
            mtk.create_test_cache_package(str(pkg_path), fingerprint, created_at)
        return pkg_path

    def test_cache_fingerprint_and_timestamp_extraction(self):
        # Empty cache
        self.assertIsNone(get_cache_manifest())
        self.assertIsNone(get_cache_fingerprint())
        self.assertEqual(get_cache_timestamp(), 0.0)

        # Write package
        self._create_package("fp_test_12345", 1728000000)

        manifest = get_cache_manifest()
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest["fingerprint"], "fp_test_12345")
        self.assertEqual(get_cache_fingerprint(), "fp_test_12345")
        self.assertEqual(get_cache_timestamp(), 1728000000.0)

    def test_check_cache_dirty_detection(self):
        self._create_package("fp_v1", 1000)

        # Initial clean match
        is_dirty, fp, ts = check_cache_dirty(cached_fingerprint="fp_v1", cached_timestamp=1000.0)
        self.assertFalse(is_dirty)
        self.assertEqual(fp, "fp_v1")
        self.assertEqual(ts, 1000.0)

        # Fingerprint mismatch
        is_dirty, fp, ts = check_cache_dirty(cached_fingerprint="fp_v0", cached_timestamp=1000.0)
        self.assertTrue(is_dirty)

        # Timestamp mismatch
        is_dirty, fp, ts = check_cache_dirty(cached_fingerprint="fp_v1", cached_timestamp=999.0)
        self.assertTrue(is_dirty)

        # Disk cache update to v2
        old_pkg = self.cache_dir / "fp_v1.mtkcache"
        if old_pkg.exists():
            old_pkg.unlink()
        self._create_package("fp_v2", 2000)

        is_dirty, fp, ts = check_cache_dirty(cached_fingerprint="fp_v1", cached_timestamp=1000.0)
        self.assertTrue(is_dirty)
        self.assertEqual(fp, "fp_v2")
        self.assertEqual(ts, 2000.0)

    def test_sync_bridge_session_dirty_cache_hot_reload(self):
        self._create_package("initial_fp", 5000)

        session = SyncBridgeSession()
        session._cached_manifest_fingerprint = "initial_fp"
        session._cached_manifest_timestamp = 5000.0

        # No changes: returns False
        self.assertFalse(session.check_and_reload_dirty_cache())

        # Disk cache updated
        old_pkg = self.cache_dir / "initial_fp.mtkcache"
        if old_pkg.exists():
            old_pkg.unlink()
        self._create_package("recompiled_fp", 6000)

        # Dirty cache detected: returns True and updates cached state
        reloaded = session.check_and_reload_dirty_cache()
        self.assertTrue(reloaded)
        self.assertEqual(session._cached_manifest_fingerprint, "recompiled_fp")
        self.assertEqual(session._cached_manifest_timestamp, 6000.0)

        # Subsequent check without modifications: returns False
        self.assertFalse(session.check_and_reload_dirty_cache())

    def test_native_voxel_world_clear_cache(self):
        if not is_sync_available():
            self.skipTest("libmtk_py is not loaded")

        from bridge.engine import get_libmtk
        mtk = get_libmtk()
        if not hasattr(mtk, "VoxelWorld"):
            self.skipTest("VoxelWorld not available in bindings")

        world = mtk.VoxelWorld.create_debug_world()
        mesh = world.rebuild_all()
        self.assertGreater(mesh.vertex_count, 0)
        self.assertGreater(world.get_world_mesh().vertex_count, 0)

        # Call clear_cache()
        world.clear_cache()
        # World mesh and section mesh cache must be purged
        self.assertEqual(world.get_world_mesh().vertex_count, 0)
        self.assertEqual(len(world.used_chunk_ids()), 0)

        # Re-mesh after cache purge
        re_mesh = world.rebuild_all()
        self.assertGreater(re_mesh.vertex_count, 0)

    def test_reload_atlas_images_helper(self):
        if not HAS_BPY:
            # Under mock, should return 0 safely without crashing
            self.assertEqual(reload_atlas_images(), 0)
            return

        atlas_dir = self.cache_dir / "atlas"
        atlas_dir.mkdir(parents=True, exist_ok=True)
        img_path = atlas_dir / "blocks_chunk_001.png"

        # Create Blender image pointing to atlas path
        img = bpy.data.images.new("blocks_chunk_001.png", width=16, height=16)
        img.filepath_raw = str(img_path)
        img.file_format = "PNG"
        img.save()

        count = reload_atlas_images()
        self.assertGreaterEqual(count, 1)

        bpy.data.images.remove(img)

    def test_sync_rebuild_operator_with_dirty_cache(self):
        if not HAS_BPY:
            self.skipTest("Requires Blender environment")

        from bridge.engine import get_libmtk
        mtk = get_libmtk()
        if not mtk or not hasattr(mtk, "LiveSyncSession"):
            self.skipTest("LiveSyncSession not available")

        session = get_sync_bridge_session()
        world = mtk.VoxelWorld.create_debug_world()
        real_mesh = world.rebuild_all()
        session._session = MagicMock()
        session._session.is_active = True
        session._is_active = True
        session._cached_manifest_fingerprint = "old_fp"
        session._cached_manifest_timestamp = 100.0

        session.get_world_mesh = MagicMock(return_value=real_mesh)
        session.get_storage = MagicMock(return_value=world.get_storage())

        # Write new package to simulate rebaking
        self._create_package("new_recompiled_fp", 200)

        # Run operator synchronously
        res = bpy.ops.mozi.sync_rebuild_world("EXEC_DEFAULT", run_async=False)
        self.assertEqual(res, {'FINISHED'})

        # Verify dirty cache was detected and reloaded
        self.assertEqual(session._cached_manifest_fingerprint, "new_recompiled_fp")
        self.assertEqual(session._cached_manifest_timestamp, 200.0)


if __name__ == "__main__":
    unittest.main()
