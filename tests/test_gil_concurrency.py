import concurrent.futures
import unittest

try:
    import libmtk_py
    HAS_LIBMTK = True
except ImportError:
    HAS_LIBMTK = False


class TestGilConcurrency(unittest.TestCase):

    def setUp(self):
        if not HAS_LIBMTK:
            self.skipTest("libmtk_py not available")

    def test_concurrent_cull_mesh_faces(self):
        """Verify that multiple threads can call cull_mesh_faces concurrently with zero contention."""
        mesh = libmtk_py.MeshData()
        for i in range(1000):
            mesh.append_unit_cube_face(i % 6, 0, -1)

        def worker(worker_id):
            culled, stats = libmtk_py.cull_mesh_faces(mesh)
            self.assertGreater(culled.vertex_count, 0)
            return worker_id, culled.face_count

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(worker, i) for i in range(16)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
            self.assertEqual(len(results), 16)

    def test_concurrent_adaptive_pixel_split_mesh(self):
        """Verify that multiple threads can call adaptive_pixel_split_mesh concurrently."""
        quad_mesh = libmtk_py.MeshData()
        for i in range(10):
            quad_mesh.append_unit_cube_face(i % 6, 0, -1)

        def worker(worker_id):
            subdivided = libmtk_py.adaptive_pixel_split_mesh(
                quad_mesh,
                default_resolution=(16, 16),
                pixels_per_face=1.0,
                max_subdivisions=64,
                weld_dist=1e-4,
            )
            self.assertGreater(subdivided.vertex_count, 0)
            return worker_id, subdivided.vertex_count

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(worker, i) for i in range(16)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
            self.assertEqual(len(results), 16)

    def test_concurrent_extrude_repair(self):
        """Verify that multiple threads can call process_random_extrude_mesh concurrently."""
        def worker(idx):
            positions = [
                [-1.0, -1.0, 0.0],
                [ 1.0, -1.0, 0.0],
                [ 1.0,  1.0, 0.0],
                [-1.0,  1.0, 0.0],
            ]
            face_vertices = [[0, 1, 2, 3]]
            face_uvs = [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]]
            face_materials = [0]
            selected_faces = [0]
            pixel_steps = [[1.0 / 16.0, 1.0 / 16.0]]

            out = libmtk_py.process_random_extrude_mesh(
                positions,
                face_vertices,
                face_uvs,
                face_materials,
                selected_faces,
                pixel_steps,
                min_height=0.1,
                max_height=0.2,
                seed=idx,
                noise_type="RANDOM",
                noise_scale=1.0,
                repair_uv=True,
                uv_mode="SMART",
                add_crease=False,
                crease_val=1.0,
            )
            return idx, len(out[0])

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(worker, i) for i in range(16)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
            self.assertEqual(len(results), 16)

    def test_concurrent_voxel_mesher(self):
        """Verify SectionMesher.mesh_world in concurrent threads."""
        def worker(idx):
            storage = libmtk_py.VoxelStorage()
            storage.set_bounds(0, 0, 0, 16, 16, 16)
            storage.set_block(0, 0, 0, "minecraft:stone")
            storage.set_block(1, 0, 0, "minecraft:dirt")

            cfg = libmtk_py.MesherConfig()
            mesh = libmtk_py.SectionMesher.mesh_world(storage, config=cfg)
            return idx, mesh.vertex_count

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(worker, i) for i in range(16)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
            self.assertEqual(len(results), 16)
            for _, vc in results:
                self.assertGreater(vc, 0)

    def test_loop_memoryviews_zero_copy(self):
        """Verify loop_uvs_memoryview, loop_starts_memoryview, and loop_totals_memoryview."""
        mesh = libmtk_py.MeshData()
        mesh.append_unit_cube_face(1, 0, -1)  # 1 quad: 4 vertices, 4 loop UVs

        self.assertEqual(mesh.vertex_count, 4)
        self.assertEqual(mesh.face_count, 1)

        loop_uvs = mesh.loop_uvs_memoryview()
        self.assertIsNotNone(loop_uvs)
        self.assertEqual(len(loop_uvs), 32)

        starts = mesh.loop_starts_memoryview()
        self.assertIsNotNone(starts)
        self.assertEqual(len(starts), 4)

        totals = mesh.loop_totals_memoryview()
        self.assertIsNotNone(totals)
        self.assertEqual(len(totals), 4)

    def test_concurrent_mesh_data_merge(self):
        """Verify concurrent mesh merging and thread pool meshing."""
        def worker(idx):
            storage = libmtk_py.VoxelStorage()
            storage.set_bounds(0, 0, 0, 16, 16, 16)
            storage.set_block(idx % 16, 0, 0, "minecraft:stone")

            cfg = libmtk_py.MesherConfig(num_threads=2)
            mesh = libmtk_py.SectionMesher.mesh_world(storage, config=cfg)
            return mesh.vertex_count

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(worker, i) for i in range(8)]
            counts = [f.result() for f in concurrent.futures.as_completed(futures)]
            self.assertEqual(len(counts), 8)
            for c in counts:
                self.assertGreater(c, 0)


if __name__ == "__main__":
    unittest.main()
