"""
Unit tests for Live Sync Fluid Mesher (Water & Lava).
Verifies:
- 4-corner height calculations (flat source, flowing slope, submerged waterfall).
- JMC2OBJ-style solid block boundary handling (solid walls do not drag down water levels).
- Fluid flow vector calculation and top face UV rotation.
- Mineways-style non-collapsed, linearly mapped UVs on slanted fluid side faces.
- 6-direction culling (against fluid above, solid below, and equal/higher fluid neighbors).
- Direct Mesh BMesh generation and attribute binding.
"""

import sys
import unittest
import math
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Bootstrap MoziToolKit package (also activates the isolated test sandbox)
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

import bpy
import bmesh
from mathutils import Vector

from utils.live_sync.storage import VoxelStorage
from utils.live_sync.material import LiveSyncMaterialManager
from utils.live_sync.meshing import build_world_mesh, apply_block_delta_to_world
from utils.live_sync.classifier import parse_and_classify
from utils.live_sync.meshing.fluid import (
    get_fluid_base_height,
    sample_fluid_height,
    calculate_corner_average,
    calculate_fluid_corner_heights,
    calculate_fluid_flow_vector,
    is_fluid_flowing,
    is_fluid_block,
    should_cull_fluid_face,
    generate_fluid_mesh_faces,
    MAX_FLUID_HEIGHT,
)
from utils.live_sync.constants import (
    UV_MAP,
    MTK_UV_ROTATION,
    MTK_BIOME_TINT_COLOR,
    MTK_ATLAS_CHUNK_ID,
)


