"""
Integration tests for Replace Material step in Atlas Mode vs Standalone Mode in Blender.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import bpy
    HAS_BPY = True
except ImportError:
    HAS_BPY = False


class TestReplaceMaterialAtlasMode(unittest.TestCase):

    def setUp(self):
        if not HAS_BPY:
            self.skipTest("bpy module not available")

        import os
        jar_env = os.environ.get("MC_JAR_PATH", "")
        self.jar_path = Path(jar_env) if jar_env else None
        if not self.jar_path or not self.jar_path.exists():
            self.skipTest(f"JAR file not configured or found: {self.jar_path}")
        try:
            import zipfile
            with zipfile.ZipFile(self.jar_path, "r") as zf:
                pass
        except Exception:
            self.skipTest(f"JAR file not accessible: {self.jar_path}")

        # Clear existing scene objects and materials
        bpy.ops.wm.read_factory_settings(use_empty=True)

        # Create a test cube object with materials
        bpy.ops.mesh.primitive_cube_add()
        self.cube = bpy.context.active_object
        self.cube.name = "Test_Cube"

        # Create dummy original material 'stone'
        mat = bpy.data.materials.new(name="stone")
        self.cube.data.materials.append(mat)
        uv_layer = self.cube.data.uv_layers.active
        self.original_uvs = [item.uv.copy() for item in uv_layer.data] if uv_layer else None

    def test_standalone_mode(self):
        from pipeline.presets import run_preset_pipeline

        params = {
            "zip_path": str(self.jar_path),
            "material_mode": "STANDALONE",
            "pack_textures": True,
            "use_cache": True,
        }

        res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[self.cube])
        self.assertTrue(res.is_success, f"Standalone mode failed: {res.message}")
        self.assertIn("mtk:minecraft:stone", self.cube.material_slots[0].material.name)

    def test_atlas_mode(self):
        from utils.system import has_pillow
        if not has_pillow():
            self.skipTest("Pillow not installed in test environment")

        from pipeline.presets import run_preset_pipeline

        params = {
            "zip_path": str(self.jar_path),
            "material_mode": "ATLAS",
            "pack_textures": True,
            "use_cache": True,
        }

        res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[self.cube])
        self.assertTrue(res.is_success, f"Atlas mode failed: {res.message}")

        assigned_mat = self.cube.material_slots[0].material
        self.assertTrue(assigned_mat.name.startswith("mtk:minecraft:atlas_chunk_"))

        # Verify LabPBR 1.3 Decoder node group is present in the node tree
        node_names = [n.name for n in assigned_mat.node_tree.nodes]
        self.assertIn("LabPBR 1.3 Decoder", node_names)

        # Check metadata on material
        self.assertEqual(assigned_mat.get("mtk:source_namespace"), "minecraft")
        self.assertTrue(str(assigned_mat.get("mtk:source_texture")).startswith("atlas_chunk_"))
        self.assertIsNotNone(assigned_mat.get("mtk:pack_hash"))

        # Check image datablock naming with pack hash
        albedo_images = [img for img in bpy.data.images if img.name.startswith("atlas_chunk_")]
        self.assertGreater(len(albedo_images), 0)
        self.assertIn(":", albedo_images[0].name)

        # Check custom property on node tree
        self.assertIn("mtk:atlas_mapping", assigned_mat.node_tree)
        mapping_str = assigned_mat.node_tree["mtk:atlas_mapping"]
        self.assertIn("static_texture_count", mapping_str)

        # Chunk and local texture IDs are retained for a future procedural
        # decoder, while preview mode uses the rewritten UVs directly.
        self.assertIn("atlas_chunk_id", self.cube.data.attributes)
        self.assertIn("atlas_texture_id", self.cube.data.attributes)
        attr_values = [item.value for item in self.cube.data.attributes["atlas_texture_id"].data]
        self.assertEqual(len(attr_values), len(self.cube.data.polygons))

        # Texture/Material Preview does not run the shader decoder.  The
        # mesh's default UV layer must therefore point at atlas cells itself.
        uv_layer = self.cube.data.uv_layers.active_render or self.cube.data.uv_layers.active
        self.assertIsNotNone(uv_layer)
        self.assertTrue(any(
            (uv.uv - original).length > 1e-6
            for uv, original in zip(uv_layer.data, self.original_uvs)
        ))

    def test_atlas_mode_animated_material(self):
        from utils.system import has_pillow
        if not has_pillow():
            self.skipTest("Pillow not installed in test environment")

        from pipeline.presets import run_preset_pipeline

        # Replace material slot with valid animated block texture 'sea_lantern'
        mat = bpy.data.materials.new(name="sea_lantern")
        self.cube.data.materials.clear()
        self.cube.data.materials.append(mat)
        # Simulate files saved by older versions, which duplicated this data
        # on the object instead of relying solely on mesh face attributes.
        self.cube["mtk_anim_total_frames"] = 99
        self.cube["mtk_anim_frametime"] = 99
        self.cube["mtk_anim_interpolate"] = True
        self.cube["mtk_anim_frame_width"] = 99
        self.cube["mtk_anim_frame_height"] = 99

        params = {
            "zip_path": str(self.jar_path),
            "material_mode": "ATLAS",
            "pack_textures": True,
            "use_cache": True,
        }

        res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[self.cube])
        self.assertTrue(res.is_success, f"Atlas mode animated material failed: {res.message}")

        assigned_mat = self.cube.material_slots[0].material
        self.assertTrue(assigned_mat.name.startswith("mtk:minecraft:atlas_chunk_"))

        # Verify animation nodes inside node tree for animated chunk
        node_names = [n.name for n in assigned_mat.node_tree.nodes]
        self.assertIn("LabPBR 1.3 Decoder", node_names)
        self.assertTrue(any("Scheduler" in name for name in node_names))
        self.assertTrue(any("UV Mapping" in name for name in node_names))
        self.assertTrue(any("Frame Blend" in name for name in node_names))
        self.assertTrue(any("Attr Total Frames" in name for name in node_names))
        self.assertTrue(any("Attr Frametime" in name for name in node_names))

        # Animation metadata is stored per polygon, allowing one mesh to use
        # textures with different .mcmeta settings on different faces.
        for name in (
            "mtk_anim_total_frames", "mtk_anim_frametime",
            "mtk_anim_interpolate", "mtk_anim_frame_width",
            "mtk_anim_frame_height",
        ):
            attr = self.cube.data.attributes.get(name)
            self.assertIsNotNone(attr)
            self.assertEqual(attr.domain, "FACE")
            self.assertEqual(len(attr.data), len(self.cube.data.polygons))

        # The shader reads the mesh attributes, not object custom properties.
        self.assertNotIn("mtk_anim_total_frames", self.cube)
        self.assertNotIn("mtk_anim_frametime", self.cube)
        self.assertNotIn("mtk_anim_interpolate", self.cube)
        self.assertNotIn("mtk_anim_frame_width", self.cube)
        self.assertNotIn("mtk_anim_frame_height", self.cube)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
