import pytest
from pathlib import Path

from utils.config.models import MaterialSettings
from utils.materials.builder.shading_config import resolve_material_shading_config

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
    from utils.node_groups.labpbr import ensure_labpbr_decoder
    from utils.materials.builder.standalone_builder import build_standalone_material
    from utils.materials.builder.atlas_builder import build_atlas_chunk_material


def test_material_settings_model_serialization():
    # Default model
    s = MaterialSettings()
    assert s.render_engine == "AUTO"
    assert s.enable_game_semantics is True
    assert s.transmission_mode == "AUTO"
    assert s.thin_wall_mode == "AUTO"
    assert s.disable_subsurface is False
    assert s.subsurface_method == "BURLEY"

    d = s.to_dict()
    assert d["render_engine"] == "AUTO"
    assert d["subsurface_method"] == "BURLEY"

    # From custom dict
    custom = MaterialSettings.from_dict({
        "render_engine": "EEVEE",
        "enable_game_semantics": False,
        "transmission_mode": "DISABLED",
        "thin_wall_mode": "ENABLED",
        "disable_subsurface": True,
        "subsurface_method": "RANDOM_WALK",
    })
    assert custom.render_engine == "EEVEE"
    assert custom.enable_game_semantics is False
    assert custom.transmission_mode == "DISABLED"
    assert custom.thin_wall_mode == "ENABLED"
    assert custom.disable_subsurface is True
    assert custom.subsurface_method == "RANDOM_WALK"


def test_resolve_shading_config_cycles_vs_eevee():
    # 1. Non-PBR Torch in Cycles: emission enabled
    cfg_cycles = resolve_material_shading_config(
        clean_block="torch",
        raw_props=(14.0, 0.0, 0.0, 0.55),
        has_pbr=False,
        render_engine="CYCLES",
    )
    assert cfg_cycles["target_engine"] == "CYCLES"
    assert cfg_cycles["is_eevee"] is False
    assert cfg_cycles["emission_strength"] == 14.0
    assert cfg_cycles["disable_subsurface"] is False

    # 2. PBR Torch in Cycles: uniform emission BYPASSED (0.0), per-pixel texture takes control
    cfg_pbr = resolve_material_shading_config(
        clean_block="torch",
        raw_props=(14.0, 0.0, 0.0, 0.55),
        has_pbr=True,
        render_engine="CYCLES",
    )
    assert cfg_pbr["emission_strength"] == 0.0  # Let PBR _s control emission

    # 3. Glass in Cycles: physical transmission enabled, refraction raytrace enabled
    cfg_glass_cycles = resolve_material_shading_config(
        clean_block="glass",
        raw_props=(0.0, 0.0, 1.0, 0.55),
        has_pbr=False,
        render_engine="CYCLES",
    )
    assert cfg_glass_cycles["transmission_weight"] == 1.0
    assert cfg_glass_cycles["use_raytrace_refraction"] is True

    # 4. Glass in EEVEE: AUTO mode disables transmission (0.0) to prevent black artifacts
    cfg_glass_eevee = resolve_material_shading_config(
        clean_block="glass",
        raw_props=(0.0, 0.0, 1.0, 0.55),
        has_pbr=False,
        render_engine="EEVEE",
    )
    assert cfg_glass_eevee["is_eevee"] is True
    assert cfg_glass_eevee["transmission_weight"] == 0.0
    assert cfg_glass_eevee["use_raytrace_refraction"] is False
    assert cfg_glass_eevee["disable_subsurface"] is False  # Disable Subsurface defaults to False


@pytest.mark.skipif(not HAS_BPY, reason="Blender environment required")
def test_labpbr_decoder_uses_burley_subsurface():
    group = ensure_labpbr_decoder()
    principled = group.nodes.get("LabPBR Principled BSDF")
    assert principled is not None
    assert principled.subsurface_method == "BURLEY", f"Expected BURLEY, got {principled.subsurface_method}"


@pytest.mark.skipif(not HAS_BPY, reason="Blender environment required")
def test_build_standalone_material_eevee_vs_cycles_adaptation(tmp_path):
    tex_path = tmp_path / "glass.png"
    tex_path.write_bytes(b"dummy")

    # Build for EEVEE: transmission 0, no raytrace refraction
    mat_eevee = build_standalone_material(
        texture_key="glass",
        albedo_path=tex_path,
        block_name="glass",
        material_name="TestMat:EEVEE_Glass",
        render_engine="EEVEE",
    )
    assert mat_eevee is not None
    assert getattr(mat_eevee, "use_raytrace_refraction", False) is False
    assert getattr(mat_eevee, "surface_render_method", "DITHERED") != "BLENDED"

    # Build for CYCLES: transmission enabled
    mat_cycles = build_standalone_material(
        texture_key="glass",
        albedo_path=tex_path,
        block_name="glass",
        material_name="TestMat:CYCLES_Glass",
        render_engine="CYCLES",
    )
    assert mat_cycles is not None
    assert getattr(mat_cycles, "use_raytrace_refraction", False) is True
    assert getattr(mat_cycles, "surface_render_method", "BLENDED") == "BLENDED"


@pytest.mark.skipif(not HAS_BPY, reason="Blender environment required")
def test_build_atlas_chunk_material_eevee_vs_cycles_transmission_scale(tmp_path):
    tex_path = tmp_path / "atlas_chunk_000.png"
    tex_path.write_bytes(b"dummy")

    # Atlas in EEVEE mode: Material Transmission Scale is 0.0 (prevents black rendering artifacts)
    mat_eevee = build_atlas_chunk_material(
        chunk_id=99,
        albedo_path=tex_path,
        render_engine="EEVEE",
    )
    assert mat_eevee is not None
    scale_node_eevee = mat_eevee.node_tree.nodes.get("Material Transmission Scale")
    assert scale_node_eevee is not None
    assert scale_node_eevee.inputs[1].default_value == 0.0

    # Atlas in CYCLES mode: Material Transmission Scale is 1.0 (preserves physical dielectric transmission)
    mat_cycles = build_atlas_chunk_material(
        chunk_id=98,
        albedo_path=tex_path,
        render_engine="CYCLES",
    )
    assert mat_cycles is not None
    scale_node_cycles = mat_cycles.node_tree.nodes.get("Material Transmission Scale")
    assert scale_node_cycles is not None
    assert scale_node_cycles.inputs[1].default_value == 1.0

