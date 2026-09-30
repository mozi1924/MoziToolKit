"""
Integration and regression test suite for Biome Tinting fixes:
- Dead bush (dead_bush) must NOT be tinted (tint_type=0, tint_weight=0.0).
- Leaf litter (leaf_litter) must be tinted with dry_foliage (tint_type=5, tint_weight=1.0).
- Short grass (short_grass) and Bush (bush) must be tinted with grass (tint_type=1, tint_weight=1.0).
- Oak leaves (oak_leaves) must be tinted with foliage (tint_type=2, tint_weight=1.0).
- Fallback when biome_resolver is None must use classify_tint_category rather than hardcoding grass.
- MC_Biome_Colormap_Decoder socket default value for Tint Type must be 0.0 (None / Fallback white).
"""

import pytest

try:
    import bpy
    HAS_BPY = True
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


@pytest.mark.skipif(not HAS_BPY or not HAS_LIBMTK, reason="Requires bpy and native libmtk_py")
class TestBiomeTintingFix:

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


