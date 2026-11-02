"""
Unit and integration tests for 0ms Live Sync reconnection and sparse point cloud verification.
"""

from __future__ import annotations

import subprocess
import sys
import time
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
libmtk_release_path = PROJECT_DIR.parent / "libmozitoolkit" / "target" / "release"

for p in [str(libmtk_release_path), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from MoziToolKit.bridge.engine import get_libmtk
from MoziToolKit.bridge.sync import get_sync_bridge_session, is_sync_available, reset_sync_bridge_session


class TestLiveSync0msReconnect(unittest.TestCase):
    def setUp(self):
        reset_sync_bridge_session()

    def tearDown(self):
        reset_sync_bridge_session()

    def test_sparse_state_hash_equivalence_between_storage_and_point_cloud(self):
        """Verifies that PyVoxelStorage and PyVoxelPointCloud compute identical sparse state hashes."""
        mtk = get_libmtk()
        if mtk is None or not hasattr(mtk, "VoxelStorage"):
            self.skipTest("libmtk core not available")

        storage = mtk.VoxelStorage()
        # Set some non-air blocks
        storage.set_block(0, 0, 0, "minecraft:bedrock")
        storage.set_block(1, 0, 1, "minecraft:stone")
        storage.set_block(15, 63, 15, "minecraft:oak_planks")

        min_pos = (0, 0, 0)
        size = (16, 64, 16)
        dim = "minecraft:overworld"

        storage_hash = storage.compute_sparse_state_hash(min_pos, size, dim)
        self.assertNotEqual(storage_hash, 0)

        # Convert to point cloud
        cfg = mtk.MesherConfig(z_up_coordinates=True, origin_centered=True) if hasattr(mtk, "MesherConfig") else None
        cloud = storage.to_point_cloud(cfg)
        self.assertIsNotNone(cloud)

        cloud_hash = cloud.compute_sparse_state_hash(min_pos, size, dim)
        self.assertEqual(cloud_hash, storage_hash, "Point cloud hash must equal storage hash")

        # Test restoring session storage from point cloud
        session = get_sync_bridge_session()
        self.assertTrue(session.start(url="ws://127.0.0.1:9999", auto_reconnect=False))
        # Stop immediate networking before connecting
        session.stop(keep_session=True)

        self.assertTrue(session.load_from_point_cloud(cloud))
        restored_storage = session.get_storage()
        self.assertIsNotNone(restored_storage)

        restored_hash = restored_storage.compute_sparse_state_hash(min_pos, size, dim)
        self.assertEqual(restored_hash, storage_hash, "Restored storage must retain identical sparse state hash")

    def test_0ms_reconnect_handshake_with_mock_server(self):
        """Tests end-to-end 0ms instant reconnect receiving VERIFIED_SKIP_REBUILD and zero rebuild frames."""
        if not is_sync_available():
            self.skipTest("Live Sync backend not available")

        port = 8792
        min_pos = (0, 64, 0)
        size = (16, 16, 16)
        server_script = PROJECT_DIR / "tools" / "mock_sync_server.py"
        server_proc = subprocess.Popen(
            [
                sys.executable,
                str(server_script),
                "--port",
                str(port),
                "--preset",
                "flat",
                "--origin",
                str(min_pos[0]),
                str(min_pos[1]),
                str(min_pos[2]),
                "--size",
                str(size[0]),
                str(size[1]),
                str(size[2]),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        time.sleep(1.0)

        try:
            session = get_sync_bridge_session()

            # 1. First initial connection: full baseline stream
            connected = session.start(url=f"ws://127.0.0.1:{port}", auto_reconnect=False)
            self.assertTrue(connected)

            stream_finished = False
            for _ in range(80):
                time.sleep(0.05)
                events = session.poll_events()
                for ev in events:
                    if ev.get("type") == "STREAM_FINISHED":
                        stream_finished = True
                        break
                if stream_finished:
                    break

            self.assertTrue(stream_finished, "Initial connection must complete STREAM_FINISHED")

            server_uuid = session.server_uuid
            epoch = session.current_epoch
            seq = session.current_sequence
            state_hash = session.state_hash

            self.assertTrue(server_uuid)
            self.assertNotEqual(state_hash, 0)

            # Extract point cloud from restored storage
            storage = session.get_storage()
            self.assertIsNotNone(storage)
            mtk = get_libmtk()
            cfg = mtk.MesherConfig(z_up_coordinates=True, origin_centered=True) if hasattr(mtk, "MesherConfig") else None
            cloud = storage.to_point_cloud(cfg)
            self.assertIsNotNone(cloud)

            # Assert that extracted point cloud computes the EXACT sparse state hash matching the server!
            computed_cloud_hash = cloud.compute_sparse_state_hash(min_pos, size, "minecraft:overworld")
            self.assertEqual(
                computed_cloud_hash,
                state_hash,
                f"Extracted point cloud sparse hash (0x{computed_cloud_hash:016x}) must match server state_hash (0x{state_hash:016x})",
            )

            # Stop initial session
            session.stop(keep_session=False)
            self.assertFalse(session.is_active)

            time.sleep(0.2)

            # 2. 0ms Reconnect using cached handshake metadata and point cloud
            reconnect_success = session.start_with_cache(
                url=f"ws://127.0.0.1:{port}",
                auto_reconnect=False,
                server_uuid=server_uuid,
                epoch=epoch,
                sequence=seq,
                min_pos=min_pos,
                size=size,
                state_hash=state_hash,
                dimension="minecraft:overworld",
                point_cloud=cloud,
            )
            self.assertTrue(reconnect_success, "start_with_cache must succeed")

            handshake_verified = False
            verified_event_received = False
            unexpected_mesh_count = 0

            for _ in range(50):
                time.sleep(0.05)
                events = session.poll_events()
                for ev in events:
                    ev_type = ev.get("type")
                    if ev_type == "HANDSHAKE":
                        decision = ev.get("decision")
                        decision_code = ev.get("decision_code")
                        if decision == "VERIFIED_SKIP_REBUILD" or decision_code == 0:
                            handshake_verified = True
                    elif ev_type == "VERIFIED":
                        if ev.get("is_verified") is True:
                            verified_event_received = True
                    elif ev_type == "WORLD_MESH_READY":
                        unexpected_mesh_count += 1

                if handshake_verified and verified_event_received:
                    break

            self.assertTrue(handshake_verified, "Must receive VERIFIED_SKIP_REBUILD handshake")
            self.assertTrue(verified_event_received, "Must receive VERIFIED event")
            self.assertEqual(unexpected_mesh_count, 0, "0ms reconnect must skip world mesh rebuild")
            self.assertTrue(session.is_connected, "Session should be connected in LIVE state")

            session.stop()

        finally:
            reset_sync_bridge_session()
            server_proc.terminate()
            if server_proc.stdout:
                server_proc.stdout.close()
            if server_proc.stderr:
                server_proc.stderr.close()
            server_proc.wait()


if __name__ == "__main__":
    unittest.main()
