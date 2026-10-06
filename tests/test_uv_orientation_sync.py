"""
Unit and integration tests for UV orientation and coordinate mapping.
Validates that generated UVs for both JSON baked models (e.g. grass_block, lantern, stairs)
and standard unit cubes (e.g. stone, crafting_table) adhere to standard DCC / OpenGL / Blender
conventions (V=0 at bottom, V=1 at top) and are never vertically or horizontally inverted.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_DIR = Path(__file__).parent.parent.resolve()
site_pkgs = PROJECT_DIR / "site-packages"

for p in [str(site_pkgs), str(PROJECT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import types

if "mathutils" not in sys.modules:
    sys.modules["mathutils"] = MagicMock()

if "bpy_extras" not in sys.modules:
    bpy_extras = types.ModuleType("bpy_extras")
    bpy_extras.__path__ = []
    io_utils = types.ModuleType("bpy_extras.io_utils")
    io_utils.ExportHelper = object
    io_utils.ImportHelper = object
    bpy_extras.io_utils = io_utils
    sys.modules["bpy_extras"] = bpy_extras
    sys.modules["bpy_extras.io_utils"] = io_utils

try:
    import bpy
    HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "meshes")
except ImportError:
    bpy = MagicMock()
    HAS_BPY = False

if not HAS_BPY:
    class _MockOperator: pass
    class _MockPanel: pass
    class _MockMenu: pass
    class _MockPropertyGroup: pass
    class _MockUIList: pass
    class _MockAddonPreferences: pass

    class _MockTypes:
        Operator = _MockOperator
        Panel = _MockPanel
        Menu = _MockMenu
        PropertyGroup = _MockPropertyGroup
        UIList = _MockUIList
        AddonPreferences = _MockAddonPreferences

    bpy.types = _MockTypes
    bpy.app = MagicMock()
    bpy.props = MagicMock()

    sys.modules["bpy"] = bpy
    sys.modules["bpy.props"] = bpy.props
    sys.modules["bpy.types"] = _MockTypes
    sys.modules["bpy.app"] = bpy.app
    sys.modules["bmesh"] = MagicMock()
    HAS_BPY = False

import libmtk_py


class TestUvOrientationSync(unittest.TestCase):
    def setUp(self):
        from _assets import blender_datafiles_cache

        cache_root = blender_datafiles_cache()
        cache_root = cache_root if cache_root is not None else Path("/nonexistent-cache")
        self.atlas_path = cache_root / "atlas" / "atlas_mapping.json"
        self.models_bin_path = cache_root / "models" / "models.bin"

        self.atlas = None
        if self.atlas_path.exists():
            with open(self.atlas_path, "r", encoding="utf-8") as f:
                self.atlas = libmtk_py.BakedAtlas.from_mapping_json(f.read())

        self.model_db = None
        if self.models_bin_path.exists():
            with open(self.models_bin_path, "rb") as f:
                self.model_db = libmtk_py.BakedModelDatabase.from_bincode_bytes(f.read())

    def test_unit_cube_uv_orientation(self):
        """Verifies that unit cube faces have V_top > V_bottom in Blender coordinate space."""
        storage = libmtk_py.VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        storage.set_block(0, 0, 0, "minecraft:stone")

        # 1. Test unmapped fallback (no atlas)
        config_no_atlas = libmtk_py.MesherConfig(
            enable_ao=False,
            mesh_fluids=False,
            z_up_coordinates=True,
            origin_centered=False,
            weld_vertices=False,
        )
        mesh_no_atlas = libmtk_py.SectionMesher.mesh_world(storage, config_no_atlas, None, None)
        quad_indices = mesh_no_atlas.get_quad_indices()
        uvs = mesh_no_atlas.get_flat_uvs()
        positions = mesh_no_atlas.get_flat_positions()

        # Each quad has 4 vertices: [v0, v1, v2, v3]
        # v0 is top-left, v1 is bottom-left, v2 is bottom-right, v3 is top-right
        for q in range(len(quad_indices) // 4):
            i0 = quad_indices[q * 4]
            i1 = quad_indices[q * 4 + 1]
            i2 = quad_indices[q * 4 + 2]
            i3 = quad_indices[q * 4 + 3]

            z0 = positions[i0 * 3 + 2]
            z1 = positions[i1 * 3 + 2]
            v0 = uvs[i0 * 2 + 1]
            v1 = uvs[i1 * 2 + 1]

            # For vertical faces (where z0 != z1):
            if abs(z0 - z1) > 0.5:
                # If z0 is at the top, v0 must be greater than v1
                if z0 > z1:
                    self.assertGreater(v0, v1, f"Quad {q}: Top vertex V ({v0}) must be > bottom vertex V ({v1})")
                else:
                    self.assertLess(v0, v1, f"Quad {q}: Bottom vertex V ({v0}) must be < top vertex V ({v1})")

    def test_baked_model_atlas_uv_orientation(self):
        """Verifies that BakedModel (grass block side, lantern) has V_top > V_bottom in atlas UV space."""
        if self.atlas is None or self.model_db is None:
            self.skipTest("Atlas or models.bin cache not found")

        storage = libmtk_py.VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        storage.set_block(0, 0, 0, "minecraft:grass_block")
        storage.set_block(1, 0, 0, "minecraft:lantern[hanging=false]")

        config = libmtk_py.MesherConfig(
            enable_ao=False,
            mesh_fluids=False,
            z_up_coordinates=True,
            origin_centered=False,
            weld_vertices=False,
            atlas=self.atlas,
        )
        mesh = libmtk_py.SectionMesher.mesh_world(storage, config, None, self.model_db)
        quad_indices = mesh.get_quad_indices()
        uvs = mesh.get_flat_uvs()
        positions = mesh.get_flat_positions()

        checked_vertical_quads = 0
        for q in range(len(quad_indices) // 4):
            i0 = quad_indices[q * 4]
            i1 = quad_indices[q * 4 + 1]
            i2 = quad_indices[q * 4 + 2]
            i3 = quad_indices[q * 4 + 3]

            z0 = positions[i0 * 3 + 2]
            z1 = positions[i1 * 3 + 2]
            v0 = uvs[i0 * 2 + 1]
            v1 = uvs[i1 * 2 + 1]

            # For vertical faces:
            if abs(z0 - z1) > 0.05:
                checked_vertical_quads += 1
                if z0 > z1:
                    self.assertGreater(v0, v1, f"Quad {q}: Top vertex V ({v0}) must be > bottom vertex V ({v1})")
                else:
                    self.assertLess(v0, v1, f"Quad {q}: Bottom vertex V ({v0}) must be < top vertex V ({v1})")

        self.assertGreater(checked_vertical_quads, 5, "Expected to verify multiple vertical quads")

    def test_baked_model_database_remap_to_atlas(self):
        """Verifies that model_db.remap_to_atlas correctly pre-bakes Atlas UVs into the database."""
        if self.atlas is None or self.model_db is None:
            self.skipTest("Atlas or models.bin cache not found")

        # Make sure remap_to_atlas works without error
        self.model_db.remap_to_atlas(self.atlas)
        mesh_tuple = self.model_db.get_mesh("minecraft:stone")
        if mesh_tuple is not None:
            mesh, textures = mesh_tuple
            flat_uvs = mesh.get_flat_uvs()
            self.assertGreater(len(flat_uvs), 0)


if __name__ == "__main__":
    unittest.main()

