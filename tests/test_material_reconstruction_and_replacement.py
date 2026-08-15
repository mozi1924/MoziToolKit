"""Tests for material identification and cross-mode replacement with UV inversion."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import bpy
    HAS_BPY = True
except ImportError:
    HAS_BPY = False

from utils.materials import (
    atlas_uv_from_local,
    local_uv_from_atlas,
    atlas_uv_from_rect,
    local_uv_from_rect,
    find_texture_id_from_atlas_uv,
)

if HAS_BPY:
    from utils.materials import (
        detect_material_mode,
        is_mozi_material,
        extract_face_texture_info,
        base_texture_candidates,
    )
    from pipeline.presets import run_preset_pipeline


class TestUVTransformMath(unittest.TestCase):
    """Test precision and invertibility of Atlas <-> Local UV coordinate math."""

    def test_static_atlas_uv_roundtrip(self):
        cases = [
            (0.0, 0.0, 0, 0, 16, 256, 256),
            (1.0, 1.0, 3, 5, 16, 512, 1024),
            (0.25, 0.75, 7, 2, 32, 1024, 2048),
            (0.5, 0.5, 15, 63, 16, 256, 1024),
            # Testing sub-quad and scaled UV values (> 1.0 or < 0.0)
            (1.2, -0.2, 2, 4, 16, 512, 512),
        ]
        for u_orig, v_orig, col, row, tile_size, atlas_w, atlas_h in cases:
            u_atlas, v_atlas = atlas_uv_from_local(
                u_orig, v_orig,
                tile_column=col,
                tile_row=row,
                tile_size=tile_size,
                atlas_width=atlas_w,
                atlas_height=atlas_h,
            )
            u_recovered, v_recovered = local_uv_from_atlas(
                u_atlas, v_atlas,
                tile_column=col,
                tile_row=row,
                tile_size=tile_size,
                atlas_width=atlas_w,
                atlas_height=atlas_h,
            )
            self.assertAlmostEqual(u_orig, u_recovered, places=6)
            self.assertAlmostEqual(v_orig, v_recovered, places=6)

    def test_rect_atlas_uv_roundtrip(self):
        cases = [
            (0.0, 0.0, 0, 0, 16, 16, 256, 512),
            (1.0, 1.0, 64, 0, 32, 32, 512, 1024),
            (0.33, 0.67, 128, 0, 16, 16, 1024, 1024),
        ]
        for u_orig, v_orig, px, py, rw, rh, atlas_w, atlas_h in cases:
            u_atlas, v_atlas = atlas_uv_from_rect(
                u_orig, v_orig,
                pixel_x=px,
                pixel_y=py,
                rect_width=rw,
                rect_height=rh,
                atlas_width=atlas_w,
                atlas_height=atlas_h,
            )
            u_recovered, v_recovered = local_uv_from_rect(
                u_atlas, v_atlas,
                pixel_x=px,
                pixel_y=py,
                rect_width=rw,
                rect_height=rh,
                atlas_width=atlas_w,
                atlas_height=atlas_h,
            )
            self.assertAlmostEqual(u_orig, u_recovered, places=6)
            self.assertAlmostEqual(v_orig, v_recovered, places=6)


@unittest.skipUnless(HAS_BPY, "bpy module is required")
class TestMaterialModeDetection(unittest.TestCase):
    """Test material mode classification."""

    def setUp(self):
        if not HAS_BPY:
            self.skipTest("bpy not available")
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def test_material_mode_detection(self):
        # Generic
        mat_gen = bpy.data.materials.new("Vanilla_Stone")
        self.assertEqual(detect_material_mode(mat_gen), "GENERIC")
        self.assertFalse(is_mozi_material(mat_gen))

        # Standalone Mozi
        mat_mozi = bpy.data.materials.new("mtk:minecraft:stone:a1b2c3d4e5f6")
        mat_mozi["mtk:source_namespace"] = "minecraft"
        mat_mozi["mtk:source_texture"] = "stone"
        self.assertEqual(detect_material_mode(mat_mozi), "STANDALONE")
        self.assertTrue(is_mozi_material(mat_mozi))

        # Atlas Chunk
        mat_chunk = bpy.data.materials.new("mtk:minecraft:atlas_chunk_000:a1b2c3d4e5f6")
        mat_chunk["mtk:atlas_chunk_id"] = 0
        self.assertEqual(detect_material_mode(mat_chunk), "ATLAS_CHUNK")
        self.assertTrue(is_mozi_material(mat_chunk))


@unittest.skipUnless(HAS_BPY, "bpy module is required")
class TestCrossModeMaterialReplacement(unittest.TestCase):
    """Integration test for Standalone <-> Atlas cross-mode replacements with UV restoration."""

    def setUp(self):
        import tempfile
        if not HAS_BPY:
            self.skipTest("bpy not available")

        self.temp_dir = tempfile.TemporaryDirectory()
        self.pack_dir = Path(self.temp_dir.name)
        tex_dir = self.pack_dir / "assets/minecraft/textures/block"
        tex_dir.mkdir(parents=True, exist_ok=True)

        # Create test texture: stone.png
        stone_file = tex_dir / "stone.png"
        img_stone = bpy.data.images.new("temp_stone", width=16, height=16)
        img_stone.filepath_raw = str(stone_file)
        img_stone.file_format = "PNG"
        img_stone.save()
        bpy.data.images.remove(img_stone)

        # Create test texture: dirt.png
        dirt_file = tex_dir / "dirt.png"
        img_dirt = bpy.data.images.new("temp_dirt", width=16, height=16)
        img_dirt.filepath_raw = str(dirt_file)
        img_dirt.file_format = "PNG"
        img_dirt.save()
        bpy.data.images.remove(img_dirt)

        bpy.ops.wm.read_factory_settings(use_empty=True)

        # Create a cube object
        bpy.ops.mesh.primitive_cube_add(size=2.0)
        self.cube = bpy.context.active_object
        self.cube.name = "TestCube"

        # Assign initial vanilla material
        mat = bpy.data.materials.new(name="stone")
        self.cube.data.materials.append(mat)
        uv_layer = self.cube.data.uv_layers.active
        self.original_uv_coords = [(item.uv.x, item.uv.y) for item in uv_layer.data]

    def tearDown(self):
        if hasattr(self, "temp_dir"):
            self.temp_dir.cleanup()

    def test_standalone_to_atlas_to_standalone_cycle(self):
        # Step 1: Initial Standalone Replace
        params_standalone = {
            "zip_path": str(self.pack_dir),
            "material_mode": "STANDALONE",
            "pack_textures": True,
            "use_cache": False,
        }
        res1, ctx1 = run_preset_pipeline("replace_material", bpy.context, params=params_standalone, target_objects=[self.cube])
        self.assertTrue(res1.is_success, f"res1 failed: {res1.message} - reports: {ctx1.reports}")
        self.assertEqual(len(self.cube.material_slots), 1)
        self.assertTrue(self.cube.material_slots[0].material.name.startswith("mtk:minecraft:stone"))

        # Step 2: Convert Standalone -> Atlas
        from utils.system import has_pillow
        if not has_pillow():
            self.skipTest("Pillow is not installed in current environment; skipping Atlas step")

        params_atlas = {
            "zip_path": str(self.pack_dir),
            "material_mode": "ATLAS",
            "pack_textures": True,
            "use_cache": False,
        }
        res2, ctx2 = run_preset_pipeline("replace_material", bpy.context, params=params_atlas, target_objects=[self.cube])
        self.assertTrue(res2.is_success, f"res2 failed: {res2.message} - reports: {ctx2.reports}")
        self.assertTrue(self.cube.material_slots[0].material.name.startswith("mtk:minecraft:atlas_chunk_"))
        self.assertIn("atlas_chunk_id", self.cube.data.attributes)
        self.assertIn("atlas_texture_id", self.cube.data.attributes)

        # Verify UVs moved into Atlas cells
        uv_layer = self.cube.data.uv_layers.active
        atlas_uv_coords = [(item.uv.x, item.uv.y) for item in uv_layer.data]
        self.assertTrue(any(abs(a[0] - o[0]) > 1e-4 or abs(a[1] - o[1]) > 1e-4
                            for a, o in zip(atlas_uv_coords, self.original_uv_coords)))

        # Step 3: Convert Atlas -> Standalone (Invert UVs and restore standalone material)
        res3, ctx3 = run_preset_pipeline("replace_material", bpy.context, params=params_standalone, target_objects=[self.cube])
        self.assertTrue(res3.is_success, f"res3 failed: {res3.message} - reports: {ctx3.reports}")
        self.assertTrue(self.cube.material_slots[0].material.name.startswith("mtk:minecraft:stone"))

        # Verify attributes cleaned up
        self.assertNotIn("atlas_chunk_id", self.cube.data.attributes)
        self.assertNotIn("atlas_texture_id", self.cube.data.attributes)

        # Verify UVs restored back to original [0, 1] UV space!
        restored_uv_coords = [(item.uv.x, item.uv.y) for item in uv_layer.data]
        for (u_res, v_res), (u_orig, v_orig) in zip(restored_uv_coords, self.original_uv_coords):
            self.assertAlmostEqual(u_res, u_orig, places=4)
            self.assertAlmostEqual(v_res, v_orig, places=4)

    def test_unmatched_face_leaves_the_entire_object_unchanged(self):
        """Mixed matches must not corrupt the unmatched face's material slot."""
        missing = bpy.data.materials.new(name="not_in_pack")
        self.cube.data.materials.append(missing)
        self.cube.data.polygons[0].material_index = 1
        original_slots = [slot.material for slot in self.cube.material_slots]
        original_indices = [poly.material_index for poly in self.cube.data.polygons]

        params = {
            "zip_path": str(self.pack_dir),
            "material_mode": "STANDALONE",
            "pack_textures": True,
            "use_cache": False,
        }
        res, _ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[self.cube])
        self.assertTrue(res.is_success)
        self.assertEqual([slot.material for slot in self.cube.material_slots], original_slots)
        self.assertEqual([poly.material_index for poly in self.cube.data.polygons], original_indices)
        self.assertNotIn("mtk_source_texture_key", self.cube.data.attributes)

    def test_ice_cube_internal_faces_are_retained_per_face(self):
        """An internal_face_deletion.001 slot must not become oak leaves."""
        leaves_file = self.pack_dir / "assets/minecraft/textures/block/oak_leaves.png"
        leaves_img = bpy.data.images.new("oak_leaves", width=16, height=16)
        leaves_img.filepath_raw = str(leaves_file)
        leaves_img.file_format = "PNG"
        leaves_img.save()

        internal = bpy.data.materials.new(name="internal_face_deletion.001")
        internal["ice_cube.material_id"] = "internal"
        internal.use_nodes = True
        tex = internal.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = leaves_img
        self.cube.data.materials.append(internal)
        self.cube.data.polygons[0].material_index = 1

        params = {
            "zip_path": str(self.pack_dir),
            "material_mode": "STANDALONE",
            "pack_textures": True,
            "use_cache": False,
        }
        res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[self.cube])
        self.assertTrue(res.is_success, ctx.reports)
        face_material = self.cube.material_slots[self.cube.data.polygons[0].material_index].material
        self.assertIs(face_material, internal)
        self.assertTrue(any(
            slot.material and slot.material.name.startswith("mtk:minecraft:stone")
            for slot in self.cube.material_slots
        ))

    def test_atlas_retains_ice_cube_internal_faces_per_face(self):
        """Atlas mode must also preserve invisible Ice Cube faces."""
        from utils.system import has_pillow
        if not has_pillow():
            self.skipTest("Pillow is not installed in current environment")

        leaves_file = self.pack_dir / "assets/minecraft/textures/block/oak_leaves.png"
        leaves_img = bpy.data.images.new("oak_leaves_atlas", width=16, height=16)
        leaves_img.filepath_raw = str(leaves_file)
        leaves_img.file_format = "PNG"
        leaves_img.save()

        internal = bpy.data.materials.new(name="internal_face_deletion.002")
        internal["flip_fluid_material_library"] = True
        internal.use_nodes = True
        tex = internal.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = leaves_img
        self.cube.data.materials.append(internal)
        self.cube.data.polygons[0].material_index = 1

        params = {
            "zip_path": str(self.pack_dir),
            "material_mode": "ATLAS",
            "pack_textures": True,
            "use_cache": False,
        }
        res, ctx = run_preset_pipeline("replace_material", bpy.context, params=params, target_objects=[self.cube])
        self.assertTrue(res.is_success, ctx.reports)
        face_material = self.cube.material_slots[self.cube.data.polygons[0].material_index].material
        self.assertIs(face_material, internal)
        self.assertTrue(any(
            slot.material and slot.material.name.startswith("mtk:minecraft:atlas_chunk_")
            for slot in self.cube.material_slots
        ))

    def test_face_source_key_is_authoritative_over_material_name(self):
        """A durable per-face key survives arbitrary material renaming."""
        from utils.materials import extract_face_texture_info, write_face_source_provenance

        write_face_source_provenance(
            self.cube.data,
            ["minecraft:stone"] * len(self.cube.data.polygons),
            ["generic"] * len(self.cube.data.polygons),
        )
        self.cube.data.materials[0].name = "unrelated_material_name"
        namespace, candidates, location = extract_face_texture_info(
            self.cube.data, 0, self.cube.data.materials[0]
        )
        self.assertEqual(namespace, "minecraft")
        self.assertEqual(candidates, ["stone"])
        self.assertIsNone(location)

    def test_resource_keys_keep_namespace_and_texture_path(self):
        """Pack hashes are provenance only; resource paths avoid mod collisions."""
        from utils.materials import ZipResourcePack

        mod_tex_dir = self.pack_dir / "assets" / "examplemod" / "textures" / "block"
        mod_tex_dir.mkdir(parents=True)
        img = bpy.data.images.new("mod_copper", width=16, height=16)
        img.filepath_raw = str(mod_tex_dir / "copper.png")
        img.file_format = "PNG"
        img.save()
        bpy.data.images.remove(img)

        pack = ZipResourcePack(self.pack_dir, use_cache=False)
        vanilla = pack.get_texture_info("block/stone", "minecraft")
        modded = pack.get_texture_info("block/copper", "examplemod")
        self.assertEqual(vanilla["texture_key"], "block/stone")
        self.assertEqual(modded["texture_key"], "block/copper")
        self.assertNotEqual(
            (vanilla["namespace"], vanilla["texture_key"]),
            (modded["namespace"], modded["texture_key"]),
        )

    def test_mod_namespace_round_trips_through_atlas(self):
        """A mod key stays isolated from Minecraft while switching modes."""
        from utils.system import has_pillow
        if not has_pillow():
            self.skipTest("Pillow is not installed in current environment")

        mod_tex_dir = self.pack_dir / "assets" / "examplemod" / "textures" / "block"
        mod_tex_dir.mkdir(parents=True)
        img = bpy.data.images.new("mod_copper_atlas", width=16, height=16)
        img.filepath_raw = str(mod_tex_dir / "copper.png")
        img.file_format = "PNG"
        img.save()
        bpy.data.images.remove(img)

        self.cube.data.materials[0].name = "examplemod:copper"
        atlas_params = {
            "zip_path": str(self.pack_dir),
            "material_mode": "ATLAS",
            "pack_textures": True,
            "use_cache": False,
        }
        res_atlas, ctx_atlas = run_preset_pipeline(
            "replace_material", bpy.context, params=atlas_params, target_objects=[self.cube]
        )
        self.assertTrue(res_atlas.is_success, ctx_atlas.reports)

        source_attr = self.cube.data.attributes["mtk_source_texture_key"]
        values = [item.value.decode("utf-8") for item in source_attr.data]
        self.assertEqual(set(values), {"examplemod:block/copper"})
        origin_values = [item.value.decode("utf-8") for item in self.cube.data.attributes["mtk_source_origin"].data]
        self.assertEqual(set(origin_values), {"generic"})

        standalone_params = dict(atlas_params, material_mode="STANDALONE")
        res_standalone, ctx_standalone = run_preset_pipeline(
            "replace_material", bpy.context, params=standalone_params, target_objects=[self.cube]
        )
        self.assertTrue(res_standalone.is_success, ctx_standalone.reports)
        self.assertTrue(self.cube.material_slots[0].material.name.startswith("mtk:examplemod:copper"))
        origin_values = [item.value.decode("utf-8") for item in self.cube.data.attributes["mtk_source_origin"].data]
        self.assertEqual(set(origin_values), {"generic"})

    def test_image_filepath_namespace_detection(self):
        """Image filepath like assets/create/textures/block/brass_casing.png must detect namespace 'create'."""
        mat = bpy.data.materials.new("GenericMat")
        mat.use_nodes = True
        img = bpy.data.images.new("brass_casing.png", width=16, height=16)
        img.filepath = "/workspace/assets/create/textures/block/brass_casing.png"
        tex_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex_node.image = img

        ns, candidates = base_texture_candidates(mat)
        self.assertEqual(ns, "create")
        self.assertIn("brass_casing", candidates)

    def test_resource_pack_get_texture_info_fallback_and_namespace_key(self):
        """ZipResourcePack.get_texture_info should resolve mod namespace keys and unique fallbacks."""
        from utils.materials import ZipResourcePack

        mod_tex_dir = self.pack_dir / "assets" / "farmersdelight" / "textures" / "block"
        mod_tex_dir.mkdir(parents=True)
        img = bpy.data.images.new("fd_cutting_board", width=16, height=16)
        img.filepath_raw = str(mod_tex_dir / "cutting_board.png")
        img.file_format = "PNG"
        img.save()
        bpy.data.images.remove(img)

        pack = ZipResourcePack(self.pack_dir, use_cache=False)
        # Explicit key with namespace colon
        info1 = pack.get_texture_info("farmersdelight:cutting_board")
        self.assertIsNotNone(info1)
        self.assertEqual(info1["namespace"], "farmersdelight")
        self.assertEqual(info1["texture_name"], "cutting_board")

        # Fallback lookup when default 'minecraft' is passed but texture only exists in farmersdelight
        info2 = pack.get_texture_info("cutting_board")
        self.assertIsNotNone(info2)
        self.assertEqual(info2["namespace"], "farmersdelight")


