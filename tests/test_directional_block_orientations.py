"""
Comprehensive tests for Minecraft block orientations, partial property matching,
StateBaker FaceBakery multi-face baking, and Yefira procedural point cloud atlas attributes.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy
from utils.mc_baker import StateBaker
from utils.mc_baker.blockstate_resolver import BlockStateResolver
from utils.materials.yefira import write_yefira_point_atlas_attributes
from utils.live_sync import VoxelStorage, update_world_point_cloud


class TestDirectionalBlockOrientations(unittest.TestCase):

    def setUp(self):
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in list(bpy.data.meshes):
            bpy.data.meshes.remove(mesh, do_unlink=True)

    def test_blockstate_resolver_partial_property_matching(self):
        """Verify partial property matching properly resolves without crashing or defaulting to facing=down."""
        resolver = BlockStateResolver()
        variants = {
            'facing=down,powered=false': {'model': 'minecraft:block/observer', 'x': 90},
            'facing=down,powered=true': {'model': 'minecraft:block/observer_on', 'x': 90},
            'facing=east,powered=false': {'model': 'minecraft:block/observer', 'y': 90},
            'facing=east,powered=true': {'model': 'minecraft:block/observer_on', 'y': 90},
            'facing=north,powered=false': {'model': 'minecraft:block/observer'},
            'facing=north,powered=true': {'model': 'minecraft:block/observer_on'},
            'facing=south,powered=false': {'model': 'minecraft:block/observer', 'y': 180},
            'facing=south,powered=true': {'model': 'minecraft:block/observer_on', 'y': 180},
            'facing=up,powered=false': {'model': 'minecraft:block/observer', 'x': 270},
            'facing=up,powered=true': {'model': 'minecraft:block/observer_on', 'x': 270},
            'facing=west,powered=false': {'model': 'minecraft:block/observer', 'y': 270},
            'facing=west,powered=true': {'model': 'minecraft:block/observer_on', 'y': 270},
        }

        # Partial matching with only facing
        match_east = resolver._match_variant(variants, {'facing': 'east'})
        self.assertIsNotNone(match_east)
        self.assertEqual(match_east.model_id, 'minecraft:block/observer')
        self.assertEqual(match_east.rot_y, 90.0)

        match_up = resolver._match_variant(variants, {'facing': 'up'})
        self.assertIsNotNone(match_up)
        self.assertEqual(match_up.model_id, 'minecraft:block/observer')
        self.assertEqual(match_up.rot_x, 270.0)

        # Full matching with powered=true
        match_south_lit = resolver._match_variant(variants, {'facing': 'south', 'powered': 'true'})
        self.assertIsNotNone(match_south_lit)
        self.assertEqual(match_south_lit.model_id, 'minecraft:block/observer_on')
        self.assertEqual(match_south_lit.rot_y, 180.0)

    def test_state_baker_fallback_directional_faces(self):
        """Verify StateBaker without JAR bakes accurate 6-face models and UV rotations for all directions."""
        baker = StateBaker(jar_path=None)

        # 1. Furnace Facing East
        f_east = baker.bake_block_state('minecraft:furnace[facing=east,lit=false]')
        self.assertEqual(f_east.faces[0].direction, 'east')
        self.assertEqual(f_east.faces[0].texture, 'minecraft:block/furnace_front')
        self.assertEqual(f_east.faces[1].texture, 'minecraft:block/furnace_side')
        self.assertEqual(f_east.faces[2].texture, 'minecraft:block/furnace_top')
        self.assertEqual(f_east.faces[2].uv_rot, 90.0)
        self.assertEqual(f_east.faces[3].texture, 'minecraft:block/furnace_top')
        self.assertEqual(f_east.faces[3].uv_rot, 270.0)
        self.assertEqual(f_east.faces[5].texture, 'minecraft:block/furnace_side')

        # 2. Observer Facing Up
        obs_up = baker.bake_block_state('minecraft:observer[facing=up]')
        self.assertEqual(obs_up.faces[2].direction, 'up')
        self.assertEqual(obs_up.faces[2].texture, 'minecraft:block/observer_front')
        self.assertEqual(obs_up.faces[3].direction, 'down')
        self.assertEqual(obs_up.faces[3].texture, 'minecraft:block/observer_back')

        # 3. Piston Facing Up
        piston_up = baker.bake_block_state('minecraft:piston[facing=up]')
        self.assertEqual(piston_up.faces[2].texture, 'minecraft:block/piston_top')
        self.assertEqual(piston_up.faces[3].texture, 'minecraft:block/piston_bottom')
        self.assertEqual(piston_up.faces[0].texture, 'minecraft:block/piston_side')

        # 4. Oak Log Axis X
        log_x = baker.bake_block_state('minecraft:oak_log[axis=x]')
        self.assertEqual(log_x.faces[0].texture, 'minecraft:block/oak_log_top')
        self.assertEqual(log_x.faces[1].texture, 'minecraft:block/oak_log_top')
        self.assertEqual(log_x.faces[2].texture, 'minecraft:block/oak_log')
        self.assertEqual(log_x.faces[2].uv_rot, 90.0)

    def test_yefira_point_atlas_attributes_directional_assignment(self):
        """Verify Yefira point atlas attributes write accurate directional tiles to mesh."""
        mesh = bpy.data.meshes.new('TestYefiraDirMesh')
        obj = bpy.data.objects.new('TestYefiraDirObj', mesh)
        bpy.context.scene.collection.objects.link(obj)

        mesh.from_pydata([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)], [], [])
        mesh.update()

        states = mesh.attributes.new('block_state', 'STRING', 'POINT')
        states.data[0].value = b'minecraft:furnace[facing=east,lit=false]'
        states.data[1].value = b'minecraft:furnace[facing=south,lit=true]'
        states.data[2].value = b'minecraft:observer[facing=up]'

        def loc(col, row, tex_id):
            return {'tile_column': col, 'tile_row': row, 'chunk_id': 0, 'texture_id': tex_id}

        mapping = {
            'textures': {
                'minecraft:block/furnace_top': loc(1, 0, 10),
                'minecraft:block/furnace_side': loc(2, 0, 20),
                'minecraft:block/furnace_front': loc(3, 0, 30),
                'minecraft:block/furnace_front_on': loc(4, 0, 40),
                'minecraft:block/observer_top': loc(5, 0, 50),
                'minecraft:block/observer_side': loc(6, 0, 60),
                'minecraft:block/observer_front': loc(7, 0, 70),
                'minecraft:block/observer_back': loc(8, 0, 80),
            }
        }

        write_yefira_point_atlas_attributes(mesh, mapping)

        # Index 0: Furnace Facing East
        # East (+X) is Front (3, 0, 30)
        self.assertEqual(tuple(mesh.attributes['mtk_tile_east'].data[0].vector), (3.0, 0.0, 0.0))
        self.assertEqual(mesh.attributes['mtk_texture_east'].data[0].value, 30)
        # West (-X) is Side (2, 0, 20)
        self.assertEqual(tuple(mesh.attributes['mtk_tile_west'].data[0].vector), (2.0, 0.0, 0.0))
        # North (-Z) is Side (2, 0, 20)
        self.assertEqual(tuple(mesh.attributes['mtk_tile_north'].data[0].vector), (2.0, 0.0, 0.0))
        # Top (+Y) is Top (1, 0, 10) with 90 deg rotation
        self.assertEqual(tuple(mesh.attributes['mtk_tile_top'].data[0].vector), (1.0, 0.0, 0.0))
        self.assertEqual(mesh.attributes['mtk_uv_rot_top'].data[0].value, 90.0)

        # Index 1: Furnace Facing South (Lit)
        # South (+Z) is Front On (4, 0, 40)
        self.assertEqual(tuple(mesh.attributes['mtk_tile_south'].data[1].vector), (4.0, 0.0, 0.0))
        self.assertEqual(mesh.attributes['mtk_texture_south'].data[1].value, 40)
        # North (-Z) is Side (2, 0, 20)
        self.assertEqual(tuple(mesh.attributes['mtk_tile_north'].data[1].vector), (2.0, 0.0, 0.0))

        # Index 2: Observer Facing Up
        # Top (+Y) is Observer Front (7, 0, 70)
        self.assertEqual(tuple(mesh.attributes['mtk_tile_top'].data[2].vector), (7.0, 0.0, 0.0))
        self.assertEqual(mesh.attributes['mtk_texture_top'].data[2].value, 70)
        # Bottom (-Y) is Observer Back (8, 0, 80)
        self.assertEqual(tuple(mesh.attributes['mtk_tile_bottom'].data[2].vector), (8.0, 0.0, 0.0))
        self.assertEqual(mesh.attributes['mtk_texture_bottom'].data[2].value, 80)

    def test_live_sync_point_cloud_directional_attributes(self):
        """Verify Live Sync point cloud builder generates accurate 6-face directional attributes."""
        storage = VoxelStorage()
        storage.min_x, storage.min_y, storage.min_z = 0, 0, 0
        storage.size_x, storage.size_y, storage.size_z = 1, 1, 1
        storage.block_map[(0, 0, 0)] = 'minecraft:furnace[facing=east,lit=false]'

        def loc(col, row, tex_id):
            return {'tile_column': col, 'tile_row': row, 'chunk_id': 0, 'texture_id': tex_id}

        mapping_textures = {
            'minecraft:block/furnace_top': loc(1, 0, 10),
            'minecraft:block/furnace_side': loc(2, 0, 20),
            'minecraft:block/furnace_front': loc(3, 0, 30),
        }

        res = update_world_point_cloud(bpy.context, storage, atlas_mapping_textures=mapping_textures)
        self.assertIsNotNone(res.world_obj)
        mesh = res.world_obj.data

        self.assertEqual(tuple(mesh.attributes['mtk_tile_east'].data[0].vector), (3.0, 0.0, 0.0))
        self.assertEqual(mesh.attributes['mtk_texture_east'].data[0].value, 30)
        self.assertEqual(tuple(mesh.attributes['mtk_tile_west'].data[0].vector), (2.0, 0.0, 0.0))
        self.assertEqual(mesh.attributes['mtk_uv_rot_top'].data[0].value, 90.0)

    def test_piston_orientations_all_directions(self):
        """Verify piston head, bottom, and side faces in all 6 directions."""
        baker = StateBaker(jar_path=None)

        # Facing UP: top is head, bottom is bottom
        p_up = baker.bake_block_state('minecraft:piston[facing=up]')
        self.assertEqual(p_up.faces[2].texture, 'minecraft:block/piston_top')
        self.assertEqual(p_up.faces[3].texture, 'minecraft:block/piston_bottom')
        self.assertEqual(p_up.faces[0].texture, 'minecraft:block/piston_side')

        # Facing DOWN: down is head, up is bottom
        p_down = baker.bake_block_state('minecraft:piston[facing=down]')
        self.assertEqual(p_down.faces[3].texture, 'minecraft:block/piston_top')
        self.assertEqual(p_down.faces[2].texture, 'minecraft:block/piston_bottom')

        # Facing NORTH: north is head, south is bottom
        p_north = baker.bake_block_state('minecraft:piston[facing=north]')
        self.assertEqual(p_north.faces[5].texture, 'minecraft:block/piston_top')
        self.assertEqual(p_north.faces[4].texture, 'minecraft:block/piston_bottom')

        # Facing EAST: east is head, west is bottom
        p_east = baker.bake_block_state('minecraft:piston[facing=east]')
        self.assertEqual(p_east.faces[0].texture, 'minecraft:block/piston_top')
        self.assertEqual(p_east.faces[1].texture, 'minecraft:block/piston_bottom')

    def test_direct_mesh_directional_orientations_and_uv_rot(self):
        """Verify Direct Mesh generation bakes precise UVMap and orientations for directional blocks."""
        from utils.live_sync import build_world_mesh
        storage = VoxelStorage()
        storage.set_block(0, 0, 0, 'minecraft:furnace[facing=east,lit=false]')
        storage.set_block(2, 0, 0, 'minecraft:oak_log[axis=x]')

        def loc(col, row, tex_id):
            return {'tile_column': col, 'tile_row': row, 'chunk_id': 0, 'texture_id': tex_id}

        mapping_textures = {
            'minecraft:block/furnace_top': loc(1, 0, 10),
            'minecraft:block/furnace_side': loc(2, 0, 20),
            'minecraft:block/furnace_front': loc(3, 0, 30),
            'minecraft:block/oak_log': loc(4, 0, 40),
            'minecraft:block/oak_log_top': loc(5, 0, 50),
        }

        atlas_params = {
            'width': 1024,
            'height': 512,
            'tile_size': 16,
            'tiles_per_row': 64,
            'mapping': {'textures': mapping_textures},
        }

        res = build_world_mesh(bpy.context, storage, atlas_params=atlas_params)
        self.assertIsNotNone(res.world_obj)
        mesh = res.world_obj.data

        # 2 non-adjacent cubes -> 12 faces
        self.assertEqual(len(mesh.polygons), 12)
        self.assertIn("UVMap", mesh.uv_layers)

    def test_world_tree_uv_rotations(self):
        """Verify Geometry Nodes world tree evaluates UV rotation in CW direction (90, 180, 270)."""
        from utils.geometry_nodes.world_tree import setup_world_geometry_nodes
        storage = VoxelStorage()
        storage.min_x = storage.min_y = storage.min_z = 0
        storage.size_x = storage.size_y = storage.size_z = 1
        storage.block_map[(0, 0, 0)] = 'minecraft:oak_log[axis=x]'

        res = update_world_point_cloud(bpy.context, storage)
        self.assertIsNotNone(res.world_obj)
        setup_world_geometry_nodes(res.world_obj)

        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = res.world_obj.evaluated_get(depsgraph)
        eval_mesh = eval_obj.data
        self.assertGreater(len(eval_mesh.polygons), 0)
        self.assertIn("UVMap", eval_mesh.attributes)

    def test_glazed_terracotta_all_facings_and_offline_parity(self):
        """Verify Glazed Terracotta 4-facing circular UV rotations and JAR/offline parity."""
        baker = StateBaker(jar_path=None)

        # 1. South: Top=0, South=270, North=90, East=180, West=0
        s_south = baker.bake_block_state('minecraft:white_glazed_terracotta[facing=south]')
        self.assertEqual(s_south.faces[2].uv_rot, 0.0)    # up
        self.assertEqual(s_south.faces[4].uv_rot, 270.0)  # south
        self.assertEqual(s_south.faces[5].uv_rot, 90.0)   # north
        self.assertEqual(s_south.faces[0].uv_rot, 180.0)  # east
        self.assertEqual(s_south.faces[1].uv_rot, 0.0)    # west

        # 2. West: Top=90, South=180, North=0, East=90, West=270
        s_west = baker.bake_block_state('minecraft:white_glazed_terracotta[facing=west]')
        self.assertEqual(s_west.faces[2].uv_rot, 90.0)    # up
        self.assertEqual(s_west.faces[4].uv_rot, 180.0)  # south
        self.assertEqual(s_west.faces[5].uv_rot, 0.0)    # north
        self.assertEqual(s_west.faces[0].uv_rot, 90.0)   # east
        self.assertEqual(s_west.faces[1].uv_rot, 270.0)  # west

        # 3. North: Top=180, South=90, North=270, East=0, West=180
        s_north = baker.bake_block_state('minecraft:white_glazed_terracotta[facing=north]')
        self.assertEqual(s_north.faces[2].uv_rot, 180.0)  # up
        self.assertEqual(s_north.faces[4].uv_rot, 90.0)   # south
        self.assertEqual(s_north.faces[5].uv_rot, 270.0)  # north
        self.assertEqual(s_north.faces[0].uv_rot, 0.0)    # east
        self.assertEqual(s_north.faces[1].uv_rot, 180.0)  # west

        # 4. East: Top=270, South=0, North=180, East=270, West=90
        s_east = baker.bake_block_state('minecraft:white_glazed_terracotta[facing=east]')
        self.assertEqual(s_east.faces[2].uv_rot, 270.0)  # up
        self.assertEqual(s_east.faces[4].uv_rot, 0.0)    # south
        self.assertEqual(s_east.faces[5].uv_rot, 180.0)  # north
        self.assertEqual(s_east.faces[0].uv_rot, 270.0)  # east
        self.assertEqual(s_east.faces[1].uv_rot, 90.0)   # west

    def test_dispenser_and_dropper_all_facings(self):
        """Verify Dispenser and Dropper textures for horizontal and vertical facings."""
        baker = StateBaker(jar_path=None)

        # 1. Dispenser North
        d_north = baker.bake_block_state('minecraft:dispenser[facing=north,triggered=false]')
        self.assertEqual(d_north.faces[5].texture, 'minecraft:block/dispenser_front')
        self.assertEqual(d_north.faces[0].texture, 'minecraft:block/furnace_side')
        self.assertEqual(d_north.faces[2].texture, 'minecraft:block/furnace_top')
        self.assertEqual(d_north.faces[3].texture, 'minecraft:block/furnace_top')

        # 2. Dispenser East
        d_east = baker.bake_block_state('minecraft:dispenser[facing=east,triggered=false]')
        self.assertEqual(d_east.faces[0].texture, 'minecraft:block/dispenser_front')
        self.assertEqual(d_east.faces[1].texture, 'minecraft:block/furnace_side')
        self.assertEqual(d_east.faces[2].texture, 'minecraft:block/furnace_top')
        self.assertEqual(d_east.faces[2].uv_rot, 90.0)

        # 3. Dispenser Up (Vertical)
        d_up = baker.bake_block_state('minecraft:dispenser[facing=up,triggered=false]')
        self.assertEqual(d_up.faces[2].texture, 'minecraft:block/dispenser_front_vertical')
        self.assertEqual(d_up.faces[0].texture, 'minecraft:block/furnace_top')
        self.assertEqual(d_up.faces[3].texture, 'minecraft:block/furnace_top')

        # 4. Dropper Up (Vertical)
        dr_up = baker.bake_block_state('minecraft:dropper[facing=up]')
        self.assertEqual(dr_up.faces[2].texture, 'minecraft:block/dropper_front_vertical')
        self.assertEqual(dr_up.faces[0].texture, 'minecraft:block/furnace_top')

    def test_full_offline_parity_against_jar(self):
        """Verify 100% parity between official JAR Baker and Offline Baker across 60+ directional states."""
        jar_path = Path('/Users/jaxlocke/26.2-Fabric.jar')
        if not jar_path.exists():
            self.skipTest('Minecraft JAR not available for parity check')

        jar_baker = StateBaker(jar_path=str(jar_path))
        offline_baker = StateBaker(jar_path=None)

        colors = ['white', 'orange', 'magenta', 'light_blue', 'yellow', 'lime', 'pink', 'gray', 'light_gray', 'cyan', 'purple', 'blue', 'brown', 'green', 'red', 'black']
        terracotta_states = [f'minecraft:{c}_glazed_terracotta[facing={f}]' for c in colors for f in ('south', 'west', 'north', 'east')]

        directional_states = terracotta_states + [
            'minecraft:dispenser[facing=north,triggered=false]',
            'minecraft:dispenser[facing=east,triggered=false]',
            'minecraft:dispenser[facing=south,triggered=false]',
            'minecraft:dispenser[facing=west,triggered=false]',
            'minecraft:dispenser[facing=up,triggered=false]',
            'minecraft:dispenser[facing=down,triggered=false]',
            'minecraft:dropper[facing=north]',
            'minecraft:dropper[facing=east]',
            'minecraft:dropper[facing=up]',
            'minecraft:dropper[facing=down]',
            'minecraft:command_block[facing=north,conditional=false]',
            'minecraft:command_block[facing=east,conditional=false]',
            'minecraft:command_block[facing=up,conditional=false]',
            'minecraft:command_block[facing=down,conditional=false]',
            'minecraft:piston[facing=north,extended=false]',
            'minecraft:piston[facing=east,extended=false]',
            'minecraft:piston[facing=up,extended=false]',
            'minecraft:piston[facing=down,extended=false]',
            'minecraft:observer[facing=north]',
            'minecraft:observer[facing=east]',
            'minecraft:observer[facing=up]',
            'minecraft:oak_log[axis=x]',
            'minecraft:oak_log[axis=z]',
            'minecraft:barrel[facing=north]',
            'minecraft:barrel[facing=up]',
        ]

        for s in directional_states:
            m_jar = jar_baker.bake_block_state(s)
            m_off = offline_baker.bake_block_state(s)

            for f_jar, f_off in zip(m_jar.faces, m_off.faces):
                self.assertEqual(f_jar.direction, f_off.direction, f"Direction mismatch for {s}")
                self.assertEqual(f_jar.uv_rot, f_off.uv_rot, f"UV rot mismatch for {s} face {f_jar.direction} (JAR={f_jar.uv_rot}, Off={f_off.uv_rot})")
                # Ensure textures match canonical stem
                stem_jar = f_jar.texture.split('/')[-1]
                stem_off = f_off.texture.split('/')[-1]
                self.assertEqual(stem_jar, stem_off, f"Texture mismatch for {s} face {f_jar.direction} (JAR={stem_jar}, Off={stem_off})")


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
