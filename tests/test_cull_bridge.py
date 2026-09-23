import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from bridge.cull import cull_mesh_faces
from bridge.mesh import MeshData




class TestCullBridge(unittest.TestCase):

    def test_cull_coplanar_opposite_faces(self):
        mesh = MeshData()
        # Face 1 (+Z) and Face 2 (-Z, touching same plane)
        positions = [
            (-0.5, -0.5, 0.0),
            (0.5, -0.5, 0.0),
            (0.5, 0.5, 0.0),
            (-0.5, 0.5, 0.0),
            (-0.5, -0.5, 0.0),
            (-0.5, 0.5, 0.0),
            (0.5, 0.5, 0.0),
            (0.5, -0.5, 0.0),
        ]
        normals = [(0.0, 0.0, 1.0)] * 4 + [(0.0, 0.0, -1.0)] * 4
        uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)] * 2
        indices = [0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7]
        mesh.set_buffers(positions, normals, uvs, indices, [0, 0], [-1, -1])


        culled_mesh, stats = cull_mesh_faces(mesh)
        self.assertEqual(stats["initial_faces"], 2)
        self.assertEqual(stats["culled_faces"], 2, "Interior touching faces must be culled")
        self.assertEqual(stats["remaining_faces"], 0)
        self.assertEqual(culled_mesh.face_count, 0)


if __name__ == "__main__":
    unittest.main()
