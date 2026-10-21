import array

import pytest

from MoziToolKit.utils.config.models import MaterialSettings
from MoziToolKit.utils.materials.builder.shading_config import resolve_material_shading_config

from unittest.mock import MagicMock

try:
    import bpy
    HAS_BPY = (
        not isinstance(bpy, MagicMock)
        and hasattr(bpy, "data")
        and hasattr(bpy.data, "meshes")
        and not isinstance(bpy.data, MagicMock)
    )
except ImportError:
    bpy = None
    HAS_BPY = False

if HAS_BPY:
    from MoziToolKit.utils.materials.builder.atlas_builder import build_atlas_chunk_material


def test_material_settings_model_serialization():
    # Default model
    s = MaterialSettings()
    assert s.render_engine == "AUTO"
    assert s.disable_subsurface is False
    assert s.subsurface_method == "BURLEY"

    d = s.to_dict()
    assert d["render_engine"] == "AUTO"
    assert d["subsurface_method"] == "BURLEY"

    # From custom dict
    custom = MaterialSettings.from_dict({
        "render_engine": "EEVEE",
        "disable_subsurface": True,
        "subsurface_method": "RANDOM_WALK",
    })
    assert custom.render_engine == "EEVEE"
    assert custom.disable_subsurface is True
    assert custom.subsurface_method == "RANDOM_WALK"


def test_resolve_shading_config_is_minimal():
    cfg_cycles = resolve_material_shading_config(render_engine="CYCLES")
    assert cfg_cycles["target_engine"] == "CYCLES"
    assert cfg_cycles["is_eevee"] is False
    assert cfg_cycles["disable_subsurface"] is False
    assert cfg_cycles["emission_strength"] == 5.0
    assert cfg_cycles["subsurface_scale"] == 0.1

    cfg_eevee = resolve_material_shading_config(render_engine="EEVEE")
    assert cfg_eevee["is_eevee"] is True

    cfg_overrides = resolve_material_shading_config(
        render_engine="CYCLES",
        disable_subsurface=True,
        emission_strength=12.0,
    )
    assert cfg_overrides["disable_subsurface"] is True
    assert cfg_overrides["emission_strength"] == 12.0


@pytest.mark.skipif(not HAS_BPY, reason="Blender environment required")
def test_build_atlas_chunk_material_has_no_game_semantic_nodes():
    albedo = (2, 2, array.array("f", [1.0, 1.0, 1.0, 1.0] * 4))
    normal = (2, 2, array.array("f", [0.5, 0.5, 1.0, 1.0] * 4))
    orm = (2, 2, array.array("f", [1.0, 1.0, 0.0, 1.0] * 4))
    aux = (2, 2, array.array("f", [0.0714, 0.0, 0.0, 0.0] * 4))

    mat = build_atlas_chunk_material(
        chunk_id=99,
        albedo_path=albedo,
        normal_path=normal,
        orm_path=orm,
        aux_path=aux,
        render_engine="CYCLES",
        force_rebuild=True,
    )
    assert mat is not None
    assert mat.get("mtk_pbr_layout") == "mtk_packed_v1"

    nodes = mat.node_tree.nodes
    assert nodes.get("Principled BSDF") is not None
    assert nodes.get("Normal Map") is not None
    assert nodes.get("Separate ORM") is not None
    assert nodes.get("Separate Aux") is not None
    assert nodes.get("Albedo × AO") is not None
    assert nodes.get("IOR from Aux") is not None
    assert nodes.get("Emission Strength × Mask") is not None

    # Removed runtime decoder and game-semantic nodes.
    assert nodes.get("LabPBR Decoder") is None
    assert nodes.get("Material Transmission Scale") is None
    assert nodes.get("Attr Material Props") is None
    assert nodes.get("Final Transmission") is None
