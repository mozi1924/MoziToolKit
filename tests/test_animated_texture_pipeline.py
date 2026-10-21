import unittest
import sys
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import bpy
    HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "meshes") and not isinstance(bpy.data, MagicMock)
except ImportError:
    HAS_BPY = False


class TestAnimatedTexturePipeline(unittest.TestCase):
    def test_preferences_and_save_operator_properties(self):
        try:
            from MoziToolKit.ui.preferences import MOZI_AddonPreferences
            from MoziToolKit.operators.save.op_import_save import MTK_OT_import_minecraft_save
        except ImportError:
            from MoziToolKit.ui.preferences import MOZI_AddonPreferences
            from MoziToolKit.operators.save.op_import_save import MTK_OT_import_minecraft_save

        # Verify preference property definition (either through RNA descriptor or annotation)
        has_pref = (
            "enable_animated_textures" in getattr(MOZI_AddonPreferences, "__annotations__", {})
            or hasattr(MOZI_AddonPreferences, "enable_animated_textures")
        )
        self.assertTrue(has_pref, "MOZI_AddonPreferences must declare enable_animated_textures")

        # Verify operator property definition
        has_op = (
            "enable_animated_textures" in getattr(MTK_OT_import_minecraft_save, "__annotations__", {})
            or hasattr(MTK_OT_import_minecraft_save, "enable_animated_textures")
        )
        self.assertTrue(has_op, "MTK_OT_import_minecraft_save must declare enable_animated_textures")

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_atlas_builder_animated_material_node_structure(self):
        try:
            from MoziToolKit.utils.materials.builder.atlas_builder import build_atlas_chunk_material
        except ImportError:
            from MoziToolKit.utils.materials.builder.atlas_builder import build_atlas_chunk_material

        # Create temporary dummy image for test (platform-independent temp dir)
        tmpdir = tempfile.mkdtemp(prefix="mtk-anim-")
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        test_img_path = Path(tmpdir) / "test_anim_strip.png"
        if not test_img_path.exists():
            test_img_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x01\x00\x08\x06\x00\x00\x00")

        # 1. Build an animated atlas material
        mat_anim = build_atlas_chunk_material(
            chunk_id=1,
            albedo_path=test_img_path,
            category="blocks",
            category_chunk_index=1,
            is_animated=True,
            atlas_width=2048.0,
            atlas_height=2048.0,
            tile_width=16.0,
            tile_height=16.0,
            force_rebuild=True,
        )
        self.assertIsNotNone(mat_anim)
        self.assertTrue(mat_anim.get("mtk_is_animated"))
        self.assertEqual(mat_anim.name, "MTK:Atlas:blocks:anim:001")

        node_names = [n.name for n in mat_anim.node_tree.nodes]
        self.assertIn("Animation Scheduler", node_names)
        self.assertIn("Animated UV Mapping", node_names)
        self.assertIn("Animated Frame Blend", node_names)
        self.assertIn("Atlas Albedo Texture (Current)", node_names)
        self.assertIn("Atlas Albedo Texture (Next)", node_names)

        uv_node = mat_anim.node_tree.nodes["Animated UV Mapping"]
        self.assertEqual(uv_node.inputs["Atlas Mode"].default_value, 1.0)
        self.assertEqual(uv_node.inputs["Image Width"].default_value, 2048.0)
        self.assertEqual(uv_node.inputs["Image Height"].default_value, 2048.0)

        # 2. Build a static atlas material
        mat_static = build_atlas_chunk_material(
            chunk_id=0,
            albedo_path=test_img_path,
            category="blocks",
            category_chunk_index=1,
            is_animated=False,
            atlas_width=2048.0,
            atlas_height=2048.0,
            tile_width=16.0,
            tile_height=16.0,
            force_rebuild=True,
        )
        self.assertIsNotNone(mat_static)
        self.assertFalse(mat_static.get("mtk_is_animated"))
        self.assertEqual(mat_static.name, "MTK:Atlas:blocks:001")

        static_node_names = [n.name for n in mat_static.node_tree.nodes]
        # Must NOT contain animation scheduler or blend nodes (zero overhead baseline)
        self.assertNotIn("Animation Scheduler", static_node_names)
        self.assertNotIn("Animated UV Mapping", static_node_names)
        self.assertNotIn("Animated Frame Blend", static_node_names)
        self.assertIn("Atlas Albedo Texture", static_node_names)

    @unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
    def test_atlas_builder_animated_pbr_blend_node_structure(self):
        try:
            from MoziToolKit.utils.materials.builder.atlas_builder import build_atlas_chunk_material
        except ImportError:
            from MoziToolKit.utils.materials.builder.atlas_builder import build_atlas_chunk_material

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            alb = tmp / "test_pbr_albedo.png"
            norm = tmp / "test_pbr_n.png"
            orm = tmp / "test_pbr_orm.png"
            aux = tmp / "test_pbr_aux.png"
            over = tmp / "test_pbr_overlay.png"
            png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10\x08\x06\x00\x00\x00\x1f\xf3\xffa\x00\x00\x00\x1fIDATh\x81\xed\xc1\x01\r\x00\x00\x00\xc2 \xfb\xa77\xc7\x0e\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x04\x00\x01\xa7\xeb\x99\x1e\x00\x00\x00\x00IEND\xaeB`\x82"
            for path in [alb, norm, orm, aux, over]:
                path.write_bytes(png_bytes)

            mat_pbr_anim = build_atlas_chunk_material(
                chunk_id=2,
                albedo_path=alb,
                normal_path=norm,
                orm_path=orm,
                aux_path=aux,
                overlay_path=over,
                category="blocks",
                category_chunk_index=2,
                is_animated=True,
                atlas_width=1024.0,
                atlas_height=1024.0,
                tile_width=16.0,
                tile_height=16.0,
                force_rebuild=True,
            )

        self.assertIsNotNone(mat_pbr_anim)
        nodes = {n.name: n for n in mat_pbr_anim.node_tree.nodes}

        for expected in [
            "Atlas Albedo Texture (Current)",
            "Atlas Albedo Texture (Next)",
            "Animated Frame Blend",
            "Atlas Normal Texture (Current)",
            "Atlas Normal Texture (Next)",
            "Animated Normal Blend",
            "Atlas ORM Texture (Current)",
            "Atlas ORM Texture (Next)",
            "Animated ORM Blend",
            "Atlas Aux Texture (Current)",
            "Atlas Aux Texture (Next)",
            "Animated Aux Blend",
            "Atlas Overlay Texture (Current)",
            "Atlas Overlay Texture (Next)",
            "Animated Overlay Blend",
            "Principled BSDF",
            "Normal Map",
            "Separate ORM",
            "Separate Aux",
            "Albedo × AO",
            "IOR from Aux",
            "Emission Strength × Mask",
        ]:
            self.assertIn(expected, nodes, f"{expected} must be created for animated PBR material")
        self.assertNotIn("LabPBR Decoder", nodes)

        links = mat_pbr_anim.node_tree.links
        tint = nodes["MC Biome Tint"]

        normal_map = nodes["Normal Map"]
        normal_links = [link for link in links if link.to_socket == normal_map.inputs["Color"]]
        self.assertEqual(normal_links[0].from_node.name, "Animated Normal Blend")

        orm_separate = nodes["Separate ORM"]
        orm_links = [link for link in links if link.to_socket == orm_separate.inputs["Color"]]
        self.assertEqual(orm_links[0].from_node.name, "Animated ORM Blend")

        aux_separate = nodes["Separate Aux"]
        aux_links = [link for link in links if link.to_socket == aux_separate.inputs["Color"]]
        self.assertEqual(aux_links[0].from_node.name, "Animated Aux Blend")

        # ORM.A drives the emission strength multiplier, aux.R drives IOR.
        emission_node = nodes["Emission Strength × Mask"]
        emission_links = [link for link in links if link.to_socket == emission_node.inputs[0]]
        self.assertEqual(emission_links[0].from_node.name, "Animated ORM Blend")
        self.assertEqual(emission_links[0].from_socket.name, "Emission")

        ior_node = nodes["IOR from Aux"]
        ior_links = [link for link in links if link.to_socket == ior_node.inputs[0]]
        self.assertEqual(ior_links[0].from_socket, aux_separate.outputs["Red"])

        # Check Biome Tint overlay connections.
        tint_over_col = [link for link in links if link.to_socket == tint.inputs["Overlay Color"]]
        tint_over_alpha = [link for link in links if link.to_socket == tint.inputs["Overlay Alpha"]]
        self.assertEqual(tint_over_col[0].from_node.name, "Animated Overlay Blend")
        self.assertEqual(tint_over_alpha[0].from_node.name, "Animated Overlay Blend")


if __name__ == "__main__":
    unittest.main()
