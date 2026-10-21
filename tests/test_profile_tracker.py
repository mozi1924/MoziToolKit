"""
Test suite for the host-side execution profile tracker.
Validates profile recording, stage extraction, total-duration handling, and lifecycle.
"""

import unittest
from MoziToolKit.utils.diagnostics import (
    record_operation_profile,
    append_stage_to_last_profile,
    get_last_profile,
    clear_last_profile,
    profile_timing,
    format_timing,
    format_timing_parts,
)


class MockStage:
    def __init__(self, name, duration_ms, items_count=None):
        self.name = name
        self.duration_ms = duration_ms
        self.items_count = items_count


class MockExecutionProfile:
    def __init__(self, total_duration_ms, stages):
        self.total_duration_ms = total_duration_ms
        self.stages = stages


class TestProfileTracker(unittest.TestCase):
    def setUp(self):
        clear_last_profile()

    def tearDown(self):
        clear_last_profile()

    def test_record_and_get_profile(self):
        stages = [
            MockStage("padded_extraction", 1.5, 64),
            MockStage("parallel_meshing", 3.0, 64),
            MockStage("seam_weld", 0.5, None),
        ]
        profile_obj = MockExecutionProfile(5.0, stages)

        record_operation_profile("Test Rebuild", profile_obj)
        last = get_last_profile()

        self.assertIsNotNone(last)
        self.assertEqual(last["operation"], "Test Rebuild")
        self.assertEqual(last["core_ms"], 5.0)
        self.assertEqual(last["host_ms"], 0.0)
        self.assertEqual(last["total_ms"], 5.0)
        self.assertEqual(last["stage_count"], 3)
        self.assertEqual(len(last["stages"]), 3)

        self.assertEqual(last["stages"][0]["name"], "padded_extraction")
        self.assertEqual(last["stages"][0]["duration_ms"], 1.5)
        self.assertEqual(last["stages"][0]["items_count"], 64)
        self.assertAlmostEqual(last["stages"][0]["percent"], 30.0, places=1)

        self.assertEqual(last["stages"][1]["name"], "parallel_meshing")
        self.assertAlmostEqual(last["stages"][1]["percent"], 60.0, places=1)

    def test_clear_profile(self):
        stages = [MockStage("stage1", 1.0)]
        record_operation_profile("Op", MockExecutionProfile(1.0, stages))
        self.assertIsNotNone(get_last_profile())

        clear_last_profile()
        self.assertIsNone(get_last_profile())

    def test_record_from_dict(self):
        profile_dict = {
            "total_duration_ms": 10.0,
            "stages": [
                {"name": "dict_stage", "duration_ms": 2.5, "items_count": 10},
            ],
        }
        record_operation_profile("DictOp", profile_dict)
        last = get_last_profile()
        self.assertIsNotNone(last)
        self.assertEqual(last["operation"], "DictOp")
        self.assertEqual(last["stages"][0]["name"], "dict_stage")
        # The Rust-reported total (10 ms) is authoritative: 2.5 ms of instrumented
        # stages plus 7.5 ms of uninstrumented work must not be reported as 100%.
        self.assertEqual(last["total_ms"], 10.0)
        self.assertEqual(last["stages"][0]["percent"], 25.0)
        self.assertLessEqual(sum(s["percent"] for s in last["stages"]), 100.0)

    def test_append_stage_to_profile(self):
        stages = [MockStage("rust_meshing", 4.0, 10)]
        record_operation_profile("World Meshing", MockExecutionProfile(4.0, stages))

        append_stage_to_last_profile("blender_mesh_injection", 6.0, 100)
        last = get_last_profile()

        self.assertIsNotNone(last)
        self.assertEqual(last["core_ms"], 4.0)
        self.assertEqual(last["host_ms"], 6.0)
        self.assertEqual(last["total_ms"], 10.0)
        self.assertEqual(last["stage_count"], 2)
        self.assertEqual(last["stages"][0]["source"], "core")
        self.assertEqual(last["stages"][1]["source"], "host")
        self.assertEqual(last["stages"][0]["name"], "rust_meshing")
        self.assertEqual(last["stages"][0]["percent"], 40.0)
        self.assertEqual(last["stages"][1]["name"], "blender_mesh_injection")
        self.assertEqual(last["stages"][1]["percent"], 60.0)
        self.assertEqual(last["stages"][1]["items_count"], 100)

    def test_profile_timing_and_formatting(self):
        stages = [MockStage("rust_meshing", 4.0, 10)]
        record_operation_profile("World Meshing", MockExecutionProfile(4.0, stages))
        append_stage_to_last_profile("blender_mesh_injection", 6.0, 100)

        self.assertEqual(profile_timing(), (4.0, 6.0, 10.0))
        self.assertEqual(
            format_timing(operation="World Meshing"),
            "10.0ms (Rust 4.0 + Blender 6.0)",
        )
        # A stale profile from another operation must not leak into a report.
        self.assertEqual(format_timing(12.5, operation="Other Op"), "12.5ms")
        # Host-only operations (e.g. material building) format as a single total.
        record_operation_profile(
            "Replace Materials", None, host_stages=[{"name": "pipeline", "duration_ms": 7.25}]
        )
        self.assertEqual(format_timing(operation="Replace Materials"), "7.2ms")

        # Reporting helper for callers that already have the split.
        self.assertEqual(
            format_timing_parts(123.4, 45.0),
            "168.4ms (Rust 123.4 + Blender 45.0)",
        )
        self.assertEqual(format_timing_parts(123.4, 0.0), "123.4ms")
        self.assertEqual(format_timing_parts(0.0, 45.0), "45.0ms")

    def test_record_with_host_stages(self):
        stages = [MockStage("rust_step", 5.0)]
        host_stages = [{"name": "host_step", "duration_ms": 5.0, "items_count": 1}]
        record_operation_profile("HybridOp", MockExecutionProfile(5.0, stages), host_stages=host_stages)
        last = get_last_profile()

        self.assertIsNotNone(last)
        self.assertEqual(last["core_ms"], 5.0)
        self.assertEqual(last["host_ms"], 5.0)
        self.assertEqual(last["total_ms"], 10.0)
        self.assertEqual(last["stage_count"], 2)
        self.assertEqual(last["stages"][0]["percent"], 50.0)
        self.assertEqual(last["stages"][1]["percent"], 50.0)


if __name__ == "__main__":
    unittest.main()