@unittest.skipUnless(HAS_BPY, "bpy module is required")
class TestAnimatedUVMapping(unittest.TestCase):
    """Test animated UV node template construction, socket contract, and standalone/atlas math."""

    def setUp(self):
        if not HAS_BPY:
            self.skipTest("bpy not available")
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def test_animated_uv_node_group_interface(self):
        from utils.node_groups.animated import ensure_animated_uv_mapping, UV_TEMPLATE_VERSION
        group = ensure_animated_uv_mapping()
        self.assertIsNotNone(group)
        self.assertEqual(group.get("mozi_template_version"), UV_TEMPLATE_VERSION)

        input_names = [s.name for s in group.interface.items_tree if s.in_out == "INPUT"]
        output_names = [s.name for s in group.interface.items_tree if s.in_out == "OUTPUT"]

        expected_inputs = [
            "Vector", "Current Frame", "Next Frame", "Blend Factor",
            "Frame Width", "Frame Height", "Image Width", "Image Height",
            "Atlas Mode",
        ]
        for name in expected_inputs:
            self.assertIn(name, input_names, f"Missing input socket '{name}' in MC_Animated_UV_Mapping")

        expected_outputs = ["Current UV", "Next UV", "Blend Factor"]
        for name in expected_outputs:
            self.assertIn(name, output_names, f"Missing output socket '{name}' in MC_Animated_UV_Mapping")

        # Verify socket limits
        sockets = {s.name: s for s in group.interface.items_tree if s.item_type == "SOCKET"}
        self.assertEqual(sockets["Blend Factor"].min_value, 0.0)
        self.assertEqual(sockets["Blend Factor"].max_value, 1.0)
        self.assertEqual(sockets["Frame Width"].min_value, 1.0)
        self.assertEqual(sockets["Atlas Mode"].min_value, 0.0)
        self.assertEqual(sockets["Atlas Mode"].max_value, 1.0)

    def test_frame_blend_and_atlas_decoder_socket_bounds(self):
        from utils.node_groups.animated import ensure_animated_frame_blend
        from utils.node_groups.atlas_uv_decoder import build_atlas_uv_decoder_node_group

        blend_group = ensure_animated_frame_blend()
        blend_sockets = {s.name: s for s in blend_group.interface.items_tree if s.item_type == "SOCKET"}
        self.assertEqual(blend_sockets["Current Alpha"].min_value, 0.0)
        self.assertEqual(blend_sockets["Current Alpha"].max_value, 1.0)
        self.assertEqual(blend_sockets["Blend Factor"].min_value, 0.0)
        self.assertEqual(blend_sockets["Blend Factor"].max_value, 1.0)

        atlas_decoder = build_atlas_uv_decoder_node_group()
        atlas_sockets = {s.name: s for s in atlas_decoder.interface.items_tree if s.item_type == "SOCKET"}
        self.assertEqual(atlas_sockets["Face Index"].min_value, 0.0)
        self.assertEqual(atlas_sockets["Face Index"].max_value, 5.0)
        self.assertEqual(atlas_sockets["Use Face Index"].min_value, 0.0)
        self.assertEqual(atlas_sockets["Use Face Index"].max_value, 1.0)
        self.assertEqual(atlas_sockets["Tile Size"].min_value, 1.0)
        self.assertEqual(atlas_sockets["Atlas Width"].min_value, 1.0)

    def test_scheduler_wraps_between_zero_and_total_frames(self):
        """Blender's WRAP inputs are Value, Max, Min (not Value, Min, Max)."""
        from utils.node_groups.animated import ensure_animation_scheduler, SCHEDULER_TEMPLATE_VERSION

        scheduler = ensure_animation_scheduler()
        self.assertEqual(scheduler.get("mozi_template_version"), SCHEDULER_TEMPLATE_VERSION)
        for node_name in ("Current Frame", "Next Frame"):
            wrap = scheduler.nodes[node_name]
            # Max gets Total Frames; Min remains exactly zero.  Reversing
            # these inputs sends time zero to the final/invalid atlas frame.
            self.assertEqual(wrap.inputs[2].default_value, 0.0)
            self.assertEqual(len(wrap.inputs[1].links), 1)
            self.assertEqual(wrap.inputs[1].links[0].from_socket.name, "Total Frames")

    def test_standalone_and_atlas_uv_math(self):
        """Verify the mathematical mapping logic for Standalone (Local UV) and Atlas (Pre-mapped UV)."""
        def compute_animated_uv(u, v, frame, frame_w, frame_h, img_w, img_h, atlas_mode):
            frame_step_v = frame_h / img_h
            frame_step_u = frame_w / img_w
            if atlas_mode == 0.0:
                # Standalone / Local UV Mode
                base_u = u * frame_step_u
                base_v = 1.0 - (1.0 - v) * frame_step_v
            else:
                # Atlas Mode (pre-mapped UV)
                base_u = u
                base_v = v
            final_u = base_u
            final_v = base_v - frame * frame_step_v
            return final_u, final_v

        # Case 1: Standalone animated texture (16x512, 32 frames of 16x16)
        # Face quad local UV spans (0..1, 0..1)
        # Frame 0:
        u0_bl, v0_bl = compute_animated_uv(0.0, 0.0, 0, 16, 16, 16, 512, 0.0)
        u0_tr, v0_tr = compute_animated_uv(1.0, 1.0, 0, 16, 16, 16, 512, 0.0)
        self.assertAlmostEqual(u0_bl, 0.0)
        self.assertAlmostEqual(v0_bl, 1.0 - 16 / 512)
        self.assertAlmostEqual(u0_tr, 1.0)
        self.assertAlmostEqual(v0_tr, 1.0)

        # Frame 1:
        u1_bl, v1_bl = compute_animated_uv(0.0, 0.0, 1, 16, 16, 16, 512, 0.0)
        u1_tr, v1_tr = compute_animated_uv(1.0, 1.0, 1, 16, 16, 16, 512, 0.0)
        self.assertAlmostEqual(u1_bl, 0.0)
        self.assertAlmostEqual(v1_bl, 1.0 - 32 / 512)
        self.assertAlmostEqual(u1_tr, 1.0)
        self.assertAlmostEqual(v1_tr, 1.0 - 16 / 512)

        # Frame 31 (last frame):
        u31_bl, v31_bl = compute_animated_uv(0.0, 0.0, 31, 16, 16, 16, 512, 0.0)
        self.assertAlmostEqual(u31_bl, 0.0)
        self.assertAlmostEqual(v31_bl, 0.0)

        # Case 2: Atlas animated texture (64x512 chunk, animation at column pixel_x=16)
        # Mesh UV was pre-mapped via atlas_uv_from_rect:
        u_atlas_bl, v_atlas_bl = atlas_uv_from_rect(0.0, 0.0, pixel_x=16, pixel_y=0, rect_width=16, rect_height=16, atlas_width=64, atlas_height=512)
        u_atlas_tr, v_atlas_tr = atlas_uv_from_rect(1.0, 1.0, pixel_x=16, pixel_y=0, rect_width=16, rect_height=16, atlas_width=64, atlas_height=512)

        # Frame 0 in Atlas Mode (atlas_mode = 1.0):
        u0_atlas, v0_atlas = compute_animated_uv(u_atlas_tr, v_atlas_tr, 0, 16, 16, 64, 512, 1.0)
        self.assertAlmostEqual(u0_atlas, (16 + 16) / 64)
        self.assertAlmostEqual(v0_atlas, 1.0)

        # Frame 1 in Atlas Mode:
        u1_atlas, v1_atlas = compute_animated_uv(u_atlas_tr, v_atlas_tr, 1, 16, 16, 64, 512, 1.0)
        self.assertAlmostEqual(u1_atlas, (16 + 16) / 64)
        self.assertAlmostEqual(v1_atlas, 1.0 - 16 / 512)


def run_all_tests():
    import os
    print("=" * 60)
    print("Running Material Reconstruction & Replacement Unit Tests...")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestUVTransformMath))
    suite.addTests(loader.loadTestsFromTestCase(TestAnimatedUVMapping))
    suite.addTests(loader.loadTestsFromTestCase(TestMaterialModeDetection))
    suite.addTests(loader.loadTestsFromTestCase(TestCrossModeMaterialReplacement))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("\n✅ ALL TESTS PASSED SUCCESSFULLY!")
        os._exit(0)
    else:
        print("\n❌ SOME TESTS FAILED!")
        os._exit(1)


if __name__ == "__main__":
    run_all_tests()
