"""
Integration and regression test suite for Biome Tinting fixes:
- Dead bush (dead_bush) must NOT be tinted (tint_type=0, tint_weight=0.0).
- Leaf litter (leaf_litter) must be tinted with dry_foliage (tint_type=5, tint_weight=1.0).
- Short grass (short_grass) and Bush (bush) must be tinted with grass (tint_type=1, tint_weight=1.0).
- Oak leaves (oak_leaves) must be tinted with foliage (tint_type=2, tint_weight=1.0).
- Fallback when biome_resolver is None must use classify_tint_category rather than hardcoding grass.
- MC_Biome_Colormap_Decoder socket default value for Tint Type must be 0.0 (None / Fallback white).
"""

import unittest
import struct

from unittest.mock import MagicMock

try:
    import bpy
    HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "meshes") and not isinstance(bpy.data, MagicMock)
except ImportError:
    bpy = None
    HAS_BPY = False

from bridge.assets import load_biome_resolver_from_cache

if HAS_BPY:
    from utils.node_groups.biome import ensure_colormap_decoder, COLORMAP_DECODER_VERSION
else:
    ensure_colormap_decoder = None
    COLORMAP_DECODER_VERSION = None

try:
    import libmtk_py
    HAS_LIBMTK = True
except ImportError:
    HAS_LIBMTK = False


