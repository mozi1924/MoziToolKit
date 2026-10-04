import os
import sys
import gzip
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock
import types

PROJECT_DIR = Path(__file__).parent.parent.resolve()
site_pkgs = PROJECT_DIR / "site-packages"
for p in [str(site_pkgs), str(PROJECT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

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

import libmtk_py


class TestDebugWorldBakeValidation(unittest.TestCase):
    """Validates model baking hit-rate and Blender mesh ingestion for blocks from the full debug world dump."""

    @classmethod
    def setUpClass(cls):
        cls.fixture_path = Path("/home/mozi/libmozitoolkit/crates/mtk-voxel/assets/debug_world_snapshot.json.gz")
        if not cls.fixture_path.exists():
            raise unittest.SkipTest(f"Fixture {cls.fixture_path} not found")

        with gzip.open(cls.fixture_path, "rt", encoding="utf-8") as f:
            data = json.load(f)

        blocks = data.get("blocks", [])
        cls.unique_states = sorted(list(set(b["state"] for b in blocks)))

        # Load vanilla resource pack stack
        cls.vanilla_jar = Path(os.path.expanduser("~/26.2-Fabric.jar"))
        if not cls.vanilla_jar.exists():
            cls.vanilla_jar = Path("/home/mozi/mc")
        if not cls.vanilla_jar.exists():
            raise unittest.SkipTest("No vanilla jar or assets directory found")

        cls.stack = libmtk_py.ResourcePackStack()
        if cls.vanilla_jar.is_file():
            cls.stack.add_zip_pack(str(cls.vanilla_jar))
        else:
            cls.stack.add_directory_pack(str(cls.vanilla_jar))

        baker = libmtk_py.ModelBaker()
        cls.db = baker.bake_all(cls.stack)

    def test_entity_blocks_hit_rate(self):
        """Verifies that 100% of all map-making entity block states in the dump resolve with geometry."""
        entity_keywords = ["chest", "bell", "skull", "head", "bed", "shulker_box", "sign", "pot", "portal"]
        entity_states = [
            s for s in self.unique_states
            if any(k in s for k in entity_keywords)
        ]
        self.assertGreater(len(entity_states), 2000, "Dump must contain >2000 entity block states")

        hits = 0
        empty = []
        for s in entity_states:
            res = self.db.get_mesh(s, False)
            if res is not None and res[0].face_count > 0:
                hits += 1
            else:
                empty.append(s)

        hit_rate = (hits / len(entity_states)) * 100.0
        self.assertEqual(
            hits, len(entity_states),
            f"All entity blocks must have geometry. Missing {len(empty)}: {empty[:10]} (hit rate: {hit_rate:.1f}%)"
        )

    def test_chest_orientation_in_debug_dump(self):
        """Validates that chest orientations from debug dump produce distinct rotated geometry."""
        single_chests = [
            s for s in self.unique_states
            if s.startswith("minecraft:chest[") and "type=single" in s and "waterlogged=false" in s
        ]
        # Expect north, south, east, west
        facings = {}
        for s in single_chests:
            for facing in ["north", "south", "east", "west"]:
                if f"facing={facing}" in s:
                    res = self.db.get_mesh(s, False)
                    self.assertIsNotNone(res)
                    facings[facing] = res[0].get_flat_positions()

        self.assertEqual(len(facings), 4, "Must find all 4 horizontal facings for chest in dump")
        self.assertNotEqual(facings["north"], facings["south"])
        self.assertNotEqual(facings["north"], facings["east"])
        self.assertNotEqual(facings["east"], facings["west"])

    def test_overall_dump_hit_rate_exceeds_threshold(self):
        """Overall hit rate on 32k+ states must exceed 97% (remaining are air/light/invisible blocks)."""
        hits = 0
        for s in self.unique_states:
            res = self.db.get_mesh(s, False)
            if res is not None and res[0].face_count > 0:
                hits += 1

        total = len(self.unique_states)
        hit_pct = (hits / total) * 100.0
        self.assertGreater(
            hit_pct, 97.0,
            f"Overall debug world hit rate must exceed 97%, got {hit_pct:.2f}% ({hits}/{total})"
        )

    def test_blender_mesh_ingestion_for_entity_blocks(self):
        """Under native Blender, validates that baked models convert into valid Blender mesh objects."""
        if not HAS_BPY:
            self.skipTest("Requires native Blender host environment")

        sample_entity_blocks = [
            "minecraft:chest[facing=north,type=single,waterlogged=false]",
            "minecraft:chest[facing=south,type=left,waterlogged=false]",
            "minecraft:skeleton_skull[rotation=0]",
            "minecraft:skeleton_wall_skull[facing=north]",
            "minecraft:dragon_head[rotation=0]",
            "minecraft:bell[attachment=floor,facing=north]",
            "minecraft:red_bed[facing=north,occupied=false,part=foot]",
            "minecraft:shulker_box[facing=up]",
            "minecraft:oak_sign[rotation=0,waterlogged=false]",
            "minecraft:decorated_pot[facing=north,waterlogged=false]",
        ]

        for s in sample_entity_blocks:
            res = self.db.get_mesh(s, False)
            self.assertIsNotNone(res, f"Block {s} must resolve")
            mesh_data, textures = res
            self.assertGreater(mesh_data.vertex_count, 0, f"Block {s} must have vertices")
            self.assertGreater(mesh_data.face_count, 0, f"Block {s} must have faces")

            # Create native Blender mesh and populate
            mesh_name = f"Test_{s.split('[')[0].replace('minecraft:', '')}"
            b_mesh = bpy.data.meshes.new(mesh_name)

            positions = mesh_data.get_flat_positions()
            q_indices = mesh_data.get_quad_indices()

            verts = [(positions[i], positions[i+1], positions[i+2]) for i in range(0, len(positions), 3)]
            faces = [q_indices[i:i+4] for i in range(0, len(q_indices), 4)]

            b_mesh.from_pydata(verts, [], faces)
            b_mesh.update()

            self.assertEqual(len(b_mesh.vertices), len(verts), f"Blender mesh {mesh_name} vertex count mismatch")
            self.assertEqual(len(b_mesh.polygons), len(faces), f"Blender mesh {mesh_name} polygon count mismatch")

            # Clean up test datablock
            bpy.data.meshes.remove(b_mesh)


if __name__ == "__main__":
    unittest.main()
