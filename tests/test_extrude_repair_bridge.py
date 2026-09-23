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
        for h in heights:
            self.assertTrue(0.1 <= h <= 0.5)


if __name__ == "__main__":
    unittest.main()
