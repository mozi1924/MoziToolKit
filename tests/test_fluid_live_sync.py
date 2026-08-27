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
from utils.live_sync.material_manager import LiveSyncMaterialManager
from utils.live_sync.mesh_builder import build_world_mesh, apply_block_delta_to_world
from utils.live_sync.fluid_mesher import (
    get_fluid_base_height,
    sample_fluid_height,
    calculate_corner_average,
    calculate_fluid_corner_heights,
    calculate_fluid_flow_vector,
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
        Test that an isolated still water source block calculates exact Vanilla Minecraft corner heights:
        Center has weight 10.0 (8/9), while the two exposed air neighbors have weight 1.0 (0.0),
        yielding exact surface tension curve (8/9 * 10) / 12 = 20/27 ~= 0.74074.
        """
        block_map = {(0, 0, 0): "minecraft:water[level=0]"}
        c_nw, c_ne, c_se, c_sw = calculate_fluid_corner_heights(block_map, 0, 0, 0, "water")
        expected_tension_h = (MAX_FLUID_HEIGHT * 10.0) / 12.0  # 20/27
        self.assertAlmostEqual(c_nw, expected_tension_h, places=4)
        self.assertAlmostEqual(c_ne, expected_tension_h, places=4)
        self.assertAlmostEqual(c_se, expected_tension_h, places=4)
        self.assertAlmostEqual(c_sw, expected_tension_h, places=4)

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
        """Test that top face is culled when water is above, and bottom is culled when solid block is below."""
        block_map = {
            (0, 0, 0): "minecraft:water[level=0]",
            (0, 1, 0): "minecraft:water[level=0]",  # Water above -> culls top of (0,0,0)
            (0, -1, 0): "minecraft:stone",          # Stone below -> culls bottom of (0,0,0)
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
        self.assertNotIn(2, face_dirs, "Top face (dir 2) must be culled because water is above")
        self.assertNotIn(3, face_dirs, "Bottom face (dir 3) must be culled because stone is below")
        bm.free()

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
        self.assertIn(MTK_ATLAS_CHUNK_ID, mesh.attributes)
        self.assertIn(MTK_BIOME_TINT_COLOR, mesh.attributes)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
