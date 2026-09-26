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

    def test_i18n_cull_entries(self):
        from i18n.dictionary import translations_dict
        hans = translations_dict.get("zh_HANS", {})
        self.assertIn(("*", "Cull Occluded Faces"), hans)
        self.assertEqual(hans[("*", "Cull Occluded Faces")], "剔除遮挡面")
        self.assertIn(("Operator", "Cull Occluded Faces"), hans)
        self.assertIn(("*", "Distance Tolerance"), hans)
        self.assertIn(("*", "Cull Interior Contacting Faces"), hans)
        self.assertIn(("*", "Cull Duplicate Overlapping Faces"), hans)

    def test_inject_mesh_data_defensive_swap(self):
        from bridge.mesh import inject_mesh_data
        mesh_data = MeshData()
        mesh_data.set_buffers(
            [(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0)],
            [(0.0, 0.0, 1.0)] * 4,
            [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
            [0, 1, 2, 0, 2, 3],
            [0],
            [-1],
        )

        class DummyCollection(list):
            def __init__(self, items=None):
                super().__init__(items or [])
                self.active = None
            def foreach_set(self, attr, seq):
                pass
            def foreach_get(self, attr, seq):
                pass
            def get(self, name):
                return None
            def new(self, name="UVMap"):
                return None

        class DummyMeshObj:
            def __init__(self):
                self.type = "MESH"
                self.data = self
                self.vertices = DummyCollection([None] * 4)
                self.polygons = DummyCollection([None] * 1)
                self.loops = DummyCollection([None] * 4)
                self.uv_layers = DummyCollection()
                self.attributes = []

            def clear_geometry(self):
                pass

            def from_pydata(self, verts, edges, quads):
                self.verts = verts
                self.quads = quads

            def update(self, calc_edges=True):
                pass

        obj = DummyMeshObj()
        # Verify call with swapped arguments (obj, mesh_data) does not throw AttributeError
        inject_mesh_data(obj, mesh_data, update_topology=True)
        self.assertEqual(len(obj.verts), 4)
        self.assertEqual(len(obj.quads), 1)


if __name__ == "__main__":
    unittest.main()
