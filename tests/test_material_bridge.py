"""
Unit tests for bridge/material.py and rule compliance verification.
Validates that material, biome, and atlas functions are properly routed through bridge/material.py
without direct libmtk_py imports in operators/, ui/, or utils/.
"""

import ast
from pathlib import Path
import unittest

from MoziToolKit.bridge.material import (
    BiomeResolver,
    GridAtlasSpec,
    MaterialResolver,
    clean_material_name,
    compute_biome_tint_attributes,
    get_all_biomes,
    get_biome_meta,
    is_material_bridge_available,
    load_baked_atlas_from_json,
)


class TestMaterialBridge(unittest.TestCase):
    def test_bridge_availability(self):
        """Verify bridge availability check returns boolean without errors."""
        avail = is_material_bridge_available()
        self.assertIsInstance(avail, bool)

    def test_biome_metadata(self):
        """Verify canonical biome metadata."""
        meta = get_biome_meta("plains")
        self.assertIn("temperature", meta)
        self.assertIn("humidity", meta)
        self.assertIn("grass_linear", meta)

    def test_get_all_biomes(self):
        """Verify list of biomes is returned with valid structures."""
        biomes = get_all_biomes()
        self.assertGreater(len(biomes), 0)
        first = biomes[0]
        self.assertIn("id", first)
        self.assertIn("name", first)

    def test_clean_material_name(self):
        """Verify material identifier stem cleaning."""
        cleaned = clean_material_name("minecraft:block/stone_diffuse.png")
        self.assertIn("stone", cleaned)
        self.assertFalse(cleaned.endswith(".png"))

    def test_grid_atlas_spec_instantiation(self):
        """Verify GridAtlasSpec can be constructed via bridge."""
        spec = GridAtlasSpec(
            swatch_size=18.0,
            tile_size=16.0,
            border=1.0,
            image_width=1024,
            image_height=1024,
        )
        self.assertIsNotNone(spec)

    def test_build_material_palette(self):
        """Verify building material palette and face indices via bridge.material."""
        import numpy as np
        from MoziToolKit.bridge.material import build_material_palette
        slot_names = ["stone", "dirt"]
        slot_is_mtk = [False, False]
        slot_source_ids = ["", ""]
        poly_mats = np.array([0, 1, 0, 1], dtype=np.int32)
        palette, indices = build_material_palette(
            slot_names,
            slot_is_mtk,
            slot_source_ids,
            poly_mats,
        )
        self.assertEqual(palette, ["stone", "dirt"])
        self.assertEqual(list(indices), [0, 1, 0, 1])

    def test_get_chunk_texture_specs_authoritative(self):
        """Verify get_chunk_texture_specs uses the authoritative textures list when present."""
        from MoziToolKit.bridge.material import get_chunk_texture_specs
        cm = {
            "chunk_id": 0,
            "category": "blocks",
            "textures": [
                {"role": "albedo", "file_name": "blocks_chunk_001.png", "colorspace": "sRGB"},
                {"role": "orm", "file_name": "blocks_chunk_001_orm.png", "colorspace": "Non-Color"},
            ],
        }
        specs = get_chunk_texture_specs(cm)
        self.assertEqual(len(specs), 2)
        self.assertEqual(specs[0]["role"], "albedo")
        self.assertEqual(specs[1]["role"], "orm")

    def test_get_chunk_texture_specs_legacy_fallback(self):
        """Verify get_chunk_texture_specs falls back to channel flags for legacy metadata."""
        from MoziToolKit.bridge.material import get_chunk_texture_specs
        cm = {
            "chunk_id": 1,
            "category": "blocks",
            "category_chunk_index": 2,
            "is_animated": True,
            "has_normal": True,
            "has_orm": True,
        }
        specs = get_chunk_texture_specs(cm)
        roles = [s["role"] for s in specs]
        self.assertIn("albedo", roles)
        self.assertIn("normal", roles)
        self.assertIn("orm", roles)
        normal_spec = next(s for s in specs if s["role"] == "normal")
        self.assertEqual(normal_spec["file_name"], "blocks_anim_chunk_002_n.png")
        self.assertEqual(normal_spec["colorspace"], "Non-Color")

    def test_resolve_chunk_texture_sources(self):
        """Verify resolve_chunk_texture_sources maps specs to file paths and memory getters."""
        from MoziToolKit.bridge.material import resolve_chunk_texture_sources
        cm = {
            "chunk_id": 0,
            "category": "blocks",
            "category_chunk_index": 1,
            "has_normal": True,
        }
        atlas_dir = Path("/tmp/fake_atlas")
        sources = resolve_chunk_texture_sources(cm, atlas_dir=atlas_dir)
        self.assertIn("albedo", sources)
        self.assertIn("normal", sources)
        self.assertEqual(sources["albedo"]["source"], atlas_dir / "blocks_chunk_001.png")
        self.assertEqual(sources["albedo"]["colorspace"], "sRGB")
        self.assertEqual(sources["normal"]["source"], atlas_dir / "blocks_chunk_001_n.png")
        self.assertEqual(sources["normal"]["colorspace"], "Non-Color")

    def test_no_direct_libmtk_py_in_utils_materials(self):
        """Rule compliance check: ensure utils/materials does not directly import libmtk_py."""
        toolkit_root = Path(__file__).parent.parent
        materials_dir = toolkit_root / "utils" / "materials"

        for py_file in materials_dir.rglob("*.py"):
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotEqual(
                            alias.name,
                            "libmtk_py",
                            f"Direct 'import libmtk_py' found in {py_file.relative_to(toolkit_root)} at line {node.lineno}",
                        )
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(
                        node.module,
                        "libmtk_py",
                        f"Direct 'from libmtk_py import ...' found in {py_file.relative_to(toolkit_root)} at line {node.lineno}",
                    )


if __name__ == "__main__":
    unittest.main()
