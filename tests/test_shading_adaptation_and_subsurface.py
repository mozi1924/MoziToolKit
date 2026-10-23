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
    assert s.enable_vertex_ao is True

    d = s.to_dict()
    assert d["render_engine"] == "AUTO"
    assert d["subsurface_method"] == "BURLEY"
    assert d["enable_vertex_ao"] is True

    # From custom dict
    custom = MaterialSettings.from_dict({
        "render_engine": "EEVEE",
        "disable_subsurface": True,
        "subsurface_method": "RANDOM_WALK",
        "enable_vertex_ao": False,
    })
    assert custom.render_engine == "EEVEE"
    assert custom.disable_subsurface is True
    assert custom.subsurface_method == "RANDOM_WALK"
    assert custom.enable_vertex_ao is False


def test_resolve_shading_config_is_minimal():
    cfg_cycles = resolve_material_shading_config(render_engine="CYCLES")
    assert cfg_cycles["target_engine"] == "CYCLES"
    assert cfg_cycles["is_eevee"] is False
    assert cfg_cycles["disable_subsurface"] is False
    assert cfg_cycles["emission_strength"] == 5.0
    assert cfg_cycles["subsurface_scale"] == 0.1
    assert cfg_cycles["enable_vertex_ao"] is True

    cfg_eevee = resolve_material_shading_config(render_engine="EEVEE")
    assert cfg_eevee["is_eevee"] is True

    cfg_overrides = resolve_material_shading_config(
        render_engine="CYCLES",
        disable_subsurface=True,
        emission_strength=12.0,
        enable_vertex_ao=False,
    )
    assert cfg_overrides["disable_subsurface"] is True
    assert cfg_overrides["emission_strength"] == 12.0
    assert cfg_overrides["enable_vertex_ao"] is False


def test_template_key_vertex_ao():
    from MoziToolKit.utils.materials.builder.template import get_template_key

    key_on = get_template_key(
        category="SOLID",
        is_animated=False,
        use_attribute_node=False,
        has_overlay=False,
        has_normal=False,
        has_orm=False,
        has_aux=False,
        enable_vertex_ao=True,
    )
    key_off = get_template_key(
        category="SOLID",
        is_animated=False,
        use_attribute_node=False,
        has_overlay=False,
        has_normal=False,
        has_orm=False,
        has_aux=False,
        enable_vertex_ao=False,
    )
    assert "vao=1" in key_on
    assert "vao=0" in key_off
    assert key_on != key_off


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
    assert nodes.get("Vertex AO") is not None
    assert nodes.get("AO Presence") is not None
    assert nodes.get("AO Active") is not None
    assert nodes.get("Safe Vertex AO") is not None
    assert nodes.get("Base Color × Vertex AO") is not None

    # Test with enable_vertex_ao = False
    mat_no_vao = build_atlas_chunk_material(
        chunk_id=98,
        material_name="MTK:Test:NoVAO",
        albedo_path=albedo,
        normal_path=normal,
        orm_path=orm,
        aux_path=aux,
        render_engine="CYCLES",
        enable_vertex_ao=False,
        force_rebuild=True,
    )
    assert mat_no_vao is not None
    nodes_no_vao = mat_no_vao.node_tree.nodes
    assert nodes_no_vao.get("Vertex AO") is None
    assert nodes_no_vao.get("AO Presence") is None
    assert nodes_no_vao.get("AO Active") is None
    assert nodes_no_vao.get("Safe Vertex AO") is None
    assert nodes_no_vao.get("Base Color × Vertex AO") is None

    # Removed runtime decoder and game-semantic nodes.
    assert nodes.get("LabPBR Decoder") is None
    assert nodes.get("Material Transmission Scale") is None
    assert nodes.get("Attr Material Props") is None
    assert nodes.get("Final Transmission") is None
