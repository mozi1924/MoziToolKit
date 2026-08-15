"""
Headless Automated Test Suite for MoziToolKit Pipeline Framework

Executed using Blender executable:
blender -b --python tests/run_tests.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root and parent directory to sys.path
PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy
import bmesh


class TestPipelineFramework(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Register addon package dynamically
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "MoziToolKit",
                str(PROJECT_DIR / "__init__.py"),
                submodule_search_locations=[str(PROJECT_DIR)]
            )
            pkg = importlib.util.module_from_spec(spec)
            sys.modules["MoziToolKit"] = pkg
            spec.loader.exec_module(pkg)
            if hasattr(pkg, "register"):
                pkg.register()
        except Exception as e:
            print(f"[Test Init] Extension registration note: {e}")

    def setUp(self):
        # Ensure we are in OBJECT mode before deleting objects
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        # Clear existing mesh objects
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)

        # Create a fresh test cube object
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
        self.cube = bpy.context.active_object
        self.cube.name = "TestCube"

    def test_pipeline_context_initialization(self):
        from pipeline.context import PipelineContext
        ctx = PipelineContext(context=bpy.context, params={"test_param": 123})
        self.assertEqual(ctx.active_object, self.cube)
        self.assertEqual(ctx.get_param("test_param"), 123)
        self.assertIn(self.cube, ctx.target_objects)

    def test_clear_custom_normals_step(self):
        from pipeline.presets import run_preset_pipeline
        # Add custom split normals
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.customdata_custom_splitnormals_add()
        bpy.ops.object.mode_set(mode="OBJECT")

        res, ctx = run_preset_pipeline("clear_custom_normals", bpy.context)
        self.assertTrue(res.is_success)
        self.assertFalse(self.cube.data.has_custom_normals)

    def test_select_hard_edges_step(self):
        from pipeline.presets import run_preset_pipeline
        bpy.ops.object.mode_set(mode="EDIT")
        res, ctx = run_preset_pipeline("select_hard_edges", bpy.context, {"sharp_angle": 30.0})
        self.assertTrue(res.is_success)

    def test_scale_uv_step(self):
        from pipeline.presets import run_preset_pipeline
        bpy.ops.object.mode_set(mode="EDIT")
        res, ctx = run_preset_pipeline("scale_uv", bpy.context, {"scale_factor": 0.5})
        self.assertTrue(res.is_success)
        self.assertGreater(ctx.get_data("scaled_uv_faces_count"), 0)

    def test_texture_interpolation_step(self):
        from pipeline.presets import run_preset_pipeline
        # Create a material with image texture
        mat = bpy.data.materials.new(name="TestMaterial")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        tex_node = nodes.new("ShaderNodeTexImage")
        img = bpy.data.images.new(name="TestImg", width=16, height=16)
        tex_node.image = img

        self.cube.data.materials.append(mat)
        bpy.ops.object.mode_set(mode="OBJECT")

        res, ctx = run_preset_pipeline("set_texture_interpolation_closest", bpy.context)
        self.assertTrue(res.is_success)
        self.assertEqual(tex_node.interpolation, "Closest")

    def test_ice_cube_legacy_texture_name_aliases(self):
        from utils.material_matching import ice_cube_legacy_aliases

        self.assertEqual(ice_cube_legacy_aliases("item_clock_00"), ["clock_00"])
        self.assertEqual(
            ice_cube_legacy_aliases("blast_furnace_on_front"),
            ["blast_furnace_front_on"],
        )
        self.assertEqual(
            ice_cube_legacy_aliases("soul_campfire_lit_log"),
            ["soul_campfire_log_lit"],
        )

    def test_ice_cube_preset_is_metadata_scoped(self):
        from utils.material_matching import (
            extract_material_texture_keys,
            get_material_match_preset,
        )

        generic = bpy.data.materials.new(name="British Shorthair Cat")
        generic.use_nodes = True
        self.assertEqual(get_material_match_preset(generic).identifier, "generic")
        self.assertNotIn("cat_british_shorthair", extract_material_texture_keys(generic)[1])

        ice_cube = generic.copy()
        ice_cube["flip_fluid_material_library"] = True
        self.assertEqual(get_material_match_preset(ice_cube).identifier, "ice_cube")
        self.assertIn("cat_british_shorthair", extract_material_texture_keys(ice_cube)[1])

        bpy.data.materials.remove(generic)
        bpy.data.materials.remove(ice_cube)

    def test_unpacked_resource_pack_is_indexed(self):
        from utils.zip_resource_pack import ZipResourcePack

        with tempfile.TemporaryDirectory() as temporary_dir:
            texture_dir = Path(temporary_dir) / "assets/minecraft/textures/block"
            texture_dir.mkdir(parents=True)
            image = bpy.data.images.new("DirectoryPackTest", width=1, height=1)
            image.filepath_raw = str(texture_dir / "directory_pack_test.png")
            image.file_format = "PNG"
            image.save()
            bpy.data.images.remove(image)

            pack = ZipResourcePack(temporary_dir, use_cache=False)
            texture_info = pack.get_texture_info("directory_pack_test")
            self.assertIsNotNone(texture_info)
            self.assertTrue(texture_info["albedo"].exists())

    def test_independent_material_replacement(self):
        from pipeline.presets import run_preset_pipeline

        with tempfile.TemporaryDirectory() as dir_a, tempfile.TemporaryDirectory() as dir_b:
            tex_a = Path(dir_a) / "assets/minecraft/textures/block"
            tex_a.mkdir(parents=True)
            img_a = bpy.data.images.new("OakLogA", width=1, height=1)
            img_a.filepath_raw = str(tex_a / "oak_log.png")
            img_a.file_format = "PNG"
            img_a.save()
            bpy.data.images.remove(img_a)

            tex_b = Path(dir_b) / "assets/minecraft/textures/block"
            tex_b.mkdir(parents=True)
            img_b = bpy.data.images.new("OakLogB", width=2, height=2)
            img_b.filepath_raw = str(tex_b / "oak_log.png")
            img_b.file_format = "PNG"
            img_b.save()
            bpy.data.images.remove(img_b)

            cube1 = self.cube
            mat1 = bpy.data.materials.new(name="oak_log")
            cube1.data.materials.append(mat1)

            bpy.ops.mesh.primitive_cube_add(size=2.0, location=(3, 0, 0))
            cube2 = bpy.context.active_object
            mat2 = bpy.data.materials.new(name="oak_log")
            cube2.data.materials.append(mat2)

            bpy.ops.mesh.primitive_cube_add(size=2.0, location=(6, 0, 0))
            cube3 = bpy.context.active_object
            mat3 = bpy.data.materials.new(name="oak_log")
            cube3.data.materials.append(mat3)

            # Replace cube1 with Pack A
            res1, ctx1 = run_preset_pipeline(
                "replace_material",
                bpy.context,
                params={"zip_path": dir_a, "use_cache": False},
                target_objects=[cube1],
            )
            self.assertTrue(res1.is_success)

            # Replace cube2 with Pack B (different pack hash)
            res2, ctx2 = run_preset_pipeline(
                "replace_material",
                bpy.context,
                params={"zip_path": dir_b, "use_cache": False},
                target_objects=[cube2],
            )
            self.assertTrue(res2.is_success)

            # Replace cube3 with Pack A again (same pack hash as cube1)
            res3, ctx3 = run_preset_pipeline(
                "replace_material",
                bpy.context,
                params={"zip_path": dir_a, "use_cache": False},
                target_objects=[cube3],
            )
            self.assertTrue(res3.is_success)

            mat_res1 = cube1.material_slots[0].material
            mat_res2 = cube2.material_slots[0].material
            mat_res3 = cube3.material_slots[0].material

            self.assertIsNotNone(mat_res1)
            self.assertIsNotNone(mat_res2)
            self.assertIsNotNone(mat_res3)

            # Different pack hash -> Independent material datablocks
            self.assertNotEqual(mat_res1, mat_res2)
            # Same pack hash and texture -> Reused material datablock
            self.assertEqual(mat_res1, mat_res3)

    def test_image_datablock_naming_and_deduplication(self):
        from utils.material_builder import load_image_texture
        from utils.zip_resource_pack import get_directory_hash

        with tempfile.TemporaryDirectory() as dir_a, tempfile.TemporaryDirectory() as dir_b:
            tex_a = Path(dir_a) / "assets/minecraft/textures/block"
            tex_a.mkdir(parents=True)
            img_file_a = tex_a / "dirt.png"
            img_obj_a = bpy.data.images.new("DirtA", width=1, height=1)
            img_obj_a.filepath_raw = str(img_file_a)
            img_obj_a.file_format = "PNG"
            img_obj_a.save()
            bpy.data.images.remove(img_obj_a)
            hash_a = get_directory_hash(Path(dir_a))

            tex_b = Path(dir_b) / "assets/minecraft/textures/block"
            tex_b.mkdir(parents=True)
            img_file_b = tex_b / "dirt.png"
            img_obj_b = bpy.data.images.new("DirtB", width=2, height=2)
            img_obj_b.filepath_raw = str(img_file_b)
            img_obj_b.file_format = "PNG"
            img_obj_b.save()
            bpy.data.images.remove(img_obj_b)
            hash_b = get_directory_hash(Path(dir_b))

            # First load from Pack A
            image_a1 = load_image_texture(img_file_a, pack_hash=hash_a)
            self.assertIsNotNone(image_a1)
            self.assertEqual(image_a1.name, f"dirt.png:{hash_a[:12]}")

            # Second load from Pack A (same pack hash) -> must reuse existing datablock
            image_a2 = load_image_texture(img_file_a, pack_hash=hash_a)
            self.assertEqual(image_a1, image_a2)

            # Load from Pack B (different pack hash) -> must create separate image datablock with Pack B hash
            image_b = load_image_texture(img_file_b, pack_hash=hash_b)
            self.assertIsNotNone(image_b)
            self.assertEqual(image_b.name, f"dirt.png:{hash_b[:12]}")
            self.assertNotEqual(image_a1, image_b)
            self.assertFalse(image_b.name.endswith(".001"))

    def test_pack_hash_equivalence_zip_jar_and_directory(self):
        import zipfile
        from utils.zip_resource_pack import get_pack_hash, ZipResourcePack

        with tempfile.TemporaryDirectory() as base_dir:
            dir_path = Path(base_dir) / "pack_dir"
            tex_dir = dir_path / "assets/minecraft/textures/block"
            tex_dir.mkdir(parents=True)

            # Create sample files
            (dir_path / "pack.mcmeta").write_text('{"pack":{"pack_format":15,"description":"Test Pack"}}', encoding="utf-8")
            (tex_dir / "dirt.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01")
            (tex_dir / "stone.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02")

            # Create ZIP archive from pack_dir
            zip_path = Path(base_dir) / "pack.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                for file_path in dir_path.rglob("*"):
                    if file_path.is_file():
                        rel = file_path.relative_to(dir_path).as_posix()
                        zf.write(file_path, rel)

            # Create JAR archive from pack_dir
            jar_path = Path(base_dir) / "pack.jar"
            with zipfile.ZipFile(jar_path, "w") as zf:
                for file_path in dir_path.rglob("*"):
                    if file_path.is_file():
                        rel = file_path.relative_to(dir_path).as_posix()
                        zf.write(file_path, rel)

            # 1. Hash of directory, zip, and jar must be identical
            hash_dir = get_pack_hash(dir_path)
            hash_zip = get_pack_hash(zip_path)
            hash_jar = get_pack_hash(jar_path)

            self.assertEqual(hash_dir, hash_zip)
            self.assertEqual(hash_dir, hash_jar)

            # 2. ZipResourcePack instance pack_hash must match across all 3
            pack_dir_obj = ZipResourcePack(str(dir_path), use_cache=False)
            pack_zip_obj = ZipResourcePack(str(zip_path), use_cache=False)
            pack_jar_obj = ZipResourcePack(str(jar_path), use_cache=False)

            self.assertEqual(pack_dir_obj.pack_hash, hash_dir)
            self.assertEqual(pack_zip_obj.pack_hash, hash_dir)
            self.assertEqual(pack_jar_obj.pack_hash, hash_dir)

    def test_pack_hash_uniqueness_and_os_metadata_filter(self):
        from utils.zip_resource_pack import get_pack_hash

        with tempfile.TemporaryDirectory() as base_dir:
            dir_a = Path(base_dir) / "pack_a"
            tex_a = dir_a / "assets/minecraft/textures/block"
            tex_a.mkdir(parents=True)
            (tex_a / "dirt.png").write_bytes(b"TEXTURE_DATA_A")

            dir_b = Path(base_dir) / "pack_b"
            tex_b = dir_b / "assets/minecraft/textures/block"
            tex_b.mkdir(parents=True)
            (tex_b / "dirt.png").write_bytes(b"TEXTURE_DATA_B")

            hash_a = get_pack_hash(dir_a)
            hash_b = get_pack_hash(dir_b)

            # Different content -> hash must NOT be equal
            self.assertNotEqual(hash_a, hash_b)

            # Add OS junk / metadata files to pack_a
            (dir_a / ".DS_Store").write_bytes(b"macOS_junk")
            (dir_a / ".extracted").write_bytes(b"OK")
            (dir_a / "Thumbs.db").write_bytes(b"windows_junk")
            macosx_dir = dir_a / "__MACOSX"
            macosx_dir.mkdir()
            (macosx_dir / "._dirt.png").write_bytes(b"resource_fork")

            # Hash of pack_a must remain unchanged despite OS metadata files
            hash_a_dirty = get_pack_hash(dir_a)
            self.assertEqual(hash_a, hash_a_dirty)

    def test_parse_mcmeta_non_animation_metadata_returns_none(self):
        from utils.zip_resource_pack import parse_mcmeta, ZipResourcePack

        with tempfile.TemporaryDirectory() as base_dir:
            pack_dir = Path(base_dir) / "test_pack"
            tex_dir = pack_dir / "assets/minecraft/textures/block"
            tex_dir.mkdir(parents=True)

            # 1. Non-animated .mcmeta (leaves with mipmap_strategy)
            leaves_meta = tex_dir / "oak_leaves.png.mcmeta"
            leaves_meta.write_text('{"texture": {"mipmap_strategy": "dark_cutout"}}', encoding="utf-8")
            self.assertIsNone(parse_mcmeta(leaves_meta))

            # 2. Non-animated .mcmeta (tripwire with alpha_cutoff_bias)
            tripwire_meta = tex_dir / "tripwire.png.mcmeta"
            tripwire_meta.write_text('{"texture": {"alpha_cutoff_bias": 0.1}}', encoding="utf-8")
            self.assertIsNone(parse_mcmeta(tripwire_meta))

            # 3. Valid animated .mcmeta (lava)
            lava_meta = tex_dir / "lava_still.png.mcmeta"
            lava_meta.write_text('{"animation": {"frametime": 2, "interpolate": true}}', encoding="utf-8")
            parsed_lava = parse_mcmeta(lava_meta)
            self.assertIsNotNone(parsed_lava)
            self.assertEqual(parsed_lava["frametime"], 2)
            self.assertTrue(parsed_lava["interpolate"])

            # 4. Check ZipResourcePack texture_index entries
            (tex_dir / "oak_leaves.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01")
            (tex_dir / "lava_still.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02")

            pack = ZipResourcePack(str(pack_dir), use_cache=False)
            leaves_info = pack.get_texture_info("oak_leaves")
            self.assertIsNotNone(leaves_info)
            self.assertIsNone(leaves_info["albedo_mcmeta"])

            lava_info = pack.get_texture_info("lava_still")
            self.assertIsNotNone(lava_info)
            self.assertIsNotNone(lava_info["albedo_mcmeta"])
            self.assertEqual(lava_info["albedo_mcmeta"]["frametime"], 2)

    def test_batch_material_replacement_shares_session_material(self):
        from pipeline.presets import run_preset_pipeline

        with tempfile.TemporaryDirectory() as temporary_dir:
            texture_dir = Path(temporary_dir) / "assets/minecraft/textures/block"
            texture_dir.mkdir(parents=True)
            image = bpy.data.images.new("StoneTest", width=1, height=1)
            image.filepath_raw = str(texture_dir / "stone.png")
            image.file_format = "PNG"
            image.save()
            bpy.data.images.remove(image)

            cube1 = self.cube
            mat1 = bpy.data.materials.new(name="stone")
            cube1.data.materials.append(mat1)

            bpy.ops.mesh.primitive_cube_add(size=2.0, location=(3, 0, 0))
            cube2 = bpy.context.active_object
            mat2 = bpy.data.materials.new(name="stone")
            cube2.data.materials.append(mat2)

            res, ctx = run_preset_pipeline(
                "replace_material",
                bpy.context,
                params={"zip_path": temporary_dir, "use_cache": False},
                target_objects=[cube1, cube2],
            )
            self.assertTrue(res.is_success)

            mat_res1 = cube1.material_slots[0].material
            mat_res2 = cube2.material_slots[0].material

            # Single batch replacement operation shares the session material datablock
            self.assertEqual(mat_res1, mat_res2)


    def test_adaptive_pixel_split_step(self):
        from pipeline.presets import run_preset_pipeline
        bpy.ops.object.mode_set(mode="OBJECT")
        res, ctx = run_preset_pipeline(
            "adaptive_pixel_split",
            bpy.context,
            {
                "auto_resolution": False,
                "resolution_width": 16,
                "resolution_height": 16,
                "pixels_per_face": 1,
                "selection_scope": "ALL",
            },
        )
        self.assertTrue(res.is_success)

    def test_auto_extrude_repair_step(self):
        from pipeline.presets import run_preset_pipeline
        bpy.ops.object.mode_set(mode="EDIT")
        res, ctx = run_preset_pipeline(
            "auto_extrude_repair",
            bpy.context,
            {"repair_uv": True, "add_mean_crease": True, "crease_value": 1.0, "uv_mode": "SMART"},
        )
        self.assertTrue(res.is_success)

    def test_random_extrude_step(self):
        from pipeline.presets import run_preset_pipeline
        bpy.ops.object.mode_set(mode="EDIT")
        res, ctx = run_preset_pipeline(
            "random_extrude",
            bpy.context,
            {
                "min_height": 0.2,
                "max_height": 0.8,
                "seed": 42,
                "noise_mode": "RANDOM",
                "repair_uv": True,
                "add_mean_crease": True,
            },
        )
        self.assertTrue(res.is_success)
        self.assertEqual(ctx.get_data("extruded_faces_count"), 6)
        self.assertEqual(ctx.get_data("repaired_faces_count"), 24)

    def test_operators_invoking_pipelines(self):
        # Test calling operators directly
        bpy.ops.object.mode_set(mode="EDIT")
        res = bpy.ops.mozi.select_hard_edges(sharp_angle=45.0)
        self.assertIn("FINISHED", res)

        res = bpy.ops.mozi.scale_uv(scale_factor=0.9)
        self.assertIn("FINISHED", res)

        res = bpy.ops.mozi.auto_extrude_repair(repair_uv=True, add_mean_crease=True, crease_value=1.0)
        self.assertIn("FINISHED", res)

        res = bpy.ops.mozi.random_extrude(min_height=0.1, max_height=0.5, seed=123)
        self.assertIn("FINISHED", res)

    def test_labpbr_decoder_template(self):
        from utils.node_groups import ensure_labpbr_decoder
        from utils.node_groups.labpbr import reference_shape_errors
        ng = ensure_labpbr_decoder()
        self.assertIsNotNone(ng)
        self.assertEqual(len(ng.nodes), 53)
        self.assertEqual(len(ng.links), 84)
        self.assertFalse(any(node.bl_idname == "NodeReroute" for node in ng.nodes))
        self.assertEqual(reference_shape_errors(ng), ())
        self.assertEqual(ng.get("mozi_template_version"), 8)


def run_all_tests():
    print("=" * 60)
    print("Running MoziToolKit Pipeline Automated Unit Tests...")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestPipelineFramework)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("\n✅ ALL TESTS PASSED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print("\n❌ SOME TESTS FAILED!")
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()