class TestBiomeTintingFix(unittest.TestCase):

    def setUp(self):
        if not HAS_BPY or not HAS_LIBMTK:
            self.skipTest("Requires bpy and native libmtk_py")

    def test_colormap_decoder_default_tint_type(self):
        """Verifies that MC_Biome_Colormap_Decoder default Tint Type is 0.0 (white fallback)."""
        tree = ensure_colormap_decoder()
        assert tree is not None
        assert tree.get("mozi_template_version") == COLORMAP_DECODER_VERSION

        # Check Tint Type socket default
        tint_type_sock = None
        for item in tree.interface.items_tree:
            if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.name == "Tint Type":
                tint_type_sock = item
                break

        assert tint_type_sock is not None, "Tint Type socket not found in decoder interface"
        assert tint_type_sock.default_value == 0.0, f"Expected default Tint Type 0.0, got {tint_type_sock.default_value}"

    def test_biome_resolver_categories(self):
        """Verifies that BiomeResolver categorizes dead_bush, leaf_litter, bush, and foliage correctly."""
        resolver = libmtk_py.BiomeResolver()

        # Dead bush
        db_info = resolver.get_tint_info("dead_bush", "dead_bush", 0)
        assert db_info["tint_type"] == 0
        assert db_info["tint_category"] == "none"
        assert db_info["tint_weight"] == 0.0

        # Leaf litter
        ll_info = resolver.get_tint_info("leaf_litter", "leaf_litter", 0)
        assert ll_info["tint_type"] == 5
        assert ll_info["tint_category"] == "dry_foliage"
        assert ll_info["tint_weight"] == 1.0

        # Bush (Vanilla 1.21.4 uses grass colormap)
        b_info = resolver.get_tint_info("bush", "bush", 0)
        assert b_info["tint_type"] == 1
        assert b_info["tint_category"] == "grass"
        assert b_info["tint_weight"] == 1.0

        # Short grass
        sg_info = resolver.get_tint_info("short_grass", "short_grass", 0)
        assert sg_info["tint_type"] == 1
        assert sg_info["tint_category"] == "grass"

        # Oak leaves
        oak_info = resolver.get_tint_info("oak_leaves", "oak_leaves", 0)
        assert oak_info["tint_type"] == 2
        assert oak_info["tint_category"] == "foliage"

        # Hardcoded leaves
        spruce_info = resolver.get_tint_info("spruce_leaves", "spruce_leaves", 0)
        assert spruce_info["tint_type"] == 4
        assert spruce_info["is_hardcoded"] is True

    def test_load_biome_resolver_fallback(self):
        """Verifies that load_biome_resolver_from_cache falls back to default BiomeResolver."""
        resolver = load_biome_resolver_from_cache(None)
        assert resolver is not None
        db_info = resolver.get_tint_info("dead_bush", "dead_bush", 0)
        assert db_info["tint_type"] == 0
        assert db_info["tint_weight"] == 0.0

    def test_voxel_mesher_tint_attributes_end_to_end(self):
        """Verifies that voxel mesher produces correct tint attributes with and without resolver."""
        import struct

        storage = libmtk_py.VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        storage.set_block(0, 0, 0, "minecraft:dead_bush")
        storage.set_block(0, 1, 0, "minecraft:leaf_litter")
        storage.set_block(0, 2, 0, "minecraft:short_grass")

        resolver = libmtk_py.BiomeResolver()
        cfg_res = libmtk_py.MesherConfig(biome_resolver=resolver)
        cfg_no_res = libmtk_py.MesherConfig(biome_resolver=None)

        assert cfg_res.has_biome_resolver() is True
        assert cfg_no_res.has_biome_resolver() is False

        # 1. With BiomeResolver
        mesh_res = libmtk_py.SectionMesher.mesh_world(storage, cfg_res, None)
        assert mesh_res is not None
        assert mesh_res.face_count > 0
        assert mesh_res.has_attribute("mtk_biome_tint_data")

        mv = mesh_res.attribute_memoryview("mtk_biome_tint_data")
        floats = struct.unpack(f"{len(mv)//4}f", bytes(mv))
        rows = [floats[i*4:(i+1)*4] for i in range(len(floats)//4)]
        tint_types = {r[3] for r in rows}

        # Must contain 0.0 (dead_bush), 5.0 (leaf_litter), 1.0 (short_grass)
        assert 0.0 in tint_types, "dead_bush tint_type 0.0 must be present"
        assert 5.0 in tint_types, "leaf_litter dry_foliage tint_type 5.0 must be present"
        assert 1.0 in tint_types, "short_grass grass tint_type 1.0 must be present"

        # 2. Fallback without resolver: dead_bush and leaf_litter must still be classified properly
        mesh_no_res = libmtk_py.SectionMesher.mesh_world(storage, cfg_no_res, None)
        assert mesh_no_res is not None
        mv_no_res = mesh_no_res.attribute_memoryview("mtk_biome_tint_data")
        floats_no_res = struct.unpack(f"{len(mv_no_res)//4}f", bytes(mv_no_res))
        rows_no_res = [floats_no_res[i*4:(i+1)*4] for i in range(len(floats_no_res)//4)]
        tint_types_no_res = {r[3] for r in rows_no_res}

        assert 0.0 in tint_types_no_res, "Fallback dead_bush tint_type 0.0 must be present"
        assert 5.0 in tint_types_no_res, "Fallback leaf_litter dry_foliage tint_type 5.0 must be present"
        assert 1.0 in tint_types_no_res, "Fallback short_grass grass tint_type 1.0 must be present"

    def test_grass_block_side_overlay_tinting(self):
        """Verifies grass_block_side has overlay tinted while dirt base and bottom dirt are untinted."""
        resolver = libmtk_py.BiomeResolver()

        # 1. grass_block_side (overlay companion)
        side_info = resolver.get_tint_info("grass_block_side", "grass_block", -1)
        self.assertEqual(side_info["tint_type"], 1, "grass_block_side tint_type must be 1 (GRASS)")
        self.assertEqual(side_info["tint_weight"], 1.0, "grass_block_side tint_weight must be 1.0")
        self.assertEqual(side_info["base_tint_weight"], 0.0, "dirt base on side face must be 0.0 (untinted)")
        self.assertEqual(side_info["overlay_tint_weight"], 1.0, "overlay on side face must be 1.0 (tinted)")
        self.assertTrue(side_info["has_overlay"], "grass_block_side must have overlay companion")

        # 2. dirt (bottom face of grass block)
        dirt_info = resolver.get_tint_info("dirt", "grass_block", -1)
        self.assertEqual(dirt_info["tint_weight"], 0.0, "dirt face must have tint_weight 0.0 (untinted dirt)")
        self.assertFalse(dirt_info["has_overlay"], "dirt must not have overlay companion")

        # 3. grass_block_top
        top_info = resolver.get_tint_info("grass_block_top", "grass_block", 0)
        self.assertEqual(top_info["tint_type"], 1, "top face must be grass")
        self.assertEqual(top_info["tint_weight"], 1.0, "top face must be tinted")

    def test_live_sync_biome_transition_smoothing(self):
        """Verifies voxel mesher across a biome boundary outputs smoothly blended colormap UV and tint color."""
        storage = libmtk_py.VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        for x in range(16):
            for z in range(16):
                biome = "minecraft:plains" if x < 8 else "minecraft:desert"
                storage.set_block(x, 0, z, "minecraft:grass_block", biome)

        config = libmtk_py.MesherConfig()
        mesh = libmtk_py.SectionMesher.mesh_world(storage, config, None)
        self.assertIsNotNone(mesh)
        self.assertTrue(mesh.has_attribute("mtk_colormap_uv"))
        self.assertTrue(mesh.has_attribute("mtk_biome_tint_color"))

        # Unpack mtk_colormap_uv
        mv_uv = mesh.attribute_memoryview("mtk_colormap_uv")
        raw_uv = struct.unpack(f"{len(mv_uv)//4}f", bytes(mv_uv))
        uvs = [raw_uv[i*3:(i+1)*3] for i in range(len(raw_uv)//3)]

        # Verify continuous intermediate gradient values exist across the 5x5 kernel transition
        distinct_u = set()
        for u, v, _ in uvs:
            distinct_u.add(round(u * 100))

        self.assertGreater(len(distinct_u), 2, "Transition zone must produce continuous blended gradient values!")

    def test_update_object_biome_live_sync_mesh_without_source_keys(self):
        """Verifies update_object_biome successfully updates colors and colormap UVs on meshes lacking string attributes."""
        import array
        from utils.materials.biome.updater import update_object_biome

        b_mesh = bpy.data.meshes.new("TestLiveSyncMesh")
        b_mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
        obj = bpy.data.objects.new("Yefira_World_Test", b_mesh)
        obj["mtk:is_yefira_world"] = True
        bpy.context.collection.objects.link(obj)

        try:
            # Create mtk_biome_tint_data (Grass face: tint_type=1)
            attr_data = b_mesh.attributes.new(name="mtk_biome_tint_data", type="FLOAT_COLOR", domain="FACE")
            attr_data.data.foreach_set("color", array.array("f", [1.0, 1.0, 1.0, 1.0]))

            # Initial Plains values
            attr_col = b_mesh.attributes.new(name="mtk_biome_tint_color", type="FLOAT_COLOR", domain="FACE")
            attr_col.data.foreach_set("color", array.array("f", [0.28, 0.51, 0.10, 1.0]))

            attr_uv = b_mesh.attributes.new(name="mtk_colormap_uv", type="FLOAT_VECTOR", domain="FACE")
            attr_uv.data.foreach_set("vector", array.array("f", [0.2, 0.32, 0.0]))

            # Update to DESERT
            res = update_object_biome(obj, "DESERT")
            self.assertTrue(res)

            # Check new tint color (Desert yellow-green ~ 0.52, 0.47, 0.09)
            new_col = list(b_mesh.attributes["mtk_biome_tint_color"].data[0].color)
            self.assertAlmostEqual(new_col[0], 0.5209956, places=2)
            self.assertAlmostEqual(new_col[1], 0.4735315, places=2)

            # Check new colormap UV (Desert: [0.0, 0.0, 0.0])
            new_uv = list(b_mesh.attributes["mtk_colormap_uv"].data[0].vector)
            self.assertAlmostEqual(new_uv[0], 0.0, places=3)
            self.assertAlmostEqual(new_uv[1], 0.0, places=3)
        finally:
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(b_mesh)


if __name__ == "__main__":
    unittest.main()


