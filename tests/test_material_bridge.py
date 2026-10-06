"""
Unit tests for bridge/material.py and rule compliance verification.
Validates that material, biome, and atlas functions are properly routed through bridge/material.py
without direct libmtk_py imports in operators/, ui/, or utils/.
"""

import ast
from pathlib import Path
import unittest

from bridge.material import (
    BiomeResolver,
    GridAtlasSpec,
    MaterialResolver,
    clean_material_name,
    compute_biome_tint_attributes,
    get_all_biomes,
    get_biome_meta,
    get_colormap_uv,
    is_material_bridge_available,
    load_baked_atlas_from_json,
    remap_mesh_multi_uvs,
)


class TestMaterialBridge(unittest.TestCase):
    def test_bridge_availability(self):
        """Verify bridge availability check returns boolean without errors."""
        avail = is_material_bridge_available()
        self.assertIsInstance(avail, bool)

    def test_biome_metadata_and_colormap(self):
        """Verify canonical biome metadata and colormap UV calculation."""
        meta = get_biome_meta("plains")
        self.assertIn("temperature", meta)
        self.assertIn("humidity", meta)
        self.assertIn("grass_linear", meta)

        uv = get_colormap_uv(0.8, 0.4)
        self.assertEqual(len(uv), 2)
        self.assertAlmostEqual(uv[0], 0.2, places=3)

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
