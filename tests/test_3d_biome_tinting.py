"""
Unit and integration tests for 3D Minecraft Biome Sampling, Tinting, and Smooth Blending (R=2).
Covers:
- Per-face biome array computation (`compute_biome_tint_attributes(..., face_biomes=...)`)
- 3D coordinate-based biome resolution from `VoxelStorage` (`compute_mesh_biome_attributes_from_storage`)
- Caves & Cliffs vertical biome separation (`lush_caves` at y=2 vs `dark_forest` at y=14 in the same X/Z column)
- Swamp 2D Perlin noise grass tint variation and `TINT_TYPE_HARDCODED` (4.0) shader routing
- `WORLD` biome preset in `BIOME_ENUM_ITEMS`, `update_object_biome`, and `resolve_and_apply_biome_tint`
"""

from pathlib import Path
import unittest
from unittest.mock import MagicMock

from MoziToolKit.bridge.engine import get_libmtk, has_libmtk
from MoziToolKit.bridge.material import (
    BiomeResolver,
    compute_biome_tint_attributes,
    compute_mesh_biome_attributes_from_storage,
)
from MoziToolKit.utils.materials.biome.biome import BIOME_ENUM_ITEMS
from MoziToolKit.utils.materials.biome.updater import (
    clear_biome_updater_cache,
    get_object_storage,
    mark_world_biome,
    register_object_storage,
    update_object_biome,
)
from MoziToolKit.ui.panel_biome import _get_object_biome, _resolve_biome_preset
from MoziToolKit.utils.materials.constants import (
    ATTR_BIOME_TINT_COLOR,
    ATTR_BIOME_TINT_DATA,
    ATTR_COLORMAP_UV,
    ATTR_SOURCE_TEXTURE_IDX,
)
from MoziToolKit.utils.materials.pipeline import resolve_and_apply_biome_tint


class _MockAttrElement:
    def __init__(self, val=0, color=None, vector=None):
        self.value = val
        self.color = color if color is not None else [0.0, 0.0, 0.0, 0.0]
        self.vector = vector if vector is not None else [0.0, 0.0, 0.0]


class _MockAttributeData(list):
    def foreach_get(self, prop, seq):
        for i, item in enumerate(self):
            if prop == "value":
                seq[i] = item.value
            elif prop == "color":
                for c_idx in range(4):
                    seq[i * 4 + c_idx] = item.color[c_idx]
            elif prop == "vector":
                for v_idx in range(3):
                    seq[i * 3 + v_idx] = item.vector[v_idx]

    def foreach_set(self, prop, seq):
        n = len(self)
        if prop == "value":
            for i in range(n):
                self[i].value = int(seq[i])
        elif prop == "color":
            for i in range(n):
                self[i].color = [float(seq[i * 4 + c]) for c in range(4)]
        elif prop == "vector":
            for i in range(n):
                self[i].vector = [float(seq[i * 3 + c]) for c in range(3)]


class _MockAttribute:
    def __init__(self, name, attr_type, domain, count):
        self.name = name
        self.data_type = attr_type
        self.domain = domain
        self.data = _MockAttributeData(_MockAttrElement() for _ in range(count))


class _MockAttributeGroup(dict):
    def __init__(self, poly_count):
        super().__init__()
        self._poly_count = poly_count

    def new(self, name, type, domain):
        attr = _MockAttribute(name, type, domain, self._poly_count)
        self[name] = attr
        return attr

    def remove(self, attr):
        self.pop(attr.name, None)


class _MockMesh(dict):
    def __init__(self, poly_count):
        super().__init__()
        self.polygons = [MagicMock(material_index=0) for _ in range(poly_count)]
        self.attributes = _MockAttributeGroup(poly_count)
        self.materials = []
        self._storage = None

    def update(self):
        pass


class _MockObject(dict):
    def __init__(self, mesh):
        super().__init__()
        self.type = "MESH"
        self.data = mesh
        self.material_slots = []
        self._storage = None


