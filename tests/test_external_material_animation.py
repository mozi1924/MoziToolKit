"""
Regression tests for animated material routing on externally imported meshes.

Covers the full Replace Material -> animated chunk -> atlas UV -> provenance
restore cycle, including toggling the animated-texture preference after the
first replacement.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
libmtk_release_path = PARENT_DIR / "libmozitoolkit" / "target" / "release"

for p in [str(libmtk_release_path), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import bpy
    HAS_BPY = (
        not isinstance(bpy, MagicMock)
        and hasattr(bpy, "data")
        and hasattr(bpy.data, "meshes")
        and not isinstance(bpy.data, MagicMock)
    )
except ImportError:
    HAS_BPY = False


def _write_dummy_png(path: Path):
    if HAS_BPY:
        img = bpy.data.images.new(path.name, width=16, height=64)
        img.filepath_raw = str(path)
        img.file_format = "PNG"
        img.save()
        bpy.data.images.remove(img)
    else:
        path.write_bytes(b"\x89PNG\r\n\x1a\n")


ATLAS_MAPPING = {
    "chunks": [
        {
            "chunk_id": 0,
            "category": "blocks",
            "is_animated": False,
            "category_chunk_index": 1,
            "width": 1024,
            "height": 1024,
            "has_normal": False,
            "has_specular": False,
        },
        {
            "chunk_id": 1,
            "category": "blocks",
            "is_animated": True,
            "category_chunk_index": 1,
            "width": 1024,
            "height": 1024,
            "has_normal": False,
            "has_specular": False,
        },
    ],
    "sprites": {
        "minecraft:block/water_still": {
            "chunk_id": 0,
            "category": "blocks",
            "is_animated": False,
            "texture_id": 10,
            "uv_bounds": [0.0, 0.0, 0.25, 0.25],
            "frame_0_uv_bounds": [0.0, 0.0, 0.25, 0.25],
            "local_uv_bounds": [0.0, 0.0, 1.0, 1.0],
            "pixel_rect": [0, 0, 16, 16],
            "strip_pixel_rect": [0, 0, 16, 64],
            "frame_size": [16, 16],
            "frame_count": 1,
            "has_normal": False,
            "has_specular": False,
        }
    },
    "anim_sprites": {
        "minecraft:block/water_still": {
            "chunk_id": 1,
            "category": "blocks",
            "is_animated": True,
            "texture_id": 11,
            "uv_bounds": [0.5, 0.75, 1.0, 1.0],
            "frame_0_uv_bounds": [0.5, 0.75, 1.0, 1.0],
            "local_uv_bounds": [0.0, 0.0, 1.0, 1.0],
            "pixel_rect": [0, 0, 16, 16],
            "strip_pixel_rect": [0, 0, 16, 64],
            "frame_uv_step": [0.0, 0.25],
            "frame_size": [16, 16],
            "frame_count": 4,
            "animation": {"frametime": 2, "interpolate": True},
            "has_normal": False,
            "has_specular": False,
        }
    },
}


@unittest.skipUnless(HAS_BPY, "Requires active Blender bpy environment")
class TestExternalMaterialAnimation(unittest.TestCase):
    def _make_cache(self, root: Path) -> Path:
        cache_dir = root / "cache"
        atlas_dir = cache_dir / "atlas"
        colormaps_dir = cache_dir / "colormaps"
        atlas_dir.mkdir(parents=True, exist_ok=True)
        colormaps_dir.mkdir(parents=True, exist_ok=True)

        _write_dummy_png(atlas_dir / "blocks_chunk_001.png")
        _write_dummy_png(atlas_dir / "blocks_anim_chunk_001.png")
        for name in ("grass", "foliage", "water"):
            _write_dummy_png(colormaps_dir / f"{name}.png")

        (atlas_dir / "atlas_mapping.json").write_text(
            json.dumps(ATLAS_MAPPING), encoding="utf-8"
        )

        from MoziToolKit.bridge.engine import get_libmtk

        mtk = get_libmtk()
        testing = getattr(getattr(mtk, "unstable", None), "testing", None) if mtk else None
        if testing is not None and hasattr(testing, "create_test_cache_package"):
            testing.create_test_cache_package(
                str(cache_dir / "animstackfp.mtkcache"), "animstackfp", 0
            )
        return cache_dir

    def test_external_replace_and_restore_animation_toggle(self):
        from MoziToolKit.utils.materials.pipeline import (
            replace_materials,
            restore_materials_from_provenance,
        )

        bpy.ops.mesh.primitive_cube_add(size=2.0)
        obj = bpy.context.active_object
        mesh = obj.data
        src_mat = bpy.data.materials.new(name="minecraft:block/water_still")
        mesh.materials.append(src_mat)

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = self._make_cache(Path(tmpdir))
            with patch.dict(os.environ, {"MOZI_CACHE_DIR": str(cache_dir)}), patch(
                "MoziToolKit.utils.materials.pipeline.get_cache_dir", return_value=cache_dir
            ):
                res = replace_materials(obj, mode="ATLAS", origin="AUTO", biome="PLAINS")
                self.assertTrue(res["success"])
                self.assertTrue(res["enable_animated_textures"])
                self.assertEqual(res["animated_faces"], len(mesh.polygons))
                self.assertEqual(mesh.materials[0].name, "MTK:Atlas:Ext:anim:blocks:001")
                self.assertTrue(mesh["mtk_enable_animated_textures"])

                timing = mesh.attributes["mtk_anim_timing"]
                self.assertEqual(tuple(timing.data[0].vector), (4.0, 2.0, 1.0))
                frame_size = mesh.attributes["mtk_anim_frame_size"]
                self.assertEqual(tuple(frame_size.data[0].vector), (16.0, 16.0, 0.0))
                chunk_ids = [d.value for d in mesh.attributes["mtk_atlas_chunk_id"].data]
                self.assertTrue(all(cid == 1 for cid in chunk_ids))

                # Toggle animated textures off and rebuild from provenance.
                prefs_off = SimpleNamespace(enable_animated_textures=False)
                restored = restore_materials_from_provenance(
                    obj,
                    mode="ATLAS",
                    biome="PLAINS",
                    prefs=prefs_off,
                    reconcile_animation=True,
                    enable_animated_textures=False,
                )
                self.assertTrue(restored["success"])
                self.assertTrue(restored["animation_reconciled"])
                self.assertEqual(mesh.materials[0].name, "MTK:Atlas:Ext:blocks:001")
                self.assertFalse(mesh["mtk_enable_animated_textures"])
                chunk_ids = [d.value for d in mesh.attributes["mtk_atlas_chunk_id"].data]
                self.assertTrue(all(cid == 0 for cid in chunk_ids))
                self.assertNotIn("mtk_anim_timing", mesh.attributes)
                self.assertNotIn("mtk_anim_frame_size", mesh.attributes)

                # And back on again, still without the original local UVs.
                prefs_on = SimpleNamespace(enable_animated_textures=True)
                restored_on = restore_materials_from_provenance(
                    obj,
                    mode="ATLAS",
                    biome="PLAINS",
                    prefs=prefs_on,
                    reconcile_animation=True,
                    enable_animated_textures=True,
                )
                self.assertTrue(restored_on["success"])
                self.assertEqual(mesh.materials[0].name, "MTK:Atlas:Ext:anim:blocks:001")
                self.assertTrue(mesh["mtk_enable_animated_textures"])
                timing = mesh.attributes["mtk_anim_timing"]
                self.assertEqual(tuple(timing.data[0].vector), (4.0, 2.0, 1.0))

    def test_external_replace_with_animation_disabled(self):
        from MoziToolKit.utils.materials.pipeline import replace_materials

        bpy.ops.mesh.primitive_cube_add(size=2.0)
        obj = bpy.context.active_object
        mesh = obj.data
        src_mat = bpy.data.materials.new(name="minecraft:block/water_still")
        mesh.materials.append(src_mat)

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = self._make_cache(Path(tmpdir))
            prefs_off = SimpleNamespace(enable_animated_textures=False)
            with patch.dict(os.environ, {"MOZI_CACHE_DIR": str(cache_dir)}), patch(
                "MoziToolKit.utils.materials.pipeline.get_cache_dir", return_value=cache_dir
            ):
                res = replace_materials(
                    obj,
                    mode="ATLAS",
                    origin="AUTO",
                    biome="PLAINS",
                    prefs=prefs_off,
                )
                self.assertTrue(res["success"])
                self.assertFalse(res["enable_animated_textures"])
                self.assertEqual(res["animated_faces"], 0)
                self.assertEqual(mesh.materials[0].name, "MTK:Atlas:Ext:blocks:001")
                self.assertFalse(mesh["mtk_enable_animated_textures"])
                self.assertNotIn("mtk_anim_timing", mesh.attributes)
                self.assertNotIn("mtk_anim_frame_size", mesh.attributes)


if __name__ == "__main__":
    unittest.main()
