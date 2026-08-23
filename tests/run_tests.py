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

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Discover and extract bundled extension wheels for headless testing FIRST
try:
    import PIL
    from PIL import _imaging
except ImportError:
    wheels_dir = PROJECT_DIR / "wheels"
    if wheels_dir.exists():
        target_whl = None
        for whl in wheels_dir.glob("*.whl"):
            if sys.platform == "darwin" and "macosx" in whl.name:
                machine = os.uname().machine if hasattr(os, "uname") else "arm64"
                if "arm64" in whl.name and ("arm" in machine or "aarch64" in machine):
                    target_whl = whl
                    break
                elif "x86_64" in whl.name and "x86" in machine:
                    target_whl = whl
                    break
            elif sys.platform == "win32" and "win" in whl.name:
                target_whl = whl
                break
            elif sys.platform.startswith("linux") and "linux" in whl.name:
                target_whl = whl
                break
        if target_whl:
            unpack_dir = Path(tempfile.gettempdir()) / "mozitoolkit_test_wheels"
            unpack_dir.mkdir(parents=True, exist_ok=True)
            if not (unpack_dir / "PIL").exists():
                import zipfile
                with zipfile.ZipFile(target_whl, "r") as zf:
                    zf.extractall(unpack_dir)
            if str(unpack_dir) not in sys.path:
                sys.path.insert(0, str(unpack_dir))

import importlib.util
if "MoziToolKit" not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        "MoziToolKit",
        str(PROJECT_DIR / "__init__.py"),
        submodule_search_locations=[str(PROJECT_DIR)]
    )
    pkg = importlib.util.module_from_spec(spec)
    sys.modules["MoziToolKit"] = pkg
    spec.loader.exec_module(pkg)

import MoziToolKit

