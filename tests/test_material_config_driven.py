import json
import pytest

from bridge.material import (
    HAS_LIBMTK,
    get_block_emission_strength,
    get_block_sticker_threshold,
    get_block_transmission_weight,
    get_material_props,
    is_thin_wall_block,
    is_transmissive_block,
    load_material_properties_config,
    reset_material_properties_config,
    get_default_material_properties_path,
)


@pytest.mark.skipif(not HAS_LIBMTK, reason="libmtk_py is not available")
def test_default_config_path_exists_and_loads():
    cfg_path = get_default_material_properties_path()
    assert cfg_path.is_file(), f"Expected config file at {cfg_path}"

    with open(cfg_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "emission" in data
    assert "thin_wall" in data
    assert "transmissive" in data

    # Test loading default config
    success = load_material_properties_config()
    assert success is True

    # Vanilla defaults verified
    assert get_block_emission_strength("torch") == 14.0
    assert get_block_emission_strength("beacon") == 15.0
    assert is_thin_wall_block("oak_leaves") is True
    assert is_transmissive_block("glass") is True


@pytest.mark.skipif(not HAS_LIBMTK, reason="libmtk_py is not available")
def test_dynamic_dict_override_without_recompilation():
    reset_material_properties_config()

    # Pre-check non-existent mod block
    assert get_block_emission_strength("my_mod:arcane_lantern") == 0.0
    assert is_thin_wall_block("my_mod:ancient_folium") is False
    assert is_transmissive_block("my_mod:plasma_fluid") is False

    # Send dynamic override via Python dict
    override_dict = {
        "emission": {
            "static_blocks": {
                "torch": 3.0,
                "my_mod:arcane_lantern": 15.0,
            }
        },
        "thin_wall": {
            "exact_blocks": ["my_mod:ancient_folium"]
        },
        "transmissive": {
            "exact_blocks": ["my_mod:plasma_fluid"],
            "sticker_thresholds": {
                "my_mod:plasma_fluid": 0.88,
            }
        }
    }

    success = load_material_properties_config(override_dict)
    assert success is True

    # Verify overrides take effect immediately
    assert get_block_emission_strength("torch") == 3.0
    assert get_block_emission_strength("my_mod:arcane_lantern") == 15.0
    assert is_thin_wall_block("my_mod:ancient_folium") is True
    assert is_transmissive_block("my_mod:plasma_fluid") is True
    assert get_block_sticker_threshold("my_mod:plasma_fluid") == pytest.approx(0.88)

    props = get_material_props("my_mod:plasma_fluid")
    assert props[0] == pytest.approx(0.0)
    assert props[1] == pytest.approx(0.0)
    assert props[2] == pytest.approx(1.0)
    assert props[3] == pytest.approx(0.88)

    # Reset
    reset_material_properties_config()
    assert get_block_emission_strength("torch") == 14.0
    assert get_block_emission_strength("my_mod:arcane_lantern") == 0.0