class Test3DBiomeTinting(unittest.TestCase):
    def setUp(self):
        if not has_libmtk():
            self.skipTest("Requires native libmtk_py")
        self.lib = get_libmtk()

    def test_world_in_biome_enum_items(self):
        """Verify 'WORLD' (3D World Biome) option is registered in BIOME_ENUM_ITEMS."""
        ids = [item[0] for item in BIOME_ENUM_ITEMS]
        self.assertIn("WORLD", ids)

    def test_per_face_biome_tint_attributes(self):
        """Verify compute_biome_tint_attributes supports per-face biome lists and custom tint routing."""
        keys = [
            "minecraft:block/grass_block_top",
            "minecraft:block/grass_block_top",
            "minecraft:block/grass_block_top",
        ]
        biomes = ["desert", "jungle", "badlands"]
        res = compute_biome_tint_attributes(
            keys,
            biome_preset="PLAINS",
            resolver=BiomeResolver(),
            face_biomes=biomes,
        )
        packed = res["packed_tint_data"]
        colors = res["tint_colors"]
        uvs = res["colormap_uvs"]

        self.assertEqual(len(packed), 3)
        self.assertEqual(len(colors), 3)
        self.assertEqual(len(uvs), 3)

        # Desert vs Jungle: standard colormap grass (tint_type == 1.0), distinct UVs & colors
        self.assertAlmostEqual(packed[0][3], 1.0)
        self.assertAlmostEqual(packed[1][3], 1.0)
        self.assertNotEqual(uvs[0], uvs[1])
        self.assertNotEqual(colors[0], colors[1])

        # Badlands: hardcoded custom grass override -> routed to TINT_TYPE_HARDCODED (4.0)
        self.assertAlmostEqual(packed[2][3], 4.0)

    def test_palette_biome_tint_matches_face_keys(self):
        """Palette + indices must produce byte-identical flat buffers to per-face keys."""
        import numpy as np

        keys = [
            "minecraft:block/grass_block_top",
            "minecraft:block/dirt",
            "minecraft:block/grass_block_top",
        ]
        palette = ["minecraft:block/grass_block_top", "minecraft:block/dirt"]
        indices = np.array([0, 1, 0], dtype=np.uint32)
        resolver = BiomeResolver()

        expected = compute_biome_tint_attributes(
            keys,
            biome_preset="JUNGLE",
            resolver=resolver,
        )
        expected = (expected["packed_tint_data"], expected["tint_colors"], expected["colormap_uvs"])
        packed, colors, uvs = self.lib.compute_biome_tint_attributes_paletted(
            palette,
            indices,
            "JUNGLE",
            resolver=resolver,
        )
        np.testing.assert_allclose(np.frombuffer(packed, dtype=np.float32).reshape(-1, 4), expected[0])
        np.testing.assert_allclose(np.frombuffer(colors, dtype=np.float32).reshape(-1, 4), expected[1])
        np.testing.assert_allclose(np.frombuffer(uvs, dtype=np.float32).reshape(-1, 3), expected[2])

    def test_3d_biome_attributes_from_storage(self):
        """Verify 3D vertical biome difference (lush_caves at y=2 vs dark_forest at y=14) in same X/Z column."""
        storage = self.lib.VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        storage.set_block(4, 2, 4, "minecraft:grass_block", "minecraft:lush_caves")
        storage.set_block(4, 14, 4, "minecraft:grass_block", "minecraft:dark_forest")

        self.assertEqual(storage.get_biome(4, 2, 4), "minecraft:lush_caves")
        self.assertEqual(storage.get_biome(4, 14, 4), "minecraft:dark_forest")

        res = compute_mesh_biome_attributes_from_storage(
            face_texture_keys=[
                "minecraft:block/grass_block_top",
                "minecraft:block/grass_block_top",
            ],
            block_xs=[4, 4],
            block_ys=[2, 14],
            block_zs=[4, 4],
            storage=storage,
            resolver=BiomeResolver(),
            smooth=True,
        )
        packed = res["packed_tint_data"]
        colors = res["tint_colors"]
        uvs = res["colormap_uvs"]

        # Bottom (lush_caves) vs Top (dark_forest) must have different grass colors
        self.assertNotEqual(colors[0], colors[1])
        self.assertNotEqual(uvs[0], uvs[1])
        # lush_caves uses standard colormap (1.0), dark_forest uses custom grass modifier (4.0)
        self.assertAlmostEqual(packed[0][3], 1.0)
        self.assertAlmostEqual(packed[1][3], 4.0)

    def test_swamp_perlin_noise_grass_tint(self):
        """Verify Swamp grass uses 2D Perlin noise dual-color palette and routes to TINT_TYPE_HARDCODED (4.0)."""
        storage = self.lib.VoxelStorage()
        storage.set_bounds(-64, 0, 0, 128, 16, 16)
        xs = list(range(-50, 50, 5))
        for x in xs:
            storage.set_block(x, 0, 0, "minecraft:grass_block", "minecraft:swamp")

        res = compute_mesh_biome_attributes_from_storage(
            face_texture_keys=["minecraft:block/grass_block_top"] * len(xs),
            block_xs=xs,
            block_ys=[0] * len(xs),
            block_zs=[0] * len(xs),
            storage=storage,
            resolver=BiomeResolver(),
            smooth=False,
        )
        packed = res["packed_tint_data"]
        colors = res["tint_colors"]

        for p in packed:
            self.assertAlmostEqual(p[3], 4.0)

        # Across -50..50, Perlin noise at scale 0.0225 crosses threshold -0.1, producing both swamp colors
        unique_colors = {tuple(round(c, 4) for c in col) for col in colors}
        self.assertGreaterEqual(len(unique_colors), 2)

    def test_world_biome_preset_in_pipeline_and_updater(self):
        """Verify resolve_and_apply_biome_tint and update_object_biome with biome='WORLD'."""
        storage = self.lib.VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        storage.set_block(2, 2, 2, "minecraft:grass_block", "minecraft:desert")
        storage.set_block(12, 14, 12, "minecraft:grass_block", "minecraft:jungle")

        mesh = _MockMesh(2)
        obj = _MockObject(mesh)
        obj._storage = storage
        obj["mtk:provenance_schema_version"] = 1

        # Populate coordinate attributes on mock mesh
        for name, vals in (("mtk_block_x", [2, 12]), ("mtk_block_y", [2, 14]), ("mtk_block_z", [2, 12])):
            attr = mesh.attributes.new(name=name, type="INT", domain="FACE")
            attr.data.foreach_set("value", vals)

        keys = ["minecraft:block/grass_block_top", "minecraft:block/grass_block_top"]
        resolve_and_apply_biome_tint(
            mesh_or_obj=obj,
            mesh=mesh,
            face_source_keys=keys,
            biome="WORLD",
            base_cache=Path("/tmp"),
        )

        self.assertEqual(obj.get("mtk:biome_preset"), "WORLD")
        self.assertIn(ATTR_BIOME_TINT_DATA, mesh.attributes)
        self.assertIn(ATTR_BIOME_TINT_COLOR, mesh.attributes)
        self.assertIn(ATTR_COLORMAP_UV, mesh.attributes)

        col0 = mesh.attributes[ATTR_BIOME_TINT_COLOR].data[0].color
        col1 = mesh.attributes[ATTR_BIOME_TINT_COLOR].data[1].color
        self.assertNotEqual(col0, col1)

        # Also test update_object_biome switching from PLAINS back to WORLD
        mat_mock = MagicMock()
        mat_mock.name = "mtk:grass_block_top"
        mat_mock.get = lambda k, default=None: "minecraft:block/grass_block_top" if k == "mtk_source_texture_key" else default
        mat_mock.node_tree = None
        slot_mock = MagicMock(material=mat_mock)
        obj.material_slots = [slot_mock]

        update_object_biome(obj, "PLAINS")
        plains_col0 = list(mesh.attributes[ATTR_BIOME_TINT_COLOR].data[0].color)
        plains_col1 = list(mesh.attributes[ATTR_BIOME_TINT_COLOR].data[1].color)
        self.assertEqual(plains_col0, plains_col1)

        update_object_biome(obj, "WORLD")
        world_col0 = list(mesh.attributes[ATTR_BIOME_TINT_COLOR].data[0].color)
        world_col1 = list(mesh.attributes[ATTR_BIOME_TINT_COLOR].data[1].color)
        self.assertNotEqual(world_col0, world_col1)

    def test_mark_world_biome_tags_object_and_caches_storage(self):
        """Voxel meshes must advertise WORLD and expose their storage for later re-tints."""
        self.addCleanup(clear_biome_updater_cache)
        storage = self.lib.VoxelStorage()
        mesh = _MockMesh(1)
        mesh.name = "Yefira_World_Mesh"
        obj = _MockObject(mesh)
        obj.name = "Yefira_World_Mesh"

        mark_world_biome(obj, storage)

        self.assertEqual(obj["mtk:biome_preset"], "WORLD")
        self.assertIs(get_object_storage("Yefira_World_Mesh"), storage)

    def test_ui_infers_world_for_untagged_world_mesh(self):
        """Legacy sync meshes without mtk:biome_preset should display World Biome (3D)."""
        mesh = _MockMesh(1)
        mesh.attributes.new(name=ATTR_BIOME_TINT_DATA, type="FLOAT_COLOR", domain="FACE")
        obj = _MockObject(mesh)
        obj["mtk:geometry_origin"] = "SYNC_WORLD"

        self.assertEqual(_resolve_biome_preset(obj), "WORLD")
        idx = _get_object_biome(obj)
        self.assertEqual(BIOME_ENUM_ITEMS[idx][0], "WORLD")

    def test_ui_keeps_plains_for_external_untinted_mesh(self):
        """External meshes must not inherit the WORLD default from tint attributes."""
        mesh = _MockMesh(1)
        mesh.attributes.new(name=ATTR_BIOME_TINT_DATA, type="FLOAT_COLOR", domain="FACE")
        obj = _MockObject(mesh)
        obj["mtk:geometry_origin"] = "EXTERNAL"

        self.assertEqual(_resolve_biome_preset(obj), "PLAINS")
        idx = _get_object_biome(obj)
        self.assertEqual(BIOME_ENUM_ITEMS[idx][0], "PLAINS")

    def test_world_restores_storage_from_companion_point_cloud(self):
        """Re-selecting WORLD after a uniform preset must rebuild storage from the point cloud."""
        from unittest.mock import patch
        from MoziToolKit.bridge.point_cloud.constants import ATTR_BIOME

        self.addCleanup(clear_biome_updater_cache)

        storage = self.lib.VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        storage.set_block(0, 0, 0, "minecraft:grass_block", "minecraft:jungle")

        mesh = _MockMesh(1)
        mesh.name = "Yefira_World_Mesh"
        mesh.attributes.new(name=ATTR_BIOME_TINT_DATA, type="FLOAT_COLOR", domain="FACE")
        mesh.attributes.new(name=ATTR_BIOME_TINT_COLOR, type="FLOAT_COLOR", domain="FACE")
        for name in ("mtk_block_x", "mtk_block_y", "mtk_block_z"):
            attr = mesh.attributes.new(name=name, type="INT", domain="FACE")
            attr.data[0].value = 0
        idx_attr = mesh.attributes.new(name=ATTR_SOURCE_TEXTURE_IDX, type="INT", domain="FACE")
        idx_attr.data[0].value = 0

        mesh["mtk_source_textures"] = ["minecraft:block/grass_block_top"]
        obj = _MockObject(mesh)
        obj.name = "Yefira_World_Mesh"
        obj["mtk:biome_preset"] = "PLAINS"

        cloud = MagicMock()
        cloud.name = "Yefira_World_VoxelCloud"
        cloud.data = MagicMock()
        cloud.data.attributes = {ATTR_BIOME: MagicMock()}
        cloud_data = MagicMock()
        cloud_data.to_storage.return_value = storage

        with patch("MoziToolKit.utils.point_cloud.get_associated_voxel_cloud", return_value=cloud), \
             patch("MoziToolKit.bridge.point_cloud.extract_voxel_point_cloud", return_value=cloud_data):
            self.assertTrue(update_object_biome(obj, "WORLD"))

        self.assertEqual(obj["mtk:biome_preset"], "WORLD")
        self.assertIs(get_object_storage("Yefira_World_Mesh"), storage)

    def test_world_without_storage_does_not_repaint_plains(self):
        """Refuse WORLD when a uniform preset overwrote the tint and no storage exists."""
        self.addCleanup(clear_biome_updater_cache)
        mesh = _MockMesh(1)
        mesh.name = "Detached_World_Mesh"
        mesh.attributes.new(name=ATTR_BIOME_TINT_DATA, type="FLOAT_COLOR", domain="FACE")
        col_attr = mesh.attributes.new(name=ATTR_BIOME_TINT_COLOR, type="FLOAT_COLOR", domain="FACE")
        col_attr.data[0].color = [0.27, 0.50, 0.09, 1.0]
        obj = _MockObject(mesh)
        obj.name = "Detached_World_Mesh"
        obj["mtk:biome_preset"] = "PLAINS"

        self.assertFalse(update_object_biome(obj, "WORLD"))
        self.assertEqual(obj["mtk:biome_preset"], "PLAINS")
        self.assertEqual(list(col_attr.data[0].color), [0.27, 0.50, 0.09, 1.0])

    def test_world_switch_without_source_keys_does_not_zero_tint(self):
        """Legacy sync meshes without provenance must not get all tint types zeroed."""
        self.addCleanup(clear_biome_updater_cache)

        storage = self.lib.VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        storage.set_block(0, 0, 0, "minecraft:grass_block", "minecraft:jungle")

        mesh = _MockMesh(1)
        mesh.name = "Legacy_World_Mesh"
        tint_attr = mesh.attributes.new(name=ATTR_BIOME_TINT_DATA, type="FLOAT_COLOR", domain="FACE")
        # [base_weight, overlay_weight, tint_weight, tint_type] -> grass tinted.
        tint_attr.data[0].color = [1.0, 0.0, 1.0, 1.0]
        mesh.attributes.new(name=ATTR_BIOME_TINT_COLOR, type="FLOAT_COLOR", domain="FACE")
        mesh.attributes.new(name=ATTR_COLORMAP_UV, type="VECTOR", domain="FACE")
        for name in ("mtk_block_x", "mtk_block_y", "mtk_block_z"):
            attr = mesh.attributes.new(name=name, type="INT", domain="FACE")
            attr.data[0].value = 0

        obj = _MockObject(mesh)
        obj.name = "Legacy_World_Mesh"
        obj["mtk:biome_preset"] = "WORLD"
        register_object_storage(obj.name, storage)

        # Atlas chunk material: no per-material source key, only a chunk name.
        mat = MagicMock()
        mat.name = "MTK:Atlas:blocks:0"
        mat.get = lambda key, default=None: default
        mat.node_tree = None
        obj.material_slots = [MagicMock(material=mat)]

        self.assertTrue(update_object_biome(obj, "CUSTOM"))
        self.assertAlmostEqual(mesh.attributes[ATTR_BIOME_TINT_DATA].data[0].color[3], 1.0)

        # WORLD re-selection cannot resolve provenance; it must refuse instead of
        # overwriting the still-valid tint categories with "none" (0.0).
        self.assertFalse(update_object_biome(obj, "WORLD"))
        self.assertAlmostEqual(mesh.attributes[ATTR_BIOME_TINT_DATA].data[0].color[3], 1.0)
        self.assertEqual(obj["mtk:biome_preset"], "CUSTOM")

    def test_real_save_3d_biome_loading(self):
        """Verify 3D section biome ingestion from a real Minecraft Anvil save when MTK_TEST_SAVE is available."""
        from _assets import save_world
        from MoziToolKit.bridge.save import load_and_mesh_minecraft_save

        world_path = save_world()
        if world_path is None:
            self.skipTest("Sample Minecraft save not found (set MTK_TEST_SAVE)")

        mesh_data, meta, storage, _ = load_and_mesh_minecraft_save(
            world_dir=world_path,
            dimension="overworld",
            min_block=(-32, -64, -32),
            max_block=(31, 128, 31),
        )
        self.assertGreater(mesh_data.vertex_count, 0)
        self.assertIsNotNone(storage)
        # Ensure 3D biome queries return valid canonical biome identifiers
        b_surf = storage.get_biome(0, 64, 0)
        b_deep = storage.get_biome(0, -32, 0)
        self.assertTrue(bool(b_surf))
        self.assertTrue(bool(b_deep))


if __name__ == "__main__":
    unittest.main()