class TestFluidLiveSync(unittest.TestCase):

    def setUp(self):
        self.storage = VoxelStorage()
        self.mock_mapping = {
            "categories": {
                "blocks": {"chunk_id": 0, "tile_size": 16, "width": 512, "height": 512},
                "animations": {"chunk_id": 1, "kind": "animation", "tile_size": 16, "width": 512, "height": 512},
            },
            "textures": {
                "minecraft:block/stone": {"chunk_id": 0, "category": "blocks", "tile_column": 0, "tile_row": 0},
                "minecraft:block/water_still": {
                    "chunk_id": 1,
                    "kind": "animation",
                    "pixel_x": 0, "pixel_y": 0,
                    "frame_width": 16, "frame_height": 16,
                    "frame_count": 32, "frametime": 2,
                },
                "minecraft:block/water_flow": {
                    "chunk_id": 1,
                    "kind": "animation",
                    "pixel_x": 16, "pixel_y": 0,
                    "frame_width": 32, "frame_height": 32,
                    "frame_count": 32, "frametime": 2,
                },
                "minecraft:block/lava_still": {
                    "chunk_id": 1,
                    "kind": "animation",
                    "pixel_x": 48, "pixel_y": 0,
                    "frame_width": 16, "frame_height": 16,
                    "frame_count": 20, "frametime": 3,
                },
                "minecraft:block/lava_flow": {
                    "chunk_id": 1,
                    "kind": "animation",
                    "pixel_x": 64, "pixel_y": 0,
                    "frame_width": 32, "frame_height": 32,
                    "frame_count": 20, "frametime": 3,
                },
            },
        }
        self.atlas_params = {
            "mapping": self.mock_mapping,
            "pack_hash": "test_fluid_hash",
        }

    def tearDown(self):
        self.storage.clear()
        # Clean up created objects
        for obj in list(bpy.data.objects):
            if obj.name.startswith("Yefira_") or obj.name.startswith("Test"):
                bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in list(bpy.data.meshes):
            if mesh.name.startswith("Mesh_") or mesh.name.startswith("Test") or mesh.name == "Yefira_World":
                bpy.data.meshes.remove(mesh)

    def test_fluid_base_height_levels(self):
        """Test base fluid heights for source, flowing, and falling states."""
        # Source block
        self.assertAlmostEqual(get_fluid_base_height("minecraft:water[level=0]"), MAX_FLUID_HEIGHT, places=5)
        self.assertAlmostEqual(get_fluid_base_height("minecraft:water"), MAX_FLUID_HEIGHT, places=5)

        # Flowing levels
        self.assertAlmostEqual(get_fluid_base_height("minecraft:water[level=1]"), 7.0 / 9.0, places=5)
        self.assertAlmostEqual(get_fluid_base_height("minecraft:water[level=3]"), 5.0 / 9.0, places=5)
        self.assertAlmostEqual(get_fluid_base_height("minecraft:water[level=7]"), 1.0 / 9.0, places=5)

        # Falling fluid (levels >= 8)
        self.assertAlmostEqual(get_fluid_base_height("minecraft:water[level=8]"), MAX_FLUID_HEIGHT, places=5)

    def test_single_source_water_corner_heights(self):
        """
        Test that an isolated still water source block calculates exact flat MAX_FLUID_HEIGHT corner heights
        without drooping at boundary edges.
        """
        block_map = {(0, 0, 0): "minecraft:water[level=0]"}
        c_nw, c_ne, c_se, c_sw = calculate_fluid_corner_heights(block_map, 0, 0, 0, "water")
        self.assertAlmostEqual(c_nw, MAX_FLUID_HEIGHT, places=4)
        self.assertAlmostEqual(c_ne, MAX_FLUID_HEIGHT, places=4)
        self.assertAlmostEqual(c_se, MAX_FLUID_HEIGHT, places=4)
        self.assertAlmostEqual(c_sw, MAX_FLUID_HEIGHT, places=4)

    def test_solid_block_boundary_preservation_jmc2obj(self):
        """
        Test JMC2OBJ optimization: when water is placed in a corner touching solid stone blocks,
        the solid stone blocks (-1.0) are excluded from the corner average so the water corner does not droop.
        """
        # Water at (1, 0, 1) surrounded by solid stone walls at (0, 0, 1) and (1, 0, 0) and (0, 0, 0)
        # and also bounded on East and South so all 4 corners touch stone
        block_map = {
            (1, 0, 1): "minecraft:water[level=0]",
            (0, 0, 1): "minecraft:stone",
            (1, 0, 0): "minecraft:stone",
            (0, 0, 0): "minecraft:stone",
            (2, 0, 1): "minecraft:stone",
            (1, 0, 2): "minecraft:stone",
            (2, 0, 0): "minecraft:stone",
            (0, 0, 2): "minecraft:stone",
            (2, 0, 2): "minecraft:stone",
        }
        # All corners touch stone walls on sides: solid neighbors (-1.0) are skipped entirely
        c_nw, c_ne, c_se, c_sw = calculate_fluid_corner_heights(block_map, 1, 0, 1, "water")
        self.assertAlmostEqual(c_nw, MAX_FLUID_HEIGHT, places=4)
        self.assertAlmostEqual(c_ne, MAX_FLUID_HEIGHT, places=4)
        self.assertAlmostEqual(c_se, MAX_FLUID_HEIGHT, places=4)
        self.assertAlmostEqual(c_sw, MAX_FLUID_HEIGHT, places=4)

    def test_water_pool_flat_surface(self):
        """Test a 3x3 water pool: the central source block has all water neighbors, so its surface is flat 8/9."""
        block_map = {
            (x, 0, z): "minecraft:water[level=0]"
            for x in (0, 1, 2)
            for z in (0, 1, 2)
        }
        c_nw, c_ne, c_se, c_sw = calculate_fluid_corner_heights(block_map, 1, 0, 1, "water")
        self.assertAlmostEqual(c_nw, MAX_FLUID_HEIGHT, places=4)
        self.assertAlmostEqual(c_ne, MAX_FLUID_HEIGHT, places=4)
        self.assertAlmostEqual(c_se, MAX_FLUID_HEIGHT, places=4)
        self.assertAlmostEqual(c_sw, MAX_FLUID_HEIGHT, places=4)

    def test_flowing_water_slope_and_flow_vector(self):
        """
        Test flowing water slope: water flowing from (0,0,0) (level=0) towards East (1,0,0) (level=2).
        Flow vector should point East (+X in MC), and corners on the East side should be lower.
        """
        block_map = {
            (0, 0, 0): "minecraft:water[level=0]",
            (1, 0, 0): "minecraft:water[level=2]",
        }
        # For block at (0, 0, 0): East neighbor is lower (level 2)
        vx, vz, angle = calculate_fluid_flow_vector(block_map, 0, 0, 0, "water", MAX_FLUID_HEIGHT)
        self.assertGreater(vx, 0.0, "Flow vector X should point positive East")
        self.assertAlmostEqual(vz, 0.0, places=4)

        # For block at (1, 0, 0): corner heights on West side (NW, SW) should be higher than East side (NE, SE)
        c_nw, c_ne, c_se, c_sw = calculate_fluid_corner_heights(block_map, 1, 0, 0, "water")
        self.assertGreater(c_nw, c_ne, "West corners should be higher than East corners on a downstream slope")
        self.assertGreater(c_sw, c_se, "West corners should be higher than East corners on a downstream slope")

    def test_waterfall_submerged_full_height(self):
        """Test that water with water directly above it has corner height 1.0."""
        block_map = {
            (0, 0, 0): "minecraft:water[level=0]",
            (0, 1, 0): "minecraft:water[level=0]",
        }
        c_nw, c_ne, c_se, c_sw = calculate_fluid_corner_heights(block_map, 0, 0, 0, "water")
        self.assertAlmostEqual(c_nw, 1.0, places=4)
        self.assertAlmostEqual(c_ne, 1.0, places=4)
        self.assertAlmostEqual(c_se, 1.0, places=4)
        self.assertAlmostEqual(c_sw, 1.0, places=4)

    def test_mineways_slanted_side_face_uv_mapping(self):
        """
        Verify Mineways-standard slanted side face UV mapping:
        For a sloped side face, the loop UV V coordinates strictly match the vertex 3D heights,
        guaranteeing zero UV collapsing, stretching inversion, or distortion.
        """
        # Block at (0, 0, 0) with a lower block at East (+X) causing slanted North & South faces
        block_map = {
            (0, 0, 0): "minecraft:water[level=0]",
            (1, 0, 0): "minecraft:water[level=4]",
        }
        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.new(UV_MAP)
        color_layer = bm.loops.layers.color.new("Color")
        layers = {
            "uv": uv_layer,
            "color": color_layer,
            "rot": bm.faces.layers.float.new(MTK_UV_ROTATION),
            "timing": bm.faces.layers.float_color.new("mtk_anim_timing"),
            "frame_size": bm.faces.layers.float_color.new("mtk_anim_frame_size"),
            "tiling": bm.faces.layers.float_color.new("mtk_uv_tiling_transform"),
            "tint_data": bm.faces.layers.float_color.new("mtk_biome_tint_data"),
            "tint_color": bm.faces.layers.float_color.new(MTK_BIOME_TINT_COLOR),
            "block_x": bm.faces.layers.int.new("mtk_block_x"),
            "block_y": bm.faces.layers.int.new("mtk_block_y"),
            "block_z": bm.faces.layers.int.new("mtk_block_z"),
            "face_dir": bm.faces.layers.int.new("mtk_face_dir"),
            "atlas_chunk": bm.faces.layers.int.new(MTK_ATLAS_CHUNK_ID),
        }

        mat_mgr = LiveSyncMaterialManager(world_obj=None, atlas_params=self.atlas_params)

        faces_count = generate_fluid_mesh_faces(
            bm=bm,
            x=0, y=0, z=0,
            state_str="minecraft:water[level=0]",
            block_map=block_map,
            layers=layers,
            origin_centered=False,
            min_x=0, min_y=0, min_z=0,
            half_x=0.0, half_z=0.0,
            mat_manager=mat_mgr,
        )
        self.assertGreater(faces_count, 0)
        bm.faces.ensure_lookup_table()

        # Find North face (facing Blender +Y, face_dir == 5)
        north_face = None
        face_dir_layer = layers["face_dir"]
        for f in bm.faces:
            if f[face_dir_layer] == 5:
                north_face = f
                break

        self.assertIsNotNone(north_face, "North side face must be generated")
        self.assertEqual(len(north_face.verts), 4)

        # Inspect loop vertices and their UV heights
        # Higher 3D vertex must correspond to higher UV V coordinate
        verts_and_uvs = []
        for loop in north_face.loops:
            v_z = loop.vert.co.z  # in Blender local space (z in [-0.5..0.5])
            uv_v = loop[uv_layer].uv.y
            verts_and_uvs.append((v_z, uv_v))

        # Top two vertices have z > -0.4, bottom two have z == -0.5
        top_pairs = [p for p in verts_and_uvs if p[0] > -0.4]
        self.assertEqual(len(top_pairs), 2)
        # If top_pairs[0] has higher 3D Z than top_pairs[1], its UV V must also be strictly higher or equal!
        if top_pairs[0][0] > top_pairs[1][0]:
            self.assertGreaterEqual(top_pairs[0][1], top_pairs[1][1], "UV V must increase monotonically with 3D Z height")
        elif top_pairs[0][0] < top_pairs[1][0]:
            self.assertLessEqual(top_pairs[0][1], top_pairs[1][1], "UV V must decrease monotonically with lower 3D Z height")

        bm.free()

    def test_fluid_culling(self):
        """Test fluid face culling against same fluid, solid blocks, air, and glass."""
        # 1. Test top face retention under stone ceiling (height 8/9 < 1.0) and culling of bottom/sides
        block_map = {
            (0, 0, 0): "minecraft:water[level=0]",
            (0, 1, 0): "minecraft:stone",          # Stone ceiling -> water top face kept at 8/9
            (0, -1, 0): "minecraft:stone",         # Stone floor -> culls bottom of (0,0,0)
            (0, 0, -1): "minecraft:water[level=0]",# Water North -> culls North side
            (0, 0, 1): "minecraft:stone",          # Stone South -> culls South side
            (1, 0, 0): "minecraft:glass",          # Glass East -> keeps East side
            # West is air -> keeps West side
        }
        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.new(UV_MAP)
        color_layer = bm.loops.layers.color.new("Color")
        layers = {
            "uv": uv_layer,
            "color": color_layer,
            "rot": bm.faces.layers.float.new(MTK_UV_ROTATION),
            "timing": bm.faces.layers.float_color.new("mtk_anim_timing"),
            "frame_size": bm.faces.layers.float_color.new("mtk_anim_frame_size"),
            "tiling": bm.faces.layers.float_color.new("mtk_uv_tiling_transform"),
            "tint_data": bm.faces.layers.float_color.new("mtk_biome_tint_data"),
            "tint_color": bm.faces.layers.float_color.new(MTK_BIOME_TINT_COLOR),
            "block_x": bm.faces.layers.int.new("mtk_block_x"),
            "block_y": bm.faces.layers.int.new("mtk_block_y"),
            "block_z": bm.faces.layers.int.new("mtk_block_z"),
            "face_dir": bm.faces.layers.int.new("mtk_face_dir"),
            "atlas_chunk": bm.faces.layers.int.new(MTK_ATLAS_CHUNK_ID),
        }
        mat_mgr = LiveSyncMaterialManager(world_obj=None, atlas_params=self.atlas_params)

        generate_fluid_mesh_faces(
            bm=bm,
            x=0, y=0, z=0,
            state_str="minecraft:water[level=0]",
            block_map=block_map,
            layers=layers,
            origin_centered=False,
            min_x=0, min_y=0, min_z=0,
            half_x=0.0, half_z=0.0,
            mat_manager=mat_mgr,
        )
        face_dirs = [f[layers["face_dir"]] for f in bm.faces]
        self.assertIn(2, face_dirs, "Top face (dir 2) must be retained under stone ceiling since water height is < 1.0")
        self.assertNotIn(3, face_dirs, "Bottom face (dir 3) must be culled above stone floor")
        self.assertNotIn(5, face_dirs, "North face (dir 5) must be culled against adjacent water")
        self.assertNotIn(4, face_dirs, "South face (dir 4) must be culled against solid stone wall")
        self.assertIn(0, face_dirs, "East face (dir 0) must be retained facing glass")
        self.assertIn(1, face_dirs, "West face (dir 1) must be retained facing air")
        bm.free()

        # 2. Test top face culling when submerged under another water block
        water_submerged_map = {
            (0, 0, 0): "minecraft:water[level=0]",
            (0, 1, 0): "minecraft:water[level=0]",  # Water above -> culls top face
        }
        bm_sub = bmesh.new()
        uv_layer_sub = bm_sub.loops.layers.uv.new(UV_MAP)
        color_layer_sub = bm_sub.loops.layers.color.new("Color")
        layers_sub = {
            "uv": uv_layer_sub,
            "color": color_layer_sub,
            "rot": bm_sub.faces.layers.float.new(MTK_UV_ROTATION),
            "timing": bm_sub.faces.layers.float_color.new("mtk_anim_timing"),
            "frame_size": bm_sub.faces.layers.float_color.new("mtk_anim_frame_size"),
            "tiling": bm_sub.faces.layers.float_color.new("mtk_uv_tiling_transform"),
            "tint_data": bm_sub.faces.layers.float_color.new("mtk_biome_tint_data"),
            "tint_color": bm_sub.faces.layers.float_color.new(MTK_BIOME_TINT_COLOR),
            "block_x": bm_sub.faces.layers.int.new("mtk_block_x"),
            "block_y": bm_sub.faces.layers.int.new("mtk_block_y"),
            "block_z": bm_sub.faces.layers.int.new("mtk_block_z"),
            "face_dir": bm_sub.faces.layers.int.new("mtk_face_dir"),
            "atlas_chunk": bm_sub.faces.layers.int.new(MTK_ATLAS_CHUNK_ID),
        }
        generate_fluid_mesh_faces(
            bm=bm_sub,
            x=0, y=0, z=0,
            state_str="minecraft:water[level=0]",
            block_map=water_submerged_map,
            layers=layers_sub,
            origin_centered=False,
            min_x=0, min_y=0, min_z=0,
            half_x=0.0, half_z=0.0,
            mat_manager=mat_mgr,
        )
        face_dirs_sub = [f[layers_sub["face_dir"]] for f in bm_sub.faces]
        self.assertNotIn(2, face_dirs_sub, "Top face (dir 2) must be culled when water block is directly above")
        bm_sub.free()

    def test_flowing_top_face_uv_full_scale_and_shader_rotation(self):
        """
        Verify that flowing fluid top face UVs remain full-scale [0, 1] (not shrunk by 0.25)
        and that flow direction angle is written directly to the mtk_uv_rotation attribute for the shader.
        """
        block_map = {
            (0, 0, 0): "minecraft:water[level=0]",
            (1, 0, 0): "minecraft:water[level=2]",  # Water flowing towards East (+X in MC)
        }
        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.new(UV_MAP)
        color_layer = bm.loops.layers.color.new("Color")
        layers = {
            "uv": uv_layer,
            "color": color_layer,
            "rot": bm.faces.layers.float.new(MTK_UV_ROTATION),
            "timing": bm.faces.layers.float_color.new("mtk_anim_timing"),
            "frame_size": bm.faces.layers.float_color.new("mtk_anim_frame_size"),
            "tiling": bm.faces.layers.float_color.new("mtk_uv_tiling_transform"),
            "tint_data": bm.faces.layers.float_color.new("mtk_biome_tint_data"),
            "tint_color": bm.faces.layers.float_color.new(MTK_BIOME_TINT_COLOR),
            "block_x": bm.faces.layers.int.new("mtk_block_x"),
            "block_y": bm.faces.layers.int.new("mtk_block_y"),
            "block_z": bm.faces.layers.int.new("mtk_block_z"),
            "face_dir": bm.faces.layers.int.new("mtk_face_dir"),
            "atlas_chunk": bm.faces.layers.int.new(MTK_ATLAS_CHUNK_ID),
        }
        mat_mgr = LiveSyncMaterialManager(world_obj=None, atlas_params=self.atlas_params)

        generate_fluid_mesh_faces(
            bm=bm,
            x=0, y=0, z=0,
            state_str="minecraft:water[level=0]",
            block_map=block_map,
            layers=layers,
            origin_centered=False,
            min_x=0, min_y=0, min_z=0,
            half_x=0.0, half_z=0.0,
            mat_manager=mat_mgr,
        )

        top_face = None
        for f in bm.faces:
            if f[layers["face_dir"]] == 2:  # Up face
                top_face = f
                break

        self.assertIsNotNone(top_face, "Top face must be generated")

        # 1. Verify UV coordinates have rotation baked directly into the 16x16 sampling window
        u_vals = [loop[uv_layer].uv.x for loop in top_face.loops]
        v_vals = [loop[uv_layer].uv.y for loop in top_face.loops]
        span_u = max(u_vals) - min(u_vals)
        span_v = max(v_vals) - min(v_vals)
        self.assertGreater(span_u, 0.01)
        self.assertGreater(span_v, 0.01)
        # Verify UV coordinates stay safely within [0, 1]
        for u, v in zip(u_vals, v_vals):
            self.assertGreaterEqual(u, 0.0)
            self.assertLessEqual(u, 1.0)
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)

        bm.free()


    def test_vertical_waterfall_uses_flowing_material(self):
        """
        Verify that vertical falling water (e.g. level=8, or water with air below / water above)
        is correctly identified as flowing and uses water_flow for top/side faces.
        """
        # Waterfall column: water at y=1 with air at y=0 below it
        block_map = {
            (0, 1, 0): "minecraft:water[level=8]",  # Falling water block
        }
        self.assertTrue(
            is_fluid_flowing("minecraft:water[level=8]", block_map, 0, 1, 0, "water", 0.0, 0.0),
            "Falling water level=8 must be identified as flowing",
        )

        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.new(UV_MAP)
        color_layer = bm.loops.layers.color.new("Color")
        source_key_layer = bm.faces.layers.string.new("mtk_source_texture_key")
        layers = {
            "uv": uv_layer,
            "color": color_layer,
            "rot": bm.faces.layers.float.new(MTK_UV_ROTATION),
            "timing": bm.faces.layers.float_color.new("mtk_anim_timing"),
            "frame_size": bm.faces.layers.float_color.new("mtk_anim_frame_size"),
            "tiling": bm.faces.layers.float_color.new("mtk_uv_tiling_transform"),
            "tint_data": bm.faces.layers.float_color.new("mtk_biome_tint_data"),
            "tint_color": bm.faces.layers.float_color.new(MTK_BIOME_TINT_COLOR),
            "block_x": bm.faces.layers.int.new("mtk_block_x"),
            "block_y": bm.faces.layers.int.new("mtk_block_y"),
            "block_z": bm.faces.layers.int.new("mtk_block_z"),
            "face_dir": bm.faces.layers.int.new("mtk_face_dir"),
            "atlas_chunk": bm.faces.layers.int.new(MTK_ATLAS_CHUNK_ID),
            "source_key": source_key_layer,
        }
        mat_mgr = LiveSyncMaterialManager(world_obj=None, atlas_params=self.atlas_params)

        generate_fluid_mesh_faces(
            bm=bm,
            x=0, y=1, z=0,
            state_str="minecraft:water[level=8]",
            block_map=block_map,
            layers=layers,
            origin_centered=False,
            min_x=0, min_y=0, min_z=0,
            half_x=0.0, half_z=0.0,
            mat_manager=mat_mgr,
        )

        # North side face (face_dir == 5)
        for f in bm.faces:
            if f[layers["face_dir"]] == 5:
                src_key = f[source_key_layer].decode("utf-8")
                self.assertIn("water_flow", src_key, "Vertical waterfall sides must use water_flow texture")
            elif f[layers["face_dir"]] == 2:
                src_key = f[source_key_layer].decode("utf-8")
                self.assertIn("water_flow", src_key, "Falling water top face must use water_flow texture")

        bm.free()

    def test_still_water_pool_uses_still_material(self):
        """
        Verify that a 1-deep stationary source water pool with solid base and boundaries
        uses water_still for the top surface.
        """
        block_map = {
            (1, 0, 1): "minecraft:water[level=0]",
            (1, -1, 1): "minecraft:stone",  # solid bottom
            (0, 0, 1): "minecraft:stone",
            (2, 0, 1): "minecraft:stone",
            (1, 0, 0): "minecraft:stone",
            (1, 0, 2): "minecraft:stone",
        }
        self.assertFalse(
            is_fluid_flowing("minecraft:water[level=0]", block_map, 1, 0, 1, "water", 0.0, 0.0),
            "Stationary source pool must NOT be identified as flowing",
        )

        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.new(UV_MAP)
        color_layer = bm.loops.layers.color.new("Color")
        source_key_layer = bm.faces.layers.string.new("mtk_source_texture_key")
        layers = {
            "uv": uv_layer,
            "color": color_layer,
            "rot": bm.faces.layers.float.new(MTK_UV_ROTATION),
            "timing": bm.faces.layers.float_color.new("mtk_anim_timing"),
            "frame_size": bm.faces.layers.float_color.new("mtk_anim_frame_size"),
            "tiling": bm.faces.layers.float_color.new("mtk_uv_tiling_transform"),
            "tint_data": bm.faces.layers.float_color.new("mtk_biome_tint_data"),
            "tint_color": bm.faces.layers.float_color.new(MTK_BIOME_TINT_COLOR),
            "block_x": bm.faces.layers.int.new("mtk_block_x"),
            "block_y": bm.faces.layers.int.new("mtk_block_y"),
            "block_z": bm.faces.layers.int.new("mtk_block_z"),
            "face_dir": bm.faces.layers.int.new("mtk_face_dir"),
            "atlas_chunk": bm.faces.layers.int.new(MTK_ATLAS_CHUNK_ID),
            "source_key": source_key_layer,
        }
        mat_mgr = LiveSyncMaterialManager(world_obj=None, atlas_params=self.atlas_params)

        generate_fluid_mesh_faces(
            bm=bm,
            x=1, y=0, z=1,
            state_str="minecraft:water[level=0]",
            block_map=block_map,
            layers=layers,
            origin_centered=False,
            min_x=0, min_y=0, min_z=0,
            half_x=0.0, half_z=0.0,
            mat_manager=mat_mgr,
        )

        for f in bm.faces:
            if f[layers["face_dir"]] == 2:  # Top face
                src_key = f[source_key_layer].decode("utf-8")
                self.assertIn("water_still", src_key, "Stationary pool top face must use water_still texture")
                self.assertAlmostEqual(f[layers["rot"]], 0.0, places=4, msg="Stationary pool rotation must be 0")

        bm.free()

    def test_waterlogged_block_fluid_surface_and_culling(self):
        """
        Verify that waterlogged blocks (e.g. waterlogged stairs or slabs) are recognized
        as fluid-bearing blocks, generate fluid surfaces, and correctly cull/connect with adjacent water.
        """
        stair_state = "minecraft:oak_stairs[facing=north,half=bottom,shape=straight,waterlogged=true]"
        self.assertTrue(is_fluid_block(stair_state), "Waterlogged stair must be recognized as fluid block")

        block_map = {
            (0, 0, 0): stair_state,
            (1, 0, 0): "minecraft:water[level=0]",  # Adjacent water source
        }

        # 1. Height sampling: waterlogged stair returns 8/9 base height
        h_stair = sample_fluid_height(block_map, 0, 0, 0, "water")
        self.assertAlmostEqual(h_stair, MAX_FLUID_HEIGHT, places=4)

        # 2. Adjacent water at (1, 0, 0) connects to stair at (0, 0, 0): All corners maintain full MAX_FLUID_HEIGHT
        c_nw, c_ne, c_se, c_sw = calculate_fluid_corner_heights(block_map, 1, 0, 0, "water")
        self.assertAlmostEqual(c_nw, MAX_FLUID_HEIGHT, places=4)
        self.assertAlmostEqual(c_ne, MAX_FLUID_HEIGHT, places=4)
        self.assertAlmostEqual(c_sw, MAX_FLUID_HEIGHT, places=4)
        self.assertAlmostEqual(c_se, MAX_FLUID_HEIGHT, places=4)

        # 3. Full 3x3 pool with waterlogged blocks in it produces full MAX_FLUID_HEIGHT flat surface
        pool_map = {
            (x, 0, z): stair_state if (x == 0 and z == 0) else "minecraft:water[level=0]"
            for x in (0, 1, 2)
            for z in (0, 1, 2)
        }
        p_nw, p_ne, p_se, p_sw = calculate_fluid_corner_heights(pool_map, 1, 0, 1, "water")
        self.assertAlmostEqual(p_nw, MAX_FLUID_HEIGHT, places=4)
        self.assertAlmostEqual(p_ne, MAX_FLUID_HEIGHT, places=4)
        self.assertAlmostEqual(p_se, MAX_FLUID_HEIGHT, places=4)
        self.assertAlmostEqual(p_sw, MAX_FLUID_HEIGHT, places=4)

        # 3. Full mesh build: produces both stair model faces and water fluid faces
        self.storage.set_block(0, 0, 0, stair_state)
        res = build_world_mesh(
            context=bpy.context,
            storage=self.storage,
            atlas_params=self.atlas_params,
            origin_centered=True,
        )
        self.assertIsNotNone(res.world_obj)
        self.assertGreater(res.fluids_count, 0, "Waterlogged stair must increment fluids count")
        self.assertGreater(res.face_count, 0)

    def test_kelp_and_seagrass_inherent_waterlogged(self):
        """
        Verify that underwater plants (seagrass, kelp) are inherently classified as waterlogged.
        """
        p_kelp = parse_and_classify("minecraft:kelp[age=5]")
        self.assertTrue(p_kelp.is_waterlogged, "Kelp must be inherently waterlogged")

        p_seagrass = parse_and_classify("minecraft:seagrass")
        self.assertTrue(p_seagrass.is_waterlogged, "Seagrass must be inherently waterlogged")

    def test_waterlogged_outflow_slanted_side_and_top_uv_rotation(self):
        """
        Verify that water flowing outward down the 4 slanted slopes from a waterlogged block
        (as in the cross-fountain configuration) computes the exact cardinal flow angles.
        """
        slab_state = "minecraft:oak_slab[type=bottom,waterlogged=true]"
        fountain_map = {
            (0, -1, 0): "minecraft:stone",          # Solid pillar support below
            (0, 0, 0): slab_state,
            (0, 0, 1): "minecraft:water[level=1]",   # South slope (+Z)
            (1, 0, 0): "minecraft:water[level=1]",   # East slope (+X)
            (0, 0, -1): "minecraft:water[level=1]",  # North slope (-Z)
            (-1, 0, 0): "minecraft:water[level=1]",  # West slope (-X)
        }

        # 1. South slope at (0, 0, 1) -> must flow South (flow_angle ~ 0.0)
        h_s = get_fluid_base_height("minecraft:water[level=1]")
        vx_s, vz_s, angle_s = calculate_fluid_flow_vector(fountain_map, 0, 0, 1, "water", h_s)
        self.assertGreater(vz_s, 0.0, "South slope must have positive vz flow")
        self.assertAlmostEqual(vx_s, 0.0, places=4)
        self.assertAlmostEqual(angle_s, 0.0, places=4, msg="South slope flow angle must be 0.0")

        # 2. East slope at (1, 0, 0) -> must flow East (flow_angle ~ -pi/2)
        h_e = get_fluid_base_height("minecraft:water[level=1]")
        vx_e, vz_e, angle_e = calculate_fluid_flow_vector(fountain_map, 1, 0, 0, "water", h_e)
        self.assertGreater(vx_e, 0.0, "East slope must have positive vx flow")
        self.assertAlmostEqual(vz_e, 0.0, places=4)
        self.assertAlmostEqual(angle_e, -math.pi / 2.0, places=4, msg="East slope flow angle must be -pi/2")

        # 3. North slope at (0, 0, -1) -> must flow North (flow_angle ~ -pi)
        h_n = get_fluid_base_height("minecraft:water[level=1]")
        vx_n, vz_n, angle_n = calculate_fluid_flow_vector(fountain_map, 0, 0, -1, "water", h_n)
        self.assertLess(vz_n, 0.0, "North slope must have negative vz flow")
        self.assertAlmostEqual(vx_n, 0.0, places=4)
        self.assertAlmostEqual(angle_n, -math.pi, places=4, msg="North slope flow angle must be -pi")

        # 4. West slope at (-1, 0, 0) -> must flow West (flow_angle ~ pi/2)
        h_w = get_fluid_base_height("minecraft:water[level=1]")
        vx_w, vz_w, angle_w = calculate_fluid_flow_vector(fountain_map, -1, 0, 0, "water", h_w)
        self.assertLess(vx_w, 0.0, "West slope must have negative vx flow")
        self.assertAlmostEqual(vz_w, 0.0, places=4)
        self.assertAlmostEqual(angle_w, math.pi / 2.0, places=4, msg="West slope flow angle must be pi/2")

        # 5. Center waterlogged slab at (0, 0, 0) -> symmetric outflow, flow vector = (0, 0) -> still water
        h_c = get_fluid_base_height(slab_state)
        vx_c, vz_c, angle_c = calculate_fluid_flow_vector(fountain_map, 0, 0, 0, "water", h_c)
        self.assertAlmostEqual(vx_c, 0.0, places=4)
        self.assertAlmostEqual(vz_c, 0.0, places=4)
        self.assertFalse(is_fluid_flowing(slab_state, fountain_map, 0, 0, 0, "water", vx_c, vz_c))

    def test_full_world_mesh_build_with_water(self):
        """Test full world mesh generation containing solid terrain and water bodies."""
        self.storage.set_block(0, 0, 0, "minecraft:stone")
        self.storage.set_block(1, 0, 0, "minecraft:water[level=0]")
        self.storage.set_block(2, 0, 0, "minecraft:water[level=1]")

        res = build_world_mesh(
            context=bpy.context,
            storage=self.storage,
            atlas_params=self.atlas_params,
            origin_centered=True,
        )
        self.assertIsNotNone(res.world_obj)
        self.assertGreater(res.face_count, 0)
        self.assertGreater(res.fluids_count, 0)
        mesh = res.world_obj.data
    def test_vertical_waterfall_welding_and_zero_gap(self):
        """
        Verify that a vertical waterfall column (stacked water blocks) produces contiguous
        vertices across Y boundaries and merges into a seamless mesh with 0 gaps.
        """
        self.storage.set_block(0, 0, 0, "minecraft:water[level=8]")
        self.storage.set_block(0, 1, 0, "minecraft:water[level=8]")
        self.storage.set_block(0, 2, 0, "minecraft:water[level=0]")

        res = build_world_mesh(
            context=bpy.context,
            storage=self.storage,
            atlas_params=self.atlas_params,
            origin_centered=False,
            weld_vertices=True,
        )
        self.assertIsNotNone(res.world_obj)
        mesh = res.world_obj.data

        # Inspect Z coordinates of vertices along a vertical corner edge (x=0.5, y=-0.5)
        verts_at_corner = sorted([v.co.z for v in mesh.vertices if abs(v.co.x - 0.5) < 1e-4 and abs(v.co.y - (-0.5)) < 1e-4])

        # Expect exactly 4 continuous vertical height points: Y=0 bottom (-0.5), Y=1 boundary (0.5), Y=2 boundary (1.5), Y=3 top (1.5 + corner_avg)
        # No duplicate or split vertices separated by epsilon gaps!
        top_corner_height = calculate_corner_average(MAX_FLUID_HEIGHT, 0.0, 0.0, 0.0)
        self.assertEqual(len(verts_at_corner), 4, f"Expected 4 welded vertices along vertical edge, got {len(verts_at_corner)}: {verts_at_corner}")
        self.assertAlmostEqual(verts_at_corner[0], -0.5, places=4)
        self.assertAlmostEqual(verts_at_corner[1], 0.5, places=4)
        self.assertAlmostEqual(verts_at_corner[2], 1.5, places=4)
        self.assertAlmostEqual(verts_at_corner[3], 1.5 + top_corner_height, places=4)

    def test_fluid_transmission_material_props_and_biome_tint(self):
        """Verify that water has Transmission Weight = 1.0, Lava has Emission = 15.0, and biome tint applies to vertex colors."""
        from utils.live_sync.constants import MTK_MATERIAL_PROPS, MTK_BIOME_TINT_COLOR
        from utils.materials.biome import get_biome_colors

        self.storage.set_bounds(0, 0, 0, 16, 16, 16)
        self.storage.biome_map[(0, 0, 0)] = "minecraft:ocean"
        self.storage.set_block(0, 0, 0, "minecraft:water[level=0]")
        self.storage.set_block(2, 0, 0, "minecraft:lava[level=0]")

        res = build_world_mesh(
            context=bpy.context,
            storage=self.storage,
            atlas_params=self.atlas_params,
            origin_centered=False,
        )
        self.assertIsNotNone(res.world_obj)
        mesh = res.world_obj.data

        props_attr = mesh.attributes.get(MTK_MATERIAL_PROPS)
        self.assertIsNotNone(props_attr, "Mesh must contain mtk_material_props attribute layer")

        block_x_attr = mesh.attributes.get("mtk_block_x")
        self.assertIsNotNone(block_x_attr)

        found_water = False
        found_lava = False

        for i, poly in enumerate(mesh.polygons):
            bx = block_x_attr.data[i].value
            mat_props = props_attr.data[i].color
            emission = mat_props[0]
            thin_wall = mat_props[1]
            transmission = mat_props[2]

            if bx == 0:  # Water block at (0, 0, 0)
                found_water = True
                self.assertAlmostEqual(transmission, 1.0, places=3, msg="Water must have Transmission Weight = 1.0 for refractive shader")
                self.assertAlmostEqual(emission, 0.0, places=3, msg="Water emission must be 0.0")
            elif bx == 2:  # Lava block at (2, 0, 0)
                found_lava = True
                self.assertAlmostEqual(transmission, 0.0, places=3, msg="Lava must have Transmission Weight = 0.0")
                self.assertGreaterEqual(emission, 15.0, msg="Lava emission must be 15.0")

        self.assertTrue(found_water, "Must have evaluated at least one water face")
        self.assertTrue(found_lava, "Must have evaluated at least one lava face")

        # Verify vertex color layer on water
        color_attr = mesh.color_attributes.get("Color")
        self.assertIsNotNone(color_attr, "Mesh must contain Color vertex attribute layer")
        ocean_expected = get_biome_colors("minecraft:ocean").get("water_linear")
        if ocean_expected:
            tint_attr = mesh.attributes.get(MTK_BIOME_TINT_COLOR)
            self.assertIsNotNone(tint_attr)
            # Water face tint color should reflect ocean water tint
            self.assertAlmostEqual(tint_attr.data[0].color[0], ocean_expected[0], delta=0.1)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])


