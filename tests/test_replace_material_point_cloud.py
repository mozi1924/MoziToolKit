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

        # Clear scene data-blocks
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in list(bpy.data.meshes):
            bpy.data.meshes.remove(mesh, do_unlink=True)
        for mat in list(bpy.data.materials):
            bpy.data.materials.remove(mat, do_unlink=True)
        for tree in list(bpy.data.node_groups):
            bpy.data.node_groups.remove(tree, do_unlink=True)

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

        # Verify Geometry Nodes modifier Material Dispatcher or Set Material node
        mat_dispatcher_nodes = [n for n in self.mod.node_group.nodes if n.name == 'Material Dispatcher']
        set_mat_nodes = [n for n in self.mod.node_group.nodes if n.type == 'SET_MATERIAL']
        self.assertTrue(len(mat_dispatcher_nodes) > 0 or len(set_mat_nodes) > 0)

        # Yefira's evaluated shader path is a separate material variant.
        self.assertEqual(assigned_mat.get("mtk:atlas_uv_source"), "UVMap")
        uv_source = next(n for n in assigned_mat.node_tree.nodes if n.name == "Atlas UV Attribute (UVMap)")
        self.assertEqual(uv_source.attribute_name, "UVMap")
        self.assertIn("mtk_tile_top", self.mesh.attributes)
        self.assertIn("mtk_texture_top", self.mesh.attributes)
        self.assertIn("mtk_is_opaque", self.mesh.attributes)
        self.assertNotIn("mtk:atlas_mapping", self.mesh)

    def test_generated_model_uses_texture_table_when_faces_are_null(self):
        """Stained glass has a generated model but a valid Atlas texture."""
        from utils.materials.yefira import write_yefira_point_atlas_attributes as _write_yefira_point_atlas_attributes

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
        from utils.materials.yefira import write_yefira_point_atlas_attributes as _write_yefira_point_atlas_attributes

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

    def test_opacity_attributes_written(self):
        """Verify that mtk_is_opaque and is_opaque attributes are populated for opaque vs transparent materials."""
        from utils.materials.yefira import write_yefira_point_atlas_attributes as _write_yefira_point_atlas_attributes

        mapping = {
            "materials": [
                {
                    "name": "stone",
                    "material_id": 1,
                    "is_opaque": True,
                    "faces": {face: {"is_opaque": True} for face in ("+X", "-X", "+Y", "-Y", "+Z", "-Z")},
                },
                {
                    "name": "glass",
                    "material_id": 2,
                    "is_opaque": False,
                    "faces": {face: {"is_opaque": False} for face in ("+X", "-X", "+Y", "-Y", "+Z", "-Z")},
                },
            ]
        }
        self.mesh.attributes["block_state"].data[0].value = b"minecraft:stone"
        self.mesh.attributes["block_state"].data[1].value = b"minecraft:glass"
        _write_yefira_point_atlas_attributes(self.mesh, mapping)

        self.assertIn("mtk_is_opaque", self.mesh.attributes)
        self.assertIn("is_opaque", self.mesh.attributes)
        self.assertEqual(self.mesh.attributes["mtk_is_opaque"].data[0].value, 1)
        self.assertEqual(self.mesh.attributes["mtk_is_opaque"].data[1].value, 0)
        self.assertEqual(self.mesh.attributes["is_opaque"].data[0].value, 1)
        self.assertEqual(self.mesh.attributes["is_opaque"].data[1].value, 0)

    def test_yefira_object_detection(self):
        """Verify is_yefira_object and has_yefira_objects correctly distinguish Yefira from normal meshes."""
        from utils.materials.yefira import is_yefira_object, has_yefira_objects

        # 1. Yefira object is recognized
        self.assertTrue(is_yefira_object(self.obj))
        self.assertTrue(has_yefira_objects([self.obj]))

        # 2. Standard polygon mesh is not recognized as Yefira
        cube_mesh = bpy.data.meshes.new("Standard_Cube")
        cube_obj = bpy.data.objects.new("Standard_Cube", cube_mesh)
        self.assertFalse(is_yefira_object(cube_obj))
        self.assertFalse(has_yefira_objects([cube_obj]))

        # 3. Mixed list returns True
        self.assertTrue(has_yefira_objects([cube_obj, self.obj]))

        # 4. None / non-mesh objects return False
        self.assertFalse(is_yefira_object(None))
        camera = bpy.data.objects.new("Camera", None)
        self.assertFalse(is_yefira_object(camera))

    def test_animated_texture_column_address_and_timing_attributes(self):
        """Verify animation textures (command_block, sea_lantern) resolve to px // fw and write anim attributes."""
        from utils.materials.yefira import write_yefira_point_atlas_attributes, setup_yefira_point_cloud_attributes

        mock_mapping = {
            "format_version": 11,
            "chunks": [
                {
                    "chunk_id": 0,
                    "kind": "static",
                    "width": 4096,
                    "height": 80,
                    "tile_size": 16,
                    "tiles_per_row": 256,
                },
                {
                    "chunk_id": 1,
                    "kind": "animation",
                    "width": 896,
                    "height": 1024,
                    "tile_size": 16,
                    "tiles_per_row": 56,
                },
            ],
            "textures": {
                "minecraft:block/command_block_front": {
                    "texture_key": "minecraft:block/command_block_front",
                    "chunk_id": 1,
                    "texture_id": 30,
                    "kind": "animation",
                    "pixel_x": 320,
                    "pixel_y": 0,
                    "frame_width": 16,
                    "frame_height": 16,
                    "frame_count": 4,
                    "frametime": 2,
                    "interpolate": True,
                },
                "minecraft:block/command_block_side": {
                    "texture_key": "minecraft:block/command_block_side",
                    "chunk_id": 1,
                    "texture_id": 31,
                    "kind": "animation",
                    "pixel_x": 336,
                    "pixel_y": 0,
                    "frame_width": 16,
                    "frame_height": 16,
                    "frame_count": 4,
                    "frametime": 2,
                    "interpolate": True,
                },
                "minecraft:block/command_block_back": {
                    "texture_key": "minecraft:block/command_block_back",
                    "chunk_id": 1,
                    "texture_id": 32,
                    "kind": "animation",
                    "pixel_x": 352,
                    "pixel_y": 0,
                    "frame_width": 16,
                    "frame_height": 16,
                    "frame_count": 4,
                    "frametime": 2,
                    "interpolate": True,
                },
                "minecraft:block/sea_lantern": {
                    "texture_key": "minecraft:block/sea_lantern",
                    "chunk_id": 1,
                    "texture_id": 38,
                    "kind": "animation",
                    "pixel_x": 624,
                    "pixel_y": 0,
                    "frame_width": 16,
                    "frame_height": 16,
                    "frame_count": 5,
                    "frametime": 5,
                    "interpolate": False,
                },
            },
        }

        self.mesh.attributes["block_state"].data[0].value = b"minecraft:command_block"
        self.mesh.attributes["block_state"].data[1].value = b"minecraft:sea_lantern"

        setup_yefira_point_cloud_attributes(
            mesh=self.mesh,
            mapping_data=mock_mapping,
        )

        # 1. Verify global anim atlas metadata attributes
        self.assertIn("mtk_anim_atlas_width", self.mesh.attributes)
        self.assertIn("mtk_anim_atlas_height", self.mesh.attributes)
        self.assertIn("mtk_anim_frame_width", self.mesh.attributes)
        self.assertIn("mtk_anim_frame_height", self.mesh.attributes)
        self.assertEqual(self.mesh.attributes["mtk_anim_atlas_width"].data[0].value, 896.0)
        self.assertEqual(self.mesh.attributes["mtk_anim_atlas_height"].data[0].value, 1024.0)

        # 2. Verify command_block (point 0):
        # East (+X) is side: pixel_x=336 -> col = 336 // 16 = 21
        # Top (+Y) is front: pixel_x=320 -> col = 320 // 16 = 20
        # Bottom (-Y) is back: pixel_x=352 -> col = 352 // 16 = 22
        east_tile = tuple(self.mesh.attributes["mtk_tile_east"].data[0].vector)
        top_tile = tuple(self.mesh.attributes["mtk_tile_top"].data[0].vector)
        bottom_tile = tuple(self.mesh.attributes["mtk_tile_bottom"].data[0].vector)
        self.assertEqual(east_tile, (21.0, 0.0, 0.0))
        self.assertEqual(top_tile, (20.0, 0.0, 0.0))
        self.assertEqual(bottom_tile, (22.0, 0.0, 0.0))
        self.assertEqual(self.mesh.attributes["mtk_chunk_east"].data[0].value, 1)

        # Verify anim timing & frame size on command_block
        anim_timing = tuple(self.mesh.attributes["mtk_anim_timing_east"].data[0].color)
        self.assertEqual(anim_timing, (4.0, 2.0, 1.0, 0.0))
        anim_frame_size = tuple(self.mesh.attributes["mtk_anim_frame_size_east"].data[0].color)
        self.assertEqual(anim_frame_size, (16.0, 16.0, 0.0, 0.0))

        # 3. Verify sea_lantern (point 1):
        # pixel_x=624 -> col = 624 // 16 = 39
        sea_east_tile = tuple(self.mesh.attributes["mtk_tile_east"].data[1].vector)
        self.assertEqual(sea_east_tile, (39.0, 0.0, 0.0))
        self.assertEqual(self.mesh.attributes["mtk_chunk_east"].data[1].value, 1)

        sea_anim_timing = tuple(self.mesh.attributes["mtk_anim_timing_east"].data[1].color)
        self.assertEqual(sea_anim_timing, (5.0, 5.0, 0.0, 0.0))

    def test_block_state_and_face_addressing_enhancements(self):
        """Verify lit, snowy, honey_level, charges, axis, mushrooms, glazed terracotta, and emissive block rules."""
        from utils.materials.yefira import write_yefira_point_atlas_attributes

        mock_mapping = {
            "textures": {
                "minecraft:block/furnace_front": {"chunk_id": 0, "texture_id": 1, "tile_column": 1, "tile_row": 0},
                "minecraft:block/furnace_front_on": {"chunk_id": 0, "texture_id": 2, "tile_column": 2, "tile_row": 0},
                "minecraft:block/furnace_side": {"chunk_id": 0, "texture_id": 3, "tile_column": 3, "tile_row": 0},
                "minecraft:block/furnace_top": {"chunk_id": 0, "texture_id": 4, "tile_column": 4, "tile_row": 0},
                "minecraft:block/redstone_lamp": {"chunk_id": 0, "texture_id": 5, "tile_column": 5, "tile_row": 0},
                "minecraft:block/redstone_lamp_on": {"chunk_id": 0, "texture_id": 6, "tile_column": 6, "tile_row": 0},
                "minecraft:block/glowstone": {"chunk_id": 0, "texture_id": 7, "tile_column": 7, "tile_row": 0},
                "minecraft:block/grass_block_top": {"chunk_id": 0, "texture_id": 8, "tile_column": 8, "tile_row": 0, "default_tint_weight": 1.0},
                "minecraft:block/grass_block_side": {"chunk_id": 0, "texture_id": 9, "tile_column": 9, "tile_row": 0},
                "minecraft:block/grass_block_snow": {"chunk_id": 0, "texture_id": 10, "tile_column": 10, "tile_row": 0},
                "minecraft:block/dirt": {"chunk_id": 0, "texture_id": 11, "tile_column": 11, "tile_row": 0},
                "minecraft:block/beehive_front": {"chunk_id": 0, "texture_id": 12, "tile_column": 12, "tile_row": 0},
                "minecraft:block/beehive_front_honey": {"chunk_id": 0, "texture_id": 13, "tile_column": 13, "tile_row": 0},
                "minecraft:block/beehive_side": {"chunk_id": 0, "texture_id": 14, "tile_column": 14, "tile_row": 0},
                "minecraft:block/beehive_top": {"chunk_id": 0, "texture_id": 15, "tile_column": 15, "tile_row": 0},
                "minecraft:block/respawn_anchor_top_off": {"chunk_id": 0, "texture_id": 16, "tile_column": 16, "tile_row": 0},
                "minecraft:block/respawn_anchor_top": {"chunk_id": 0, "texture_id": 17, "tile_column": 17, "tile_row": 0},
                "minecraft:block/respawn_anchor_side0": {"chunk_id": 0, "texture_id": 18, "tile_column": 18, "tile_row": 0},
                "minecraft:block/respawn_anchor_side4": {"chunk_id": 0, "texture_id": 19, "tile_column": 19, "tile_row": 0},
                "minecraft:block/respawn_anchor_bottom": {"chunk_id": 0, "texture_id": 20, "tile_column": 20, "tile_row": 0},
                "minecraft:block/oak_log": {"chunk_id": 0, "texture_id": 21, "tile_column": 21, "tile_row": 0},
                "minecraft:block/oak_log_top": {"chunk_id": 0, "texture_id": 22, "tile_column": 22, "tile_row": 0},
                "minecraft:block/red_mushroom_block": {"chunk_id": 0, "texture_id": 23, "tile_column": 23, "tile_row": 0},
                "minecraft:block/mushroom_block_inside": {"chunk_id": 0, "texture_id": 24, "tile_column": 24, "tile_row": 0},
                "minecraft:block/white_glazed_terracotta": {"chunk_id": 0, "texture_id": 25, "tile_column": 25, "tile_row": 0},
                "minecraft:block/spruce_leaves": {"chunk_id": 0, "texture_id": 26, "tile_column": 26, "tile_row": 0},
                "minecraft:block/wheat_stage7": {"chunk_id": 0, "texture_id": 27, "tile_column": 27, "tile_row": 0},
            }
        }

        test_states = [
            b"minecraft:furnace[facing=north,lit=true]",      # 0: Lit furnace
            b"minecraft:furnace[facing=north,lit=false]",     # 1: Unlit furnace
            b"minecraft:grass_block[snowy=true]",             # 2: Snowy grass
            b"minecraft:beehive[facing=north,honey_level=5]", # 3: Full beehive
            b"minecraft:respawn_anchor[charges=4]",           # 4: Charged respawn anchor
            b"minecraft:oak_log[axis=x]",                     # 5: X-axis log
            b"minecraft:red_mushroom_block[up=true,down=false,north=false,south=true,east=true,west=true]", # 6: Mushroom
            b"minecraft:white_glazed_terracotta",             # 7: Glazed terracotta
            b"minecraft:spruce_leaves",                       # 8: Spruce leaves (hardcoded tint)
            b"minecraft:glowstone",                           # 9: Glowstone (emissive)
            b"minecraft:wheat[age=7]",                        # 10: Wheat age 7
        ]

        test_mesh = bpy.data.meshes.new("Test_States_Mesh")
        test_mesh.from_pydata([(float(i), 0.0, 0.0) for i in range(len(test_states))], [], [])
        test_mesh.update()
        states_attr = test_mesh.attributes.new("block_state", 'STRING', 'POINT')
        for i, s in enumerate(test_states):
            states_attr.data[i].value = s

        write_yefira_point_atlas_attributes(test_mesh, mock_mapping)

        # 0. Lit furnace: North (-Z) is front_on (tile_col=2), emissive = 1
        self.assertEqual(test_mesh.attributes["mtk_tile_north"].data[0].vector[0], 2.0)
        self.assertEqual(test_mesh.attributes["mtk_emissive"].data[0].value, 1)

        # 1. Unlit furnace: North (-Z) is front (tile_col=1), emissive = 0
        self.assertEqual(test_mesh.attributes["mtk_tile_north"].data[1].vector[0], 1.0)
        self.assertEqual(test_mesh.attributes["mtk_emissive"].data[1].value, 0)

        # 2. Snowy grass: East/West/South/North are grass_block_snow (tile_col=10), top tint is zero weight
        self.assertEqual(test_mesh.attributes["mtk_tile_east"].data[2].vector[0], 10.0)
        self.assertEqual(tuple(test_mesh.attributes["mtk_tint_data_top"].data[2].color), (0.0, 0.0, 0.0, 0.0))

        # 3. Beehive honey_level=5: North (-Z) is front_honey (tile_col=13)
        self.assertEqual(test_mesh.attributes["mtk_tile_north"].data[3].vector[0], 13.0)

        # 4. Respawn anchor charges=4: Top is top (tile_col=17), East side is side4 (tile_col=19), emissive = 1
        self.assertEqual(test_mesh.attributes["mtk_tile_top"].data[4].vector[0], 17.0)
        self.assertEqual(test_mesh.attributes["mtk_tile_east"].data[4].vector[0], 19.0)
        self.assertEqual(test_mesh.attributes["mtk_emissive"].data[4].value, 1)

        # 5. Oak log axis=x: East (+X) and West (-X) are top (tile_col=22), Top (+Y) is side (tile_col=21)
        self.assertEqual(test_mesh.attributes["mtk_tile_east"].data[5].vector[0], 22.0)
        self.assertEqual(test_mesh.attributes["mtk_tile_west"].data[5].vector[0], 22.0)
        self.assertEqual(test_mesh.attributes["mtk_tile_top"].data[5].vector[0], 21.0)

        # 6. Red mushroom block: Top (+Y) is skin (tile_col=23), Bottom (-Y) & North (-Z) are inside (tile_col=24)
        self.assertEqual(test_mesh.attributes["mtk_tile_top"].data[6].vector[0], 23.0)
        self.assertEqual(test_mesh.attributes["mtk_tile_bottom"].data[6].vector[0], 24.0)
        self.assertEqual(test_mesh.attributes["mtk_tile_north"].data[6].vector[0], 24.0)

        # 7. Glazed terracotta: All faces are white_glazed_terracotta (tile_col=25)
        self.assertEqual(test_mesh.attributes["mtk_tile_top"].data[7].vector[0], 25.0)
        self.assertEqual(test_mesh.attributes["mtk_tile_east"].data[7].vector[0], 25.0)

        # 8. Spruce leaves: Hardcoded tint flag set
        self.assertEqual(test_mesh.attributes["mtk_tint_data_top"].data[8].color[3], 1.0)

        # 9. Glowstone: Emissive
        self.assertEqual(test_mesh.attributes["mtk_emissive"].data[9].value, 1)

    def test_sequential_material_replacement_point_cloud(self):
        """Verify that replacing materials 1st, 2nd, and 3rd time updates the point cloud,
        assigned material slots, and Geometry Nodes Set Material nodes correctly without getting stuck."""
        from utils.system.dependencies import has_pillow
        if not has_pillow():
            self.skipTest("Pillow not installed in test environment")

        import tempfile
        import zipfile
        from PIL import Image
        from pipeline.presets import run_preset_pipeline

        # Build Yefira_Material_Dispatcher sub-group to emulate full Yefira DCC setup
        disp_tree = bpy.data.node_groups.new(name="Yefira_Material_Dispatcher", type='GeometryNodeTree')
        disp_tree.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
        disp_tree.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
        gn_in = disp_tree.nodes.new("NodeGroupInput")
        gn_out = disp_tree.nodes.new("NodeGroupOutput")
        set_mat0 = disp_tree.nodes.new("GeometryNodeSetMaterial")
        set_mat0.name = "Set Material (Chunk 0)"
        set_mat0.inputs["Material"].default_value = self.obj.data.materials[0]
        disp_tree.links.new(gn_in.outputs["Geometry"], set_mat0.inputs["Geometry"])
        disp_tree.links.new(set_mat0.outputs["Geometry"], gn_out.inputs["Geometry"])

        # Add Material Dispatcher node to world tree
        disp_node = self.mod.node_group.nodes.new("GeometryNodeGroup")
        disp_node.node_tree = disp_tree
        disp_node.name = "Material Dispatcher"

        # Create 3 distinct resource packs with different texture colors
        tmp_dir = tempfile.TemporaryDirectory()
        pack_paths = []
        colors = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)]
        for i, color in enumerate(colors):
            zip_file = Path(tmp_dir.name) / f"pack_{i + 1}.zip"
            with zipfile.ZipFile(zip_file, "w") as zf:
                img_path = Path(tmp_dir.name) / f"stone_{i + 1}.png"
                Image.new("RGBA", (16, 16), color).save(img_path)
                zf.write(img_path, arcname="assets/minecraft/textures/block/stone.png")
            pack_paths.append(zip_file)

        assigned_materials = []
        for pack_idx, pack_path in enumerate(pack_paths):
            params = {
                "zip_path": str(pack_path),
                "material_mode": "ATLAS",
                "pack_textures": True,
                "use_cache": False,
            }
            res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[self.obj])
            self.assertTrue(res.is_success, f"Replacement {pack_idx + 1} failed: {res.message}")

            cur_mat = self.obj.material_slots[0].material
            self.assertIsNotNone(cur_mat, f"Slot 0 is None on replacement {pack_idx + 1}")
            self.assertTrue(cur_mat.name.startswith("mtk:minecraft:atlas_chunk_"))
            assigned_materials.append(cur_mat)

            # Check that current material is distinct from previous replacements
            if pack_idx > 0:
                self.assertNotEqual(
                    cur_mat.name,
                    assigned_materials[pack_idx - 1].name,
                    f"Replacement {pack_idx + 1} did not create/assign a new material (same as replacement {pack_idx})"
                )

            # Check Material Dispatcher node group has the current material
            disp_set_mat = [n for n in disp_tree.nodes if n.type == 'SET_MATERIAL']
            self.assertTrue(len(disp_set_mat) > 0)
            self.assertEqual(
                disp_set_mat[0].inputs["Material"].default_value,
                cur_mat,
                f"Material Dispatcher on replacement {pack_idx + 1} was stuck on {disp_set_mat[0].inputs['Material'].default_value} instead of {cur_mat}"
            )


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])


