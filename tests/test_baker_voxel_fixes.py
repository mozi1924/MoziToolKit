import unittest
import libmtk_py
from pathlib import Path


class TestBakerVoxelFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = libmtk_py.ResourcePackStack()
        cls.stack.add_directory_pack("/home/mozi/mc")
        cls.baker = libmtk_py.ModelBaker()

    def test_spawner_faces(self):
        mesh, textures = self.baker.bake_blockstate(self.stack, "minecraft:spawner")
        self.assertEqual(mesh.face_count, 12, "Spawner must preserve all 12 faces (6 outer + 6 inner cage)")
        self.assertIn("minecraft:block/spawner", textures)

    def test_vault_faces_and_normal(self):
        mesh, textures = self.baker.bake_blockstate(
            self.stack, "minecraft:vault[facing=north,ominous=false,vault_state=inactive]"
        )
        self.assertGreaterEqual(mesh.face_count, 7, "Vault must keep outer and inner cage faces")
        normals = mesh.get_flat_normals()
        has_up = any(normals[i * 3 + 1] > 0.99 for i in range(len(normals) // 3))
        self.assertTrue(has_up, "Vault must keep top face with normal (0, 1, 0)")
        self.assertTrue(any("vault_top" in t for t in textures), "vault_top texture must be present")

    def test_heavy_core_texture(self):
        mesh, textures = self.baker.bake_blockstate(self.stack, "minecraft:heavy_core")
        self.assertEqual(mesh.face_count, 6)
        self.assertEqual(textures, ["minecraft:block/heavy_core"], "Heavy core must resolve to block/heavy_core, not block/all")

    def test_end_portal_and_gateway(self):
        ep_mesh, ep_tex = self.baker.bake_blockstate(self.stack, "minecraft:end_portal")
        self.assertEqual(ep_mesh.face_count, 1, "End portal should have 1 upward face")
        self.assertEqual(ep_tex, ["minecraft:entity/end_portal/end_portal"])

        eg_mesh, eg_tex = self.baker.bake_blockstate(self.stack, "minecraft:end_gateway")
        self.assertEqual(eg_mesh.face_count, 6, "End gateway should have 6 cube faces")
        self.assertEqual(eg_tex, ["minecraft:entity/end_portal/end_portal"])

    def test_conduit_and_banners(self):
        cd_mesh, cd_tex = self.baker.bake_blockstate(self.stack, "minecraft:conduit")
        self.assertEqual(cd_mesh.face_count, 6)
        self.assertEqual(cd_tex, ["minecraft:entity/conduit/base"])

        sb_mesh, sb_tex = self.baker.bake_blockstate(self.stack, "minecraft:black_banner[rotation=4]")
        self.assertGreaterEqual(sb_mesh.face_count, 12)
        self.assertIn("minecraft:entity/banner/banner_base", sb_tex)

        wb_mesh, wb_tex = self.baker.bake_blockstate(self.stack, "minecraft:red_wall_banner[facing=north]")
        self.assertGreaterEqual(wb_mesh.face_count, 10)
        self.assertIn("minecraft:entity/banner/banner_base", wb_tex)


if __name__ == "__main__":
    unittest.main()
