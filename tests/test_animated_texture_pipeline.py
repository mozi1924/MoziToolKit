import unittest
import sys
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
            from ui.preferences import MOZI_AddonPreferences
            from operators.save.op_import_save import MTK_OT_import_minecraft_save

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
            from utils.materials.builder.atlas_builder import build_atlas_chunk_material

        # Create temporary dummy image for test
        test_img_path = Path("/tmp/test_anim_strip.png")
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


if __name__ == "__main__":
    unittest.main()
