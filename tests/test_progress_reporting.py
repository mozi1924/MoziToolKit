"""
Unit tests for unified progress reporting across bridge, voxel meshing, and Blender UI status bar.
"""

import unittest
from unittest.mock import MagicMock

from bridge.progress import ProgressReport, wrap_progress_callback
from bridge.world import mesh_voxel_storage
from bridge.debug import generate_debug_world_mesh
from utils.progress import BlenderProgressReporter, blender_progress_scope


class TestProgressReporting(unittest.TestCase):
    def test_progress_report_dataclass(self):
        report = ProgressReport(stage="meshing", current=5, total=10, message="Testing", percent=50.0)
        self.assertEqual(report.stage, "meshing")
        self.assertEqual(report.current, 5)
        self.assertEqual(report.total, 10)
        self.assertEqual(report.percent, 50.0)

        # From dict factory
        from_d = ProgressReport.from_dict({"stage": "test", "current": 2, "total": 4, "message": "msg"})
        self.assertEqual(from_d.percent, 50.0)
        self.assertEqual(from_d.message, "msg")

    def test_wrap_progress_callback(self):
        received = []
        wrapped = wrap_progress_callback(lambda r: received.append(r))
        self.assertIsNotNone(wrapped)

        wrapped({"stage": "stage1", "current": 1, "total": 2, "message": "msg1"})
        self.assertEqual(len(received), 1)
        self.assertIsInstance(received[0], ProgressReport)
        self.assertEqual(received[0].stage, "stage1")

    def test_blender_progress_reporter_lifecycle(self):
        mock_wm = MagicMock()
        mock_ws = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.window_manager = mock_wm
        mock_ctx.workspace = mock_ws

        reporter = BlenderProgressReporter(context=mock_ctx, total=100, title="TestSync")
        reporter.start()
        mock_wm.progress_begin.assert_called_once_with(0, 100)

        reporter.update(current=50, total=100, message="Halfway")
        mock_wm.progress_update.assert_called_with(50)
        mock_ws.status_text_set.assert_called_with("TestSync: Halfway (50/100, 50%)")

        reporter.close()
        mock_wm.progress_end.assert_called_once()
        mock_ws.status_text_set.assert_called_with(None)

    def test_blender_progress_scope_exception_safety(self):
        mock_wm = MagicMock()
        mock_ws = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.window_manager = mock_wm
        mock_ctx.workspace = mock_ws

        try:
            with blender_progress_scope(context=mock_ctx, total=50, title="Faulty"):
                raise RuntimeError("Simulated crash")
        except RuntimeError:
            pass

        # Verification: Progress end and status clear MUST have been called despite exception
        mock_wm.progress_end.assert_called_once()
        mock_ws.status_text_set.assert_called_with(None)

    def test_voxel_meshing_with_real_physical_progress(self):
        from bridge.engine import get_libmtk
        mtk = get_libmtk()
        if mtk is None:
            self.skipTest("libmtk not available")

        # Create a small voxel storage with two sections
        storage = mtk.VoxelStorage()
        storage.set_bounds(0, 0, 0, 32, 16, 16)
        storage.set_block(0, 0, 0, "minecraft:stone")
        storage.set_block(16, 0, 0, "minecraft:dirt")

        reports = []
        def on_prog(r):
            reports.append(r)

        mesh_data, elapsed = mesh_voxel_storage(
            storage=storage,
            progress_callback=on_prog,
        )

        self.assertIsNotNone(mesh_data)
        self.assertGreater(elapsed, 0.0)
        self.assertGreaterEqual(len(reports), 2, "Expected at least 2 progress milestones")

        # Verify physical progress consistency
        for r in reports:
            self.assertGreaterEqual(r.current, 0)
            self.assertGreaterEqual(r.total, r.current)
            self.assertIn(r.stage, ("meshing_sections", "assembling_world_mesh"))


if __name__ == "__main__":
    unittest.main()
