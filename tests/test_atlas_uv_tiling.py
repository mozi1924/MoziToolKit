"""Unit tests for MC_Atlas_UV_Tiling node group."""

import unittest
import bpy

from utils.node_groups.atlas_uv_tiling import ensure_atlas_uv_tiling, ATLAS_UV_TILING_VERSION


class TestAtlasUVTiling(unittest.TestCase):
    def test_atlas_uv_tiling_group_creation(self):
        group = ensure_atlas_uv_tiling()
        self.assertIsNotNone(group)
        self.assertEqual(group.name, "MC_Atlas_UV_Tiling")
        self.assertEqual(group.get("mozi_template_version"), ATLAS_UV_TILING_VERSION)
        self.assertTrue(group.get("mozi_template_complete"))

        # Verify interface sockets
        input_names = [
            s.name for s in group.interface.items_tree
            if s.item_type == "SOCKET" and s.in_out == "INPUT"
        ]
        output_names = [
            s.name for s in group.interface.items_tree
            if s.item_type == "SOCKET" and s.in_out == "OUTPUT"
        ]

        expected_inputs = [
            "Vector",
            "Scale",
            "Location",
            "Rotation",
            "Mapped Vector",
            "Use External Vector",
            "Atlas Width",
            "Atlas Height",
            "Tile Width",
            "Tile Height",
        ]
        expected_outputs = ["Atlas UV", "Local UV"]

        for exp in expected_inputs:
            self.assertIn(exp, input_names)
        for exp in expected_outputs:
            self.assertIn(exp, output_names)

    def test_atlas_material_builder_static_and_animated_tiling_nodes(self):
        import json
        import tempfile
        from pathlib import Path
        from utils.materials.atlas_builder import build_atlas_chunk_materials

        with tempfile.TemporaryDirectory() as tmp_dir:
            atlas_dir = Path(tmp_dir)

            # Create dummy images
            for name in ["chunk_000_albedo.png", "chunk_001_albedo.png"]:
                img = bpy.data.images.new(name, width=64, height=64)
                img.filepath_raw = str(atlas_dir / name)
                img.file_format = "PNG"
                img.save()
                bpy.data.images.remove(img)

            mapping = {
                "atlas_version": 1,
                "tile_size": 16,
                "chunks": [
                    {
                        "chunk_id": 0,
                        "kind": "static",
                        "width": 64,
                        "height": 64,
                        "tile_size": 16,
                        "files": {"albedo": "chunk_000_albedo.png"}
                    },
                    {
                        "chunk_id": 1,
                        "kind": "animation",
                        "width": 64,
                        "height": 64,
                        "tile_size": 16,
                        "files": {"albedo": "chunk_001_albedo.png"}
                    }
                ]
            }
            with open(atlas_dir / "atlas_mapping.json", "w", encoding="utf-8") as fp:
                json.dump(mapping, fp)

            materials = build_atlas_chunk_materials(atlas_dir, pack_textures=False)
            self.assertEqual(len(materials), 2)

            # 1. Verify Static Material (Chunk 0)
            mat_static = materials[0]
            nodes_static = {n.name: n for n in mat_static.node_tree.nodes}
            self.assertIn("MC Atlas UV Tiling", nodes_static)
            tiling_static = nodes_static["MC Atlas UV Tiling"]
            tex_static = nodes_static["Atlas Chunk 000 Static (Albedo)"]

            # TexCoord -> MC Atlas UV Tiling -> Texture Node
            self.assertEqual(tiling_static.inputs["Vector"].links[0].from_node.bl_idname, "ShaderNodeTexCoord")
            self.assertEqual(tex_static.inputs["Vector"].links[0].from_node, tiling_static)

            # 2. Verify Animated Material (Chunk 1)
            mat_anim = materials[1]
            nodes_anim = {n.name: n for n in mat_anim.node_tree.nodes}
            self.assertIn("MC UV Mapping (Albedo)", nodes_anim)
            self.assertIn("MC Atlas UV Tiling Current (Albedo)", nodes_anim)
            self.assertIn("MC Atlas UV Tiling Next (Albedo)", nodes_anim)

            uv_mapper = nodes_anim["MC UV Mapping (Albedo)"]
            tiling_curr = nodes_anim["MC Atlas UV Tiling Current (Albedo)"]
            tiling_next = nodes_anim["MC Atlas UV Tiling Next (Albedo)"]
            tex_curr = nodes_anim["Tex Current (Albedo)"]
            tex_next = nodes_anim["Tex Next (Albedo)"]

            # TexCoord -> MC UV Mapping (Albedo) -> MC Atlas UV Tiling Current/Next -> Tex Current/Next
            self.assertEqual(uv_mapper.inputs["Vector"].links[0].from_node.bl_idname, "ShaderNodeTexCoord")
            self.assertEqual(tiling_curr.inputs["Vector"].links[0].from_node, uv_mapper)
            self.assertEqual(tiling_curr.inputs["Vector"].links[0].from_socket.name, "Current UV")
            self.assertEqual(tiling_next.inputs["Vector"].links[0].from_node, uv_mapper)
            self.assertEqual(tiling_next.inputs["Vector"].links[0].from_socket.name, "Next UV")

            self.assertEqual(tex_curr.inputs["Vector"].links[0].from_node, tiling_curr)
            self.assertEqual(tex_curr.inputs["Vector"].links[0].from_socket.name, "Atlas UV")
            self.assertEqual(tex_next.inputs["Vector"].links[0].from_node, tiling_next)
            self.assertEqual(tex_next.inputs["Vector"].links[0].from_socket.name, "Atlas UV")


if __name__ == "__main__":
    unittest.main()
