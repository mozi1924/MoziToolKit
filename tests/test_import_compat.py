"""Tests for the Python-owned import compatibility profile."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from MoziToolKit.bridge.assets.compat import (
    compat_profile_hash,
    compat_stamp_matches,
    import_compat_path,
    load_import_compat_json,
    write_compat_stamp,
)


def test_default_profile_is_valid_json():
    text = load_import_compat_json()
    assert text is not None
    data = json.loads(text)
    assert data["version"] == 1
    assert "_forest" in data["strip_biome_suffixes"]
    assert any(rule["keyword"] == "leaves" for rule in data["material_fallbacks"])
    assert isinstance(data["tint_categories"], dict)
    assert isinstance(data["hardcoded_colors"], dict)


def test_profile_biome_suffixes_match_the_native_core():
    """The editable profile must never drift from `mtk-material`'s built-in list.

    `strip_biome_suffixes` in the JSON *overrides* the Rust default, so a missing
    entry here silently disables that suffix for every host. Keeping the two in
    lockstep is what prevents a repeat of the historical `_y` divergence.
    """
    from MoziToolKit.bridge import builtin_biome_suffixes

    native = list(builtin_biome_suffixes())
    assert native, "Rust core must expose a non-empty biome suffix list"
    assert len(set(native)) == len(native), "Rust core suffix list must not contain duplicates"
    data = json.loads(load_import_compat_json() or "{}")
    profile = data["strip_biome_suffixes"]
    # Ordering is irrelevant: Rust and every consumer prefer the longest match.
    assert set(profile) == set(native)
    assert len(profile) == len(native), "profile has duplicate suffix entries"


def test_jmc2obj_uses_the_native_suffix_list():
    """The jmc2obj candidate generator must not carry its own suffix table."""
    from MoziToolKit.bridge import builtin_biome_suffixes
    from MoziToolKit.utils.materials.matching.presets import jmc2obj

    native = tuple(builtin_biome_suffixes())
    assert jmc2obj.biome_suffixes() == native
    assert not hasattr(jmc2obj, "JMC2OBJ_BIOME_SUFFIXES"), "local biome suffix table leaked back"
    # Every native suffix must actually be stripped from a jmc2obj material name.
    for suffix in native:
        assert jmc2obj.clean_jmc2obj_identifier(f"stone{suffix}") == "stone", suffix


def test_env_override(tmp_path, monkeypatch):
    profile = tmp_path / "compat.json"
    profile.write_text(
        json.dumps(
            {
                "version": 1,
                "strip_biome_suffixes": ["_custom"],
                "material_fallbacks": [],
                "tint_categories": {"mod:block/grass": "grass"},
                "hardcoded_colors": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MTK_IMPORT_COMPAT", str(profile))
    assert import_compat_path() == profile
    data = json.loads(load_import_compat_json() or "{}")
    assert data["strip_biome_suffixes"] == ["_custom"]


def test_invalid_profile_returns_none(tmp_path, monkeypatch):
    profile = tmp_path / "broken.json"
    profile.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("MTK_IMPORT_COMPAT", str(profile))
    assert load_import_compat_json() is None


def test_compat_stamp_tracks_profile(tmp_path, monkeypatch):
    profile = tmp_path / "compat.json"
    profile.write_text('{"strip_biome_suffixes": ["_x"]}', encoding="utf-8")
    monkeypatch.setenv("MTK_IMPORT_COMPAT", str(profile))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    assert not compat_stamp_matches(cache_dir)
    write_compat_stamp(cache_dir)
    assert compat_stamp_matches(cache_dir)

    profile.write_text('{"strip_biome_suffixes": ["_y"]}', encoding="utf-8")
    assert not compat_stamp_matches(cache_dir)
    assert compat_profile_hash() != ""


def test_precompile_forwards_profile_and_writes_stamp(tmp_path, monkeypatch):
    from MoziToolKit.bridge.assets.precompile import precompile_stack

    profile = tmp_path / "compat.json"
    profile.write_text('{"strip_biome_suffixes": ["_x"]}', encoding="utf-8")
    monkeypatch.setenv("MTK_IMPORT_COMPAT", str(profile))

    stack = MagicMock()
    stack.get_pack_count.return_value = 1
    result = MagicMock()
    result.success = True
    result.pack_count = 1
    result.atlas_chunks = 1
    result.baked_models = 1
    result.package_path = str(tmp_path / "cache.mtkcache")
    result.profile = None

    with patch("MoziToolKit.bridge.assets.precompile.get_libmtk") as get_mtk, patch(
        "MoziToolKit.bridge.assets.precompile.invalidate_asset_cache_memory"
    ):
        mtk = MagicMock()
        mtk.precompile_all_assets.return_value = result
        get_mtk.return_value = mtk
        precompile_stack(stack=stack, cache_dir=str(tmp_path))

    kwargs = mtk.precompile_all_assets.call_args.kwargs
    assert kwargs["resolver_overrides_json"] == profile.read_text(encoding="utf-8")
    assert (tmp_path / "import_compat.sha256").is_file()