# Alias all MoziToolKit submodules to root in sys.modules for test compatibility
for mod_name, mod in list(sys.modules.items()):
    if mod_name.startswith("MoziToolKit."):
        short_name = mod_name[len("MoziToolKit."):]
        sys.modules[short_name] = mod

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
        from utils.materials.matching import ice_cube_legacy_aliases

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
        from utils.materials.matching import (
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
        from utils.materials import ZipResourcePack

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
        from utils.materials import load_image_texture, get_directory_hash

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
        from utils.materials import get_pack_hash, ZipResourcePack

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
        from utils.materials import get_pack_hash

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
        from utils.materials import parse_mcmeta, ZipResourcePack

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
        from utils.node_groups import ensure_labpbr_decoder, LABPBR_TEMPLATE_VERSION
        from utils.node_groups.labpbr import reference_shape_errors
        ng = ensure_labpbr_decoder()
        self.assertIsNotNone(ng)
        self.assertEqual(len(ng.nodes), 52)
        self.assertEqual(len(ng.links), 82)
        self.assertFalse(any(node.bl_idname == "NodeReroute" for node in ng.nodes))
        self.assertEqual(reference_shape_errors(ng), ())
        self.assertEqual(ng.get("mozi_template_version"), LABPBR_TEMPLATE_VERSION)

        # Verify socket convergence and Displacement Scale default
        sockets = {s.name: s for s in ng.interface.items_tree if s.item_type == "SOCKET"}
        disp_scale = sockets["Displacement Scale"]
        self.assertEqual(disp_scale.default_value, 0.0)
        self.assertEqual(disp_scale.min_value, 0.0)
        self.assertEqual(disp_scale.max_value, 1.0)

        enable_pbr = sockets["Enable PBR (0-1)"]
        self.assertEqual(enable_pbr.default_value, 1.0)
        self.assertEqual(enable_pbr.min_value, 0.0)
        self.assertEqual(enable_pbr.max_value, 1.0)

        porosity = sockets["Porosity (0-1)"]
        self.assertEqual(porosity.min_value, 0.0)
        self.assertEqual(porosity.max_value, 1.0)

    def test_pipeline_progress_protocol_and_iterative_execution(self):
        from pipeline import Pipeline, PipelineContext, ProgressUpdate, PipelineStep, StepResult

        class CustomStep(PipelineStep):
            name = "custom_step"
            def execute_iter(self, ctx):
                yield ProgressUpdate(0.0, 2.0, "Step Part 1")
                yield ProgressUpdate(1.0, 2.0, "Step Part 2")
                yield ProgressUpdate(2.0, 2.0, "Step Done")
                yield StepResult.success("Custom step finished")

        pipeline = Pipeline("test_pipeline", steps=[CustomStep(), CustomStep()])
        ctx = PipelineContext(bpy.context)

        updates = []
        final_result = None
        for item in pipeline.execute_iter(ctx):
            if isinstance(item, ProgressUpdate):
                updates.append(item)
            elif isinstance(item, StepResult):
                final_result = item

        self.assertIsNotNone(final_result)
        self.assertTrue(final_result.is_success)
        self.assertTrue(len(updates) > 0)
        self.assertEqual(updates[0].fraction, 0.0)
        self.assertEqual(updates[-1].fraction, 1.0)
        # Check ascending progress fractions
        fractions = [u.fraction for u in updates]
        self.assertEqual(fractions, sorted(fractions))

    def test_pipeline_cooperative_cancellation(self):
        from pipeline import Pipeline, PipelineContext, ProgressUpdate, PipelineStep, StepResult, StepStatus

        class LongRunningStep(PipelineStep):
            name = "long_step"
            def execute_iter(self, ctx):
                for i in range(10):
                    if ctx.is_cancelled:
                        yield StepResult.cancelled("Cancelled")
                        return
                    yield ProgressUpdate(i, 10, f"Tick {i}")
                yield StepResult.success("Done")

        pipeline = Pipeline("cancel_pipeline", steps=[LongRunningStep()])
        ctx = PipelineContext(bpy.context)

        results = []
        for idx, item in enumerate(pipeline.execute_iter(ctx)):
            if idx == 2:
                ctx.is_cancelled = True
            if isinstance(item, StepResult):
                results.append(item)

        self.assertTrue(len(results) > 0)
        self.assertEqual(results[-1].status, StepStatus.CANCELLED)

    def test_labpbr_template_recovers_incomplete_interface(self):
        """A stale complete flag must not expose a decoder without BSDF."""
        from utils.node_groups import ensure_all_templates

        decoder = ensure_all_templates()["LabPBR 1.3 Decoder"]
        decoder.interface.clear()
        decoder["mozi_template_complete"] = True

        recovered = ensure_all_templates()["LabPBR 1.3 Decoder"]
        output_names = [
            item.name for item in recovered.interface.items_tree
            if item.item_type == "SOCKET" and item.in_out == "OUTPUT"
        ]
        self.assertIn("BSDF", output_names)


def run_all_tests():
    print("=" * 60)
    print("Running MoziToolKit Pipeline Automated Unit Tests...")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestPipelineFramework))

    try:
        from tests.test_adaptive_pixel_split import TestAdaptivePixelSplit
        suite.addTests(loader.loadTestsFromTestCase(TestAdaptivePixelSplit))
    except Exception as e:
        print(f"[Warning] Could not load TestAdaptivePixelSplit: {e}")

    try:
        from tests.test_extrude_repair_atlas import TestExtrudeRepairAtlas
        suite.addTests(loader.loadTestsFromTestCase(TestExtrudeRepairAtlas))
    except Exception as e:
        print(f"[Warning] Could not load TestExtrudeRepairAtlas: {e}")

    try:
        from tests.test_dependencies import TestDependencyManager
        suite.addTests(loader.loadTestsFromTestCase(TestDependencyManager))
    except Exception as e:
        print(f"[Warning] Could not load TestDependencyManager: {e}")

    try:
        from tests.test_material_reconstruction_and_replacement import (
            TestUVTransformMath,
            TestMaterialModeDetection,
            TestCrossModeMaterialReplacement,
            TestAnimatedUVMapping,
        )
        suite.addTests(loader.loadTestsFromTestCase(TestUVTransformMath))
        suite.addTests(loader.loadTestsFromTestCase(TestMaterialModeDetection))
        suite.addTests(loader.loadTestsFromTestCase(TestCrossModeMaterialReplacement))
        suite.addTests(loader.loadTestsFromTestCase(TestAnimatedUVMapping))
    except Exception as e:
        print(f"[Warning] Could not load TestMaterialReconstructionAndReplacement: {e}")

    try:
        from tests.test_replace_material_atlas import TestReplaceMaterialAtlasMode
        suite.addTests(loader.loadTestsFromTestCase(TestReplaceMaterialAtlasMode))
    except Exception as e:
        print(f"[Warning] Could not load TestReplaceMaterialAtlasMode: {e}")

    try:
        from tests.test_jmc2obj_matching import TestJmc2objMatching
        suite.addTests(loader.loadTestsFromTestCase(TestJmc2objMatching))
    except Exception as e:
        print(f"[Warning] Could not load TestJmc2objMatching: {e}")

    try:
        from tests.test_mineways_matching import TestMinewaysMatching
        suite.addTests(loader.loadTestsFromTestCase(TestMinewaysMatching))
    except Exception as e:
        print(f"[Warning] Could not load TestMinewaysMatching: {e}")

    try:
        from tests.test_generate_atlas import TestAtlasGenerator
        suite.addTests(loader.loadTestsFromTestCase(TestAtlasGenerator))
    except Exception as e:
        print(f"[Warning] Could not load TestAtlasGenerator: {e}")

    try:
        from tests.test_pack_model_atlas_integration import TestPackModelAtlasIntegration
        suite.addTests(loader.loadTestsFromTestCase(TestPackModelAtlasIntegration))
    except Exception as e:
        print(f"[Warning] Could not load TestPackModelAtlasIntegration: {e}")

    try:
        from tests.test_code_review_fixes import TestCodeReviewFixes
        suite.addTests(loader.loadTestsFromTestCase(TestCodeReviewFixes))
    except Exception as e:
        print(f"[Warning] Could not load TestCodeReviewFixes: {e}")

    try:
        from tests.test_atlas_uv_tiling import TestAtlasUVTiling
        suite.addTests(loader.loadTestsFromTestCase(TestAtlasUVTiling))
    except Exception as e:
        print(f"[Warning] Could not load TestAtlasUVTiling: {e}")

    try:
        from tests.test_atlas_uv_rotation import TestAtlasUVRotation
        suite.addTests(loader.loadTestsFromTestCase(TestAtlasUVRotation))
    except Exception as e:
        print(f"[Warning] Could not load TestAtlasUVRotation: {e}")

    try:
        from tests.test_p0_fixes import TestP0Fixes
        suite.addTests(loader.loadTestsFromTestCase(TestP0Fixes))
    except Exception as e:
        print(f"[Warning] Could not load TestP0Fixes: {e}")

    try:
        from tests.test_importer_matching_benchmark import TestImporterModelMatching
        suite.addTests(loader.loadTestsFromTestCase(TestImporterModelMatching))
    except Exception as e:
        print(f"[Warning] Could not load TestImporterModelMatching: {e}")

    try:
        from tests.test_biome_materials import (
            TestBiomeColors,
            TestBiomeResolver,
            TestBiomeNodeGroups,
            TestBiomeMaterialBuilding,
            TestBiomePipelineIntegration,
        )
        suite.addTests(loader.loadTestsFromTestCase(TestBiomeColors))
        suite.addTests(loader.loadTestsFromTestCase(TestBiomeResolver))
        suite.addTests(loader.loadTestsFromTestCase(TestBiomeNodeGroups))
        suite.addTests(loader.loadTestsFromTestCase(TestBiomeMaterialBuilding))
        suite.addTests(loader.loadTestsFromTestCase(TestBiomePipelineIntegration))
    except Exception as e:
        print(f"[Warning] Could not load TestBiomeMaterials: {e}")

    try:
        from tests.test_standalone_animated_pbr import TestStandaloneAnimatedPBR
        suite.addTests(loader.loadTestsFromTestCase(TestStandaloneAnimatedPBR))
    except Exception as e:
        print(f"[Warning] Could not load TestStandaloneAnimatedPBR: {e}")

    try:
        from tests.test_atlas_material_metadata import TestAtlasMaterialMetadata
        suite.addTests(loader.loadTestsFromTestCase(TestAtlasMaterialMetadata))
    except Exception as e:
        print(f"[Warning] Could not load TestAtlasMaterialMetadata: {e}")

    try:
        from tests.test_replace_material_point_cloud import TestReplaceMaterialPointCloud
        suite.addTests(loader.loadTestsFromTestCase(TestReplaceMaterialPointCloud))
    except Exception as e:
        print(f"[Warning] Could not load TestReplaceMaterialPointCloud: {e}")

    try:
        from tests.test_mc_model_baker import TestMCModelBaker
        suite.addTests(loader.loadTestsFromTestCase(TestMCModelBaker))
    except Exception as e:
        print(f"[Warning] Could not load TestMCModelBaker: {e}")

    try:
        from tests.test_jar_model_baker import TestJarModelBaker
        suite.addTests(loader.loadTestsFromTestCase(TestJarModelBaker))
    except Exception as e:
        print(f"[Warning] Could not load TestJarModelBaker: {e}")

    try:
        from tests.test_mozi_yefira_integration import TestMoziYefiraIntegration
        suite.addTests(loader.loadTestsFromTestCase(TestMoziYefiraIntegration))
    except Exception as e:
        print(f"[Warning] Could not load TestMoziYefiraIntegration: {e}")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("\n✅ ALL TESTS PASSED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print("\n❌ SOME TESTS FAILED!")
        if result.failures:
            print("\n--- FAILURES ---")
            for test, err in result.failures:
                print(f"FAILED: {test}\n{err}\n")
        if result.errors:
            print("\n--- ERRORS ---")
            for test, err in result.errors:
                print(f"ERROR: {test}\n{err}\n")
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()
