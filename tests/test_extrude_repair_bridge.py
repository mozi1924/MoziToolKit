import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from bridge.extrude import repair_extruded_side_uv, generate_random_extrude_heights




class TestExtrudeRepairBridge(unittest.TestCase):

    def test_repair_extruded_side_uv_inward(self):
        uv_base_a = (0.0, 0.0)
        uv_base_b = (1.0 / 16.0, 0.0)
        top_normal = (0.0, 0.0, 1.0)
        extrude_vec = (0.0, 0.0, 0.1)

        uvs = repair_extruded_side_uv(
            uv_base_a=uv_base_a,
            uv_base_b=uv_base_b,
            top_normal=top_normal,
            extrude_vec=extrude_vec,
            mode="SMART",
            step_u=1.0 / 16.0,
            step_v=1.0 / 16.0,
            top_uv_bounds=(0.0, 0.0, 1.0, 1.0),
        )

        self.assertEqual(len(uvs), 4)
        for u, v in uvs:
            self.assertTrue(0.0 <= u <= 1.0)
            self.assertTrue(0.0 <= v <= 1.0)

    def test_generate_random_extrude_heights(self):
        centers = [(0.0, 0.0, 0.0), (1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]
        heights = generate_random_extrude_heights(
            centers,
            noise_type="PERLIN",
            min_height=0.1,
            max_height=0.5,
            noise_scale=0.5,
            seed=42,
        )
        self.assertEqual(len(heights), 3)
    def test_uv_editing_and_extrude_progress_guards(self):
        import importlib.util
        op_path = PROJECT_DIR / "operators" / "op_extrude.py"
        spec = importlib.util.spec_from_file_location("op_extrude", str(op_path))
        op_extrude = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(op_extrude)

        _is_uv_editing_active = op_extrude._is_uv_editing_active
        _is_extrude_operator_identifier = op_extrude._is_extrude_operator_identifier
        _is_extrude_in_progress = op_extrude._is_extrude_in_progress
        _has_recent_extrude_operator = op_extrude._has_recent_extrude_operator
        _deferred_extrude_repair_tick = op_extrude._deferred_extrude_repair_tick
        _pending_repairs = op_extrude._pending_repairs
        _smart_extrude_sessions = op_extrude._smart_extrude_sessions

        class DummyArea:
            def __init__(self, type_str):
                self.type = type_str

        class DummySpace:
            def __init__(self, type_str):
                self.type = type_str

        class DummyOp:
            def __init__(self, idname):
                self.bl_idname = idname

        class DummyWindow:
            def __init__(self, modal_ops=None):
                self.modal_operators = modal_ops or []

        class DummyContext:
            def __init__(self, area_type=None, space_type=None, modal_ops=None, recent_ops=None):
                self.area = DummyArea(area_type) if area_type else None
                self.space_data = DummySpace(space_type) if space_type else None
                self.window = DummyWindow(modal_ops)
                self.window_manager = type("DummyWM", (), {"operators": recent_ops or []})()

        # 1. IMAGE_EDITOR detection
        ctx_uv = DummyContext(area_type="IMAGE_EDITOR")
        self.assertTrue(_is_uv_editing_active(ctx_uv))
        self.assertFalse(_is_extrude_in_progress(ctx_uv))

        # 2. View 3D non-extrude modal transform
        ctx_transform_only = DummyContext(
            area_type="VIEW_3D",
            modal_ops=[DummyOp("TRANSFORM_OT_translate")],
            recent_ops=[DummyOp("VIEW3D_OT_select"), DummyOp("TRANSFORM_OT_translate")],
        )
        self.assertFalse(_is_uv_editing_active(ctx_transform_only))
        self.assertFalse(_is_extrude_in_progress(ctx_transform_only))
        self.assertFalse(_has_recent_extrude_operator(ctx_transform_only))

        # 3. View 3D extrude modal transform
        ctx_extrude = DummyContext(
            area_type="VIEW_3D",
            modal_ops=[DummyOp("TRANSFORM_OT_translate")],
            recent_ops=[DummyOp("MESH_OT_extrude_region_move"), DummyOp("TRANSFORM_OT_translate")],
        )
        self.assertTrue(_is_extrude_in_progress(ctx_extrude))
        self.assertTrue(_has_recent_extrude_operator(ctx_extrude))

        # 4. Operator identifier recognition
        self.assertTrue(_is_extrude_operator_identifier("MESH_OT_extrude_region"))
        self.assertTrue(_is_extrude_operator_identifier("MESH_OT_extrude_faces_move"))
        self.assertTrue(_is_extrude_operator_identifier("MESH_OT_extrude_manifold"))
        self.assertTrue(_is_extrude_operator_identifier("MOZI_OT_random_extrude"))
        self.assertFalse(_is_extrude_operator_identifier("TRANSFORM_OT_translate"))
        self.assertFalse(_is_extrude_operator_identifier("UV_OT_unwrap"))

        # 5. Deferred tick idle returns None
        _pending_repairs.clear()
        _smart_extrude_sessions.clear()
        res = _deferred_extrude_repair_tick()
        self.assertIsNone(res)


if __name__ == "__main__":
    unittest.main()

