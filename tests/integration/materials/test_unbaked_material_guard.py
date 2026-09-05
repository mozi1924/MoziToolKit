"""
Test suite for unbaked material enforcement:
- Replace Material pipeline fails when unbaked and prompts user to precompile in preferences
- Live Sync fails when unbaked and prompts user to precompile in preferences
- Live Sync does NOT generate fake / dummy Principled BSDF placeholder materials
"""

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
PARENT_DIR = _REPO_ROOT.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

import bpy
from MoziToolKit.pipeline.presets import run_preset_pipeline
from MoziToolKit.utils.materials.pack import ResourcePackStack
from MoziToolKit.utils.system.menu_config import save_pack_stack_config
from utils.live_sync.material import LiveSyncMaterialManager


class TestUnbakedMaterialGuard(unittest.TestCase):

    def setUp(self):
        self.cube = bpy.data.objects.new("Guard_Cube", bpy.data.meshes.new("Guard_Cube_Mesh"))
        bpy.context.collection.objects.link(self.cube)
        mat = bpy.data.materials.new(name="stone")
        self.cube.data.materials.append(mat)

    def tearDown(self):
        if self.cube and self.cube.name in bpy.data.objects:
            bpy.data.objects.remove(self.cube, do_unlink=True)
        for m in list(bpy.data.materials):
            if m.name.startswith("MC_Atlas_Chunk_") or m.name == "stone":
                bpy.data.materials.remove(m, do_unlink=True)

    def test_replace_material_pipeline_fails_when_unbaked_atlas(self):
        """Pipeline replace_material must fail and prompt when stack is unbaked in Atlas mode."""
        import tempfile
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp_dir:
            p_dir = Path(tmp_dir)
            tex_dir = p_dir / "assets/minecraft/textures/block"
            tex_dir.mkdir(parents=True, exist_ok=True)
            Image.new("RGBA", (16, 16), (128, 128, 128, 255)).save(tex_dir / "stone.png")

            stack = ResourcePackStack([p_dir])
            self.assertFalse(stack.is_stack_baked())

            res, ctx = run_preset_pipeline(
                "replace_material",
                bpy.context,
                params={"pack_stack": stack, "material_mode": "ATLAS", "use_cache": True},
                target_objects=[self.cube],
            )
            self.assertFalse(res.is_success)
            self.assertIn("Precompile / Rebuild Stack Atlas Cache", res.message)

    def test_replace_material_pipeline_fails_when_unbaked_standalone(self):
        """Pipeline replace_material must fail and prompt when stack is unbaked in Standalone mode."""
        import tempfile
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp_dir:
            p_dir = Path(tmp_dir)
            tex_dir = p_dir / "assets/minecraft/textures/block"
            tex_dir.mkdir(parents=True, exist_ok=True)
            Image.new("RGBA", (16, 16), (128, 128, 128, 255)).save(tex_dir / "stone.png")

            stack = ResourcePackStack([p_dir])
            self.assertFalse(stack.is_standalone_baked())

            res, ctx = run_preset_pipeline(
                "replace_material",
                bpy.context,
                params={"pack_stack": stack, "material_mode": "STANDALONE", "use_cache": True},
                target_objects=[self.cube],
            )
            self.assertFalse(res.is_success)
            self.assertIn("Precompile / Rebuild Stack Atlas Cache", res.message)

    def test_live_sync_operator_succeeds_without_precompiled_materials(self):
        """MOZI_OT_sync_rebuild_world should not fail due to unbaked materials, allowing untextured sync."""
        import tempfile
        from PIL import Image
        from utils.materials import is_material_cache_ready

        with tempfile.TemporaryDirectory() as tmp_dir:
            p_dir = Path(tmp_dir)
            tex_dir = p_dir / "assets/minecraft/textures/block"
            tex_dir.mkdir(parents=True, exist_ok=True)
            from MoziToolKit.utils.system.menu_config import save_pack_stack_config
            from MoziToolKit.utils.materials.pack import clear_resource_pack_cache
            from MoziToolKit.utils.materials import is_material_cache_ready
            save_pack_stack_config([{"name": "TestPack", "path": str(p_dir), "enabled": True, "pack_type": "RESOURCE_PACK"}])
            clear_resource_pack_cache()

            # Material cache is not ready
            self.assertFalse(is_material_cache_ready(force_refresh=True))

            # sync_rebuild_world should not raise unbaked error
            try:
                bpy.ops.mozi.sync_rebuild_world()
            except RuntimeError as e:
                self.assertNotIn("Precompile / Rebuild Stack Atlas Cache", str(e))

    def test_live_sync_material_manager_never_creates_dummy_placeholder_materials(self):
        """LiveSyncMaterialManager must not synthesize placeholder Principled BSDF materials when unbaked."""
        for m in list(bpy.data.materials):
            if m.name.startswith("MC_Atlas_Chunk_"):
                bpy.data.materials.remove(m, do_unlink=True)

        mgr = LiveSyncMaterialManager(world_obj=self.cube)
        self.assertEqual(len(mgr.chunk_materials), 0)

        # No dummy materials should have been added to bpy.data.materials
        dummy_mats = [m.name for m in bpy.data.materials if m.name.startswith("MC_Atlas_Chunk_")]
        self.assertEqual(len(dummy_mats), 0)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
