"""
Integration tests for MoziToolKit Replace Material on Point Cloud / Procedural Geometry Nodes objects.
"""

import os
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

try:
    import bpy
    HAS_BPY = True
except ImportError:
    HAS_BPY = False


class TestReplaceMaterialPointCloud(unittest.TestCase):

    def setUp(self):
        if not HAS_BPY:
            self.skipTest("bpy module not available")

        # Clear scene
        bpy.ops.wm.read_factory_settings(use_empty=True)

        # Create Point Cloud object (Mesh with points, 0 polygons)
        self.mesh = bpy.data.meshes.new("Yefira_World_Mesh")
        self.obj = bpy.data.objects.new("Yefira_World", self.mesh)
        bpy.context.scene.collection.objects.link(self.obj)

        self.mesh.from_pydata([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], [], [])
        self.mesh.update()
        # This is the explicit Yefira variant marker.  Polygon-free meshes
        # without it remain ordinary procedural objects.
        states = self.mesh.attributes.new("block_state", 'STRING', 'POINT')
        for item in states.data:
            item.value = b"minecraft:stone"

        # Add dummy material slot
        dummy_mat = bpy.data.materials.new(name="Yefira_Atlas_Master")
        self.obj.data.materials.append(dummy_mat)

        # Add Geometry Nodes modifier
        self.mod = self.obj.modifiers.new(name="Yefira_WorldModifier", type='NODES')
        gn_tree = bpy.data.node_groups.new(name="Yefira_WorldTree", type='GeometryNodeTree')
        gn_tree.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
        gn_tree.interface.new_socket(name="Atlas Width", in_out='INPUT', socket_type='NodeSocketFloat')
        gn_tree.interface.new_socket(name="Atlas Height", in_out='INPUT', socket_type='NodeSocketFloat')
        gn_tree.interface.new_socket(name="Tile Size", in_out='INPUT', socket_type='NodeSocketFloat')
        gn_tree.interface.new_socket(name="Tiles Per Row", in_out='INPUT', socket_type='NodeSocketFloat')
        gn_tree.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

        nodes = gn_tree.nodes
        set_mat = nodes.new('GeometryNodeSetMaterial')
        set_mat.inputs['Material'].default_value = dummy_mat
        self.mod.node_group = gn_tree

    def test_replace_material_point_cloud(self):
        from utils.system.dependencies import has_pillow
        if not has_pillow():
            self.skipTest("Pillow not installed in test environment")

        import tempfile
        import zipfile
        from PIL import Image
        from pipeline.presets import run_preset_pipeline

        jar_env = os.environ.get("MC_JAR_PATH", "")
        jar_path = Path(jar_env) if jar_env else None

        tmp_dir = None
        if not jar_path or not jar_path.exists():
            tmp_dir = tempfile.TemporaryDirectory()
            zip_file = Path(tmp_dir.name) / "mock_pack.zip"
            with zipfile.ZipFile(zip_file, "w") as zf:
                # Add dummy texture
                img_path = Path(tmp_dir.name) / "stone.png"
                Image.new("RGBA", (16, 16), (128, 128, 128, 255)).save(img_path)
                zf.write(img_path, arcname="assets/minecraft/textures/block/stone.png")
            jar_path = zip_file

        params = {
            "zip_path": str(jar_path),
            "material_mode": "ATLAS",
            "pack_textures": True,
            "use_cache": True,
        }

        res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[self.obj])
        self.assertTrue(res.is_success, f"Replace material on point cloud failed: {res.message}")

        # Verify object's material slot was updated to atlas chunk material
        assigned_mat = self.obj.material_slots[0].material
        self.assertIsNotNone(assigned_mat)
        self.assertTrue(assigned_mat.name.startswith("mtk:minecraft:atlas_chunk_"))

        # Verify custom properties on material
        self.assertIn("mtk_atlas_width", assigned_mat)
        self.assertIn("mtk_atlas_height", assigned_mat)
        self.assertIn("mtk_tile_size", assigned_mat)
        self.assertIn("mtk_tiles_per_row", assigned_mat)
        self.assertIn("mtk:atlas_mapping", assigned_mat)

        # Verify Geometry Nodes modifier Set Material node was updated
        set_mat_nodes = [n for n in self.mod.node_group.nodes if n.type == 'SET_MATERIAL']
        self.assertEqual(len(set_mat_nodes), 1)
        self.assertEqual(set_mat_nodes[0].inputs['Material'].default_value, assigned_mat)

        # Yefira's evaluated shader path is a separate material variant.
        self.assertEqual(assigned_mat.get("mtk:atlas_uv_source"), "UVMap")
        uv_source = next(n for n in assigned_mat.node_tree.nodes if n.name == "Atlas UV Attribute (UVMap)")
        self.assertEqual(uv_source.attribute_name, "UVMap")
        self.assertIn("mtk_tile_top", self.mesh.attributes)
        self.assertIn("mtk_texture_top", self.mesh.attributes)
        self.assertNotIn("mtk:atlas_mapping", self.mesh)

    def test_generated_model_uses_texture_table_when_faces_are_null(self):
        """Stained glass has a generated model but a valid Atlas texture."""
        from pipeline.steps.step_replace_material import _write_yefira_point_atlas_attributes

        mapping = {
            "textures": {
                "minecraft:block/blue_stained_glass": {
                    "chunk_id": 0,
                    "texture_id": 125,
                    "tile_column": 125,
                    "tile_row": 0,
                },
            },
            "materials": [{
                "name": "blue_stained_glass",
                "material_id": 99,
                "faces": {face: None for face in ("+X", "-X", "+Y", "-Y", "+Z", "-Z")},
            }],
        }
        self.mesh.attributes["block_state"].data[0].value = b"minecraft:blue_stained_glass"
        _write_yefira_point_atlas_attributes(self.mesh, mapping)

        self.assertEqual(tuple(self.mesh.attributes["mtk_tile_east"].data[0].vector), (125.0, 0.0, 0.0))
        self.assertEqual(self.mesh.attributes["mtk_texture_east"].data[0].value, 125)

    def test_grass_tint_weights_are_face_specific(self):
        """Grass must not propagate its top tint to dirt or side base faces."""
        from pipeline.steps.step_replace_material import _write_yefira_point_atlas_attributes

        no_tint = {"default_base_tint_weight": 0.0, "default_overlay_tint_weight": 0.0, "default_tint_weight": 0.0}
        side_overlay = {"default_base_tint_weight": 0.0, "default_overlay_tint_weight": 1.0, "default_tint_weight": 1.0}
        grass_top = {"default_base_tint_weight": 1.0, "default_overlay_tint_weight": 1.0, "default_tint_weight": 1.0}
        mapping = {"materials": [{
            "name": "grass_block",
            "faces": {
                "+X": side_overlay, "-X": side_overlay, "+Y": grass_top,
                "-Y": no_tint, "+Z": side_overlay, "-Z": side_overlay,
            },
        }]}
        self.mesh.attributes["block_state"].data[0].value = b"minecraft:grass_block"
        _write_yefira_point_atlas_attributes(self.mesh, mapping)

        self.assertEqual(tuple(self.mesh.attributes["mtk_tint_data_east"].data[0].color), (0.0, 1.0, 1.0, 0.0))
        self.assertEqual(tuple(self.mesh.attributes["mtk_tint_data_top"].data[0].color), (1.0, 1.0, 1.0, 0.0))
        self.assertEqual(tuple(self.mesh.attributes["mtk_tint_data_bottom"].data[0].color), (0.0, 0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
