"""
Unit tests for unified progress reporting across bridge, voxel meshing, and Blender UI status bar.
"""

import unittest
from types import SimpleNamespace

import bpy

from MoziToolKit.bridge.progress import ProgressReport, wrap_progress_callback
from MoziToolKit.bridge.world import mesh_voxel_storage
from MoziToolKit.bridge.debug import generate_debug_world_mesh
from MoziToolKit.utils.progress import BlenderProgressReporter, blender_progress_scope


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
        calls = []
        dummy_wm = SimpleNamespace(
            progress_begin=lambda a, b: calls.append(("begin", a, b)),
            progress_update=lambda v: calls.append(("update", v)),
            progress_end=lambda: calls.append(("end",)),
        )
        dummy_ws = SimpleNamespace(
            status_text_set=lambda t: calls.append(("status", t)),
        )
        dummy_ctx = SimpleNamespace(
            window_manager=dummy_wm,
            workspace=dummy_ws,
        )

        reporter = BlenderProgressReporter(context=dummy_ctx, total=100, title="TestSync")
        reporter.start()
        self.assertIn(("begin", 0, 100), calls)

        reporter.update(current=50, total=100, message="Halfway")
        self.assertIn(("update", 50), calls)
        self.assertIn(("status", "TestSync: Halfway (50/100, 50%)"), calls)

        reporter.close()
        self.assertIn(("end",), calls)
        self.assertIn(("status", None), calls)

    def test_blender_progress_scope_exception_safety(self):
        calls = []
        dummy_wm = SimpleNamespace(
            progress_begin=lambda a, b: calls.append(("begin", a, b)),
            progress_update=lambda v: calls.append(("update", v)),
            progress_end=lambda: calls.append(("end",)),
        )
        dummy_ws = SimpleNamespace(
            status_text_set=lambda t: calls.append(("status", t)),
        )
        dummy_ctx = SimpleNamespace(
            window_manager=dummy_wm,
            workspace=dummy_ws,
        )

        try:
            with blender_progress_scope(context=dummy_ctx, total=50, title="Faulty"):
                raise RuntimeError("Simulated crash")
        except RuntimeError:
            pass

        self.assertIn(("end",), calls)
        self.assertIn(("status", None), calls)

    def test_voxel_meshing_with_real_physical_progress(self):
        from MoziToolKit.bridge.engine import get_libmtk
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
