"""Unit tests for MC_Atlas_UV_Tiling node group."""

import sys
import unittest
import math
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy
import bmesh
from mathutils import Vector

# Bootstrap MoziToolKit package (also activates the isolated test sandbox)
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

from utils.node_groups.atlas_uv_tiling import ensure_atlas_uv_tiling, ATLAS_UV_TILING_VERSION
from utils.materials.constants import ATTR_UV_TILING_TRANSFORM
from utils.mesh import (
    normalize_face_uv_for_atlas_tiling,
    face_uv_requires_atlas_tiling,
    restore_atlas_tiling_uv,
)


class TestAtlasUVTiling(unittest.TestCase):
    def test_optimized_face_uv_is_normalized_and_reconstructable(self):
        """A merged jmc2obj face remains a single quad while retaining its repeats."""
        mesh = bpy.data.meshes.new("TiledUVFace")
        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.new("UVMap")
        verts = [
            bm.verts.new((0.0, 0.0, 0.0)),
            bm.verts.new((3.0, 0.0, 0.0)),
            bm.verts.new((3.0, 2.0, 0.0)),
            bm.verts.new((0.0, 2.0, 0.0)),
        ]
        face = bm.faces.new(verts)
        original = [(-2.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-2.0, 1.0)]
        for loop, uv in zip(face.loops, original):
            loop[uv_layer].uv = Vector(uv)
        bm.to_mesh(mesh)
        bm.free()

        try:
            poly = mesh.polygons[0]
            scale, location = normalize_face_uv_for_atlas_tiling(poly, mesh.uv_layers.active)
            self.assertEqual(scale, (3.0, 2.0, 1.0))
            self.assertEqual(location, (-1.0, -0.5, 0.0))

            # The Atlas tiling Mapping node evaluates this affine transform
            # around 0.5. It must reconstruct the source coordinate exactly
            # before FRACT keeps the sample inside the assigned Atlas cell.
            for loop_index, expected in zip(poly.loop_indices, original):
                uv = mesh.uv_layers.active.data[loop_index].uv
                restored = restore_atlas_tiling_uv(uv.x, uv.y, scale, location)
                self.assertAlmostEqual(restored[0], expected[0])
                self.assertAlmostEqual(restored[1], expected[1])
                self.assertGreaterEqual(uv.x, 0.0)
                self.assertLessEqual(uv.x, 1.0)
                self.assertGreaterEqual(uv.y, 0.0)
                self.assertLessEqual(uv.y, 1.0)
        finally:
            bpy.data.meshes.remove(mesh)

    def test_standalone_restore_bakes_atlas_tiling_rotation(self):
        """The standalone fallback must reproduce the Atlas node transform."""
        # This is jmc2obj's south-west liquid corner: the Atlas mesh stores
        # (0, 0), while the shader rotates it by 45° around UV center.
        u, v = restore_atlas_tiling_uv(0.0, 0.0, rotation=math.pi / 4.0)
        self.assertAlmostEqual(u, 0.5, places=6)
        self.assertAlmostEqual(v, 0.5 - math.sqrt(0.5), places=6)

        # A merged 3 x 2 face additionally restores its source offset.
        u, v = restore_atlas_tiling_uv(1.0, 1.0, (3.0, 2.0, 1.0), (-1.0, -0.5, 0.0))
        self.assertAlmostEqual(u, 1.0, places=6)
        self.assertAlmostEqual(v, 1.0, places=6)

    def test_partial_uv_island_does_not_enable_tiling(self):
        """Pixel-split and partial-model faces are already Atlas-safe."""
        mesh = bpy.data.meshes.new("PartialUVFace")
        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.new("UVMap")
        verts = [bm.verts.new((x, y, 0.0)) for x, y in ((0, 0), (1, 0), (1, 1), (0, 1))]
        face = bm.faces.new(verts)
        partial = ((0.25, 0.125), (0.3125, 0.125), (0.3125, 0.1875), (0.25, 0.1875))
        for loop, coord in zip(face.loops, partial):
            loop[uv_layer].uv = Vector(coord)
        bm.to_mesh(mesh)
        bm.free()
        try:
            poly = mesh.polygons[0]
            active_uv = mesh.uv_layers.active
            self.assertFalse(face_uv_requires_atlas_tiling(poly, active_uv))
            self.assertEqual(
                [(round(active_uv.data[i].uv.x, 6), round(active_uv.data[i].uv.y, 6)) for i in poly.loop_indices],
                list(partial),
            )
        finally:
            bpy.data.meshes.remove(mesh)

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

    def test_atlas_material_builder_tiling_disabled_by_default(self):
        """When enable_uv_tiling=False (default for Yefira and Ice Cube), no tiling nodes or attributes exist."""
        import json
        import tempfile
        from pathlib import Path
        from utils.materials.atlas.builder import build_atlas_chunk_materials
        from utils.materials.constants import PROP_ENABLE_UV_TILING

        with tempfile.TemporaryDirectory() as tmp_dir:
            atlas_dir = Path(tmp_dir)

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

            materials = build_atlas_chunk_materials(atlas_dir, pack_textures=False, enable_uv_tiling=False)
            self.assertEqual(len(materials), 2)

            # 1. Verify Static Material (Chunk 0) has NO tiling nodes/attributes
            mat_static = materials[0]
            self.assertFalse(mat_static.get(PROP_ENABLE_UV_TILING, False))
            nodes_static = {n.name: n for n in mat_static.node_tree.nodes}
            self.assertNotIn("MC Atlas UV Tiling", nodes_static)
            self.assertNotIn("Attr UV Tiling Transform", nodes_static)
            self.assertNotIn("Combine UV Tiling Scale", nodes_static)
            self.assertNotIn("Combine UV Tiling Location", nodes_static)

            tex_static = nodes_static["Atlas Chunk 000 Static (Albedo)"]
            self.assertEqual(tex_static.inputs["Vector"].links[0].from_node.bl_idname, "ShaderNodeTexCoord")

            # 2. Verify Animated Material (Chunk 1) has NO tiling nodes/attributes
            mat_anim = materials[1]
            self.assertFalse(mat_anim.get(PROP_ENABLE_UV_TILING, False))
            nodes_anim = {n.name: n for n in mat_anim.node_tree.nodes}
            self.assertNotIn("MC Atlas UV Tiling (Albedo)", nodes_anim)
            self.assertNotIn("Attr UV Tiling Transform", nodes_anim)

            uv_mapper = nodes_anim["MC UV Mapping (Albedo)"]
            tex_curr = nodes_anim["Tex Current (Albedo)"]
            tex_next = nodes_anim["Tex Next (Albedo)"]

            self.assertEqual(uv_mapper.inputs["Vector"].links[0].from_node.bl_idname, "ShaderNodeTexCoord")
            self.assertEqual(tex_curr.inputs["Vector"].links[0].from_node, uv_mapper)
            self.assertEqual(tex_next.inputs["Vector"].links[0].from_node, uv_mapper)

    def test_atlas_material_builder_static_and_animated_tiling_nodes(self):
        """When enable_uv_tiling=True (for JMC2OBJ/Mineways static replacement), tiling nodes are created."""
        import json
        import tempfile
        from pathlib import Path
        from utils.materials.atlas.builder import build_atlas_chunk_materials
        from utils.materials.constants import PROP_ENABLE_UV_TILING

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

            materials = build_atlas_chunk_materials(atlas_dir, pack_textures=False, enable_uv_tiling=True)
            self.assertEqual(len(materials), 2)

            # 1. Verify Static Material (Chunk 0)
            mat_static = materials[0]
            self.assertTrue(mat_static.get(PROP_ENABLE_UV_TILING, False))
            nodes_static = {n.name: n for n in mat_static.node_tree.nodes}
            self.assertIn("MC Atlas UV Tiling", nodes_static)
            self.assertIn("Attr UV Tiling Transform", nodes_static)
            tiling_static = nodes_static["MC Atlas UV Tiling"]
            tex_static = nodes_static["Atlas Chunk 000 Static (Albedo)"]
            self.assertEqual(tiling_static.inputs["Vector"].links[0].from_node.bl_idname, "ShaderNodeTexCoord")
            self.assertEqual(tiling_static.inputs["Scale"].links[0].from_node, nodes_static["Combine UV Tiling Scale"])
            self.assertEqual(tiling_static.inputs["Location"].links[0].from_node, nodes_static["Combine UV Tiling Location"])
            self.assertEqual(tex_static.inputs["Vector"].links[0].from_node, tiling_static)

            # 2. Verify Animated Material (Chunk 1)
            mat_anim = materials[1]
            self.assertTrue(mat_anim.get(PROP_ENABLE_UV_TILING, False))
            nodes_anim = {n.name: n for n in mat_anim.node_tree.nodes}
            self.assertIn("MC Atlas UV Tiling (Albedo)", nodes_anim)
            self.assertIn("MC UV Mapping (Albedo)", nodes_anim)

            tiling_anim = nodes_anim["MC Atlas UV Tiling (Albedo)"]
            uv_mapper = nodes_anim["MC UV Mapping (Albedo)"]
            tex_curr = nodes_anim["Tex Current (Albedo)"]
            tex_next = nodes_anim["Tex Next (Albedo)"]

            self.assertEqual(tiling_anim.inputs["Vector"].links[0].from_node.bl_idname, "ShaderNodeTexCoord")
            self.assertEqual(uv_mapper.inputs["Vector"].links[0].from_node, tiling_anim)
            self.assertEqual(uv_mapper.inputs["Vector"].links[0].from_socket.name, "Atlas UV")
            self.assertEqual(tex_curr.inputs["Vector"].links[0].from_node, uv_mapper)
            self.assertEqual(tex_curr.inputs["Vector"].links[0].from_socket.name, "Current UV")
            self.assertEqual(tex_next.inputs["Vector"].links[0].from_node, uv_mapper)
            self.assertEqual(tex_next.inputs["Vector"].links[0].from_socket.name, "Next UV")

            # 3. Verify Safe Frame Size nodes exist and MAXIMUM nodes are NOT used
            self.assertIn("Safe Frame Width", nodes_anim)
            self.assertIn("Safe Frame Height", nodes_anim)
            self.assertIn("Is Frame Width Non-Zero", nodes_anim)
            self.assertIn("Is Frame Height Non-Zero", nodes_anim)
            self.assertNotIn("Max Frame Width", nodes_anim)
            self.assertNotIn("Max Frame Height", nodes_anim)

    def test_atlas_uv_tiling_bypass_and_clamping_nodes(self):
        """Verify MC_Atlas_UV_Tiling has identity bypass and boundary clamping nodes."""
        group = ensure_atlas_uv_tiling()
        node_names = {n.name: n for n in group.nodes}

        # Check boundary clamping
        self.assertIn("Col Index Max Clamp", node_names)
        self.assertIn("Row Index Max Clamp", node_names)
        self.assertIn("Clamp Atlas U Min", node_names)
        self.assertIn("Final Atlas U", node_names)
        self.assertIn("Clamp Atlas V Min", node_names)
        self.assertIn("Final Atlas V", node_names)

        # Check continuous local UV calculation
        self.assertIn("U - Cell Min U", node_names)
        self.assertIn("V - Cell Min V", node_names)

        # Check identity bypass logic
        self.assertIn("Is Transform Active", node_names)
        self.assertIn("Bypass Mix", node_names)
        bypass = node_names["Bypass Mix"]
        self.assertEqual(bypass.data_type, "VECTOR")

        # Group output Atlas UV must be fed from Bypass Mix
        group_out = node_names["Group Output"]
        atlas_uv_in = group_out.inputs["Atlas UV"]
        self.assertTrue(atlas_uv_in.is_linked)
        self.assertEqual(atlas_uv_in.links[0].from_node, bypass)

    def test_animation_scheduler_timeline_frame_driver_target(self):
        """Verify MC_Animation_Scheduler_Default Timeline Frame driver explicitly targets SCENE.frame_current."""
        from utils.node_groups.animated import ensure_animation_scheduler, SCHEDULER_TEMPLATE_VERSION

        scheduler = ensure_animation_scheduler()
        self.assertEqual(scheduler.get("mozi_template_version"), SCHEDULER_TEMPLATE_VERSION)

        self.assertIsNotNone(scheduler.animation_data)
        timeline_driver = None
        for d in scheduler.animation_data.drivers:
            if 'Timeline Frame' in d.data_path:
                timeline_driver = d
                break
        self.assertIsNotNone(timeline_driver)
        driver = timeline_driver.driver
        self.assertEqual(driver.expression, "frame")
        self.assertGreaterEqual(len(driver.variables), 1)
        var = driver.variables[0]
        self.assertEqual(var.name, "frame")
        self.assertEqual(var.targets[0].id_type, "SCENE")
        self.assertEqual(var.targets[0].data_path, "frame_current")

    def test_pipeline_origin_tiling_decision(self):
        """Verify the pipeline's detection of whether UV tiling is required based on object/material origin."""
        from utils.materials.matching import material_source_origin

        # JMC2OBJ / Mineways -> requires tiling
        mat_jmc = bpy.data.materials.new("jmc2obj_stone")
        mat_jmc.use_nodes = True
        bsdf_jmc = mat_jmc.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
        tex_jmc = mat_jmc.node_tree.nodes.new("ShaderNodeTexImage")
        img_jmc = bpy.data.images.new("stone.png", width=16, height=16)
        tex_jmc.image = img_jmc
        mat_jmc.node_tree.links.new(tex_jmc.outputs["Color"], bsdf_jmc.inputs["Base Color"])

        mat_mw = bpy.data.materials.new("mw_chest_normal")

        # Ice Cube / Yefira -> does NOT require tiling
        mat_ice = bpy.data.materials.new("oak_planks")
        mat_ice["ice_cube.material_id"] = "minecraft:oak_planks"

        yefira_obj = bpy.data.objects.new("Yefira_Section_0_0_0", bpy.data.meshes.new("YefiraMesh"))
        yefira_obj["mtk:is_yefira_world"] = True

        self.assertEqual(material_source_origin(mat_jmc), "jmc2obj")
        self.assertEqual(material_source_origin(mat_mw), "mineways")
        self.assertEqual(material_source_origin(mat_ice), "ice_cube")
        self.assertTrue(yefira_obj.get("mtk:is_yefira_world"))

        # Clean up
        for m in (mat_jmc, mat_mw, mat_ice):
            bpy.data.materials.remove(m)
        bpy.data.images.remove(img_jmc)
        bpy.data.objects.remove(yefira_obj)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
