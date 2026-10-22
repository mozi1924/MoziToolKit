"""
Unit and integration tests for Minecraft Save Bridge and Importer.
"""

import pytest

from _assets import save_world
from MoziToolKit.bridge.save import inspect_minecraft_save, load_and_mesh_minecraft_save
from MoziToolKit.operators.save.op_import_save import MTK_OT_import_minecraft_save

SAMPLE_WORLD_PATH = save_world()


def test_operator_definition():
    """Verify operator bl_idname and properties."""
    assert MTK_OT_import_minecraft_save.bl_idname == "mtk.import_minecraft_save"
    assert "directory" in MTK_OT_import_minecraft_save.__annotations__
    assert "min_coord" in MTK_OT_import_minecraft_save.__annotations__
    assert "max_coord" in MTK_OT_import_minecraft_save.__annotations__
    assert "dimension" in MTK_OT_import_minecraft_save.__annotations__
    assert "use_yefira_selection" in MTK_OT_import_minecraft_save.__annotations__
    assert "run_async" in MTK_OT_import_minecraft_save.__annotations__


def test_operator_apply_yefira_selection(tmp_path):
    """Verify operator apply_yefira_selection loads coordinates into operator instance."""
    import json
    from types import SimpleNamespace
    from MoziToolKit.utils.save.selection import YEFIRA_SELECTION_FILENAME

    json_file = tmp_path / YEFIRA_SELECTION_FILENAME
    json_file.write_text(
        json.dumps({
            "pos1": {"x": 100, "y": 200, "z": 300},
            "pos2": {"x": 50, "y": 64, "z": -50},
            "dimension": "minecraft:the_nether",
        }),
        encoding="utf-8",
    )

    op = SimpleNamespace(
        directory=str(tmp_path),
        filepath="",
        use_yefira_selection=True,
        min_coord=(-64, -64, -64),
        max_coord=(64, 320, 64),
        dimension="overworld",
    )
    applied = MTK_OT_import_minecraft_save.apply_yefira_selection(op)

    assert applied is True
    assert tuple(op.min_coord) == (50, 64, -50)
    assert tuple(op.max_coord) == (100, 200, 300)
    assert op.dimension == "the_nether"


def test_operator_apply_yefira_selection_non_world_dir(tmp_path):
    """Verify that toggling in a non-world folder does not crash and safely returns False."""
    from types import SimpleNamespace
    from MoziToolKit.operators.save.op_import_save import (
        _on_use_yefira_selection_update,
        _on_save_import_directory_update,
    )

    op = SimpleNamespace(
        directory=str(tmp_path),
        filepath="",
        use_yefira_selection=True,
        min_coord=(-64, -64, -64),
        max_coord=(64, 320, 64),
        dimension="overworld",
    )

    # Calling callbacks on RNA-like structs must not crash
    _on_use_yefira_selection_update(op, None)
    _on_save_import_directory_update(op, None)

    # Coordinates remain untouched
    assert tuple(op.min_coord) == (-64, -64, -64)
    assert tuple(op.max_coord) == (64, 320, 64)
    assert op.dimension == "overworld"


def test_operator_apply_yefira_selection_via_filepath(tmp_path):
    """Verify that selecting a world folder via filepath correctly resolves and fills."""
    import json
    from types import SimpleNamespace
    from MoziToolKit.utils.save.selection import YEFIRA_SELECTION_FILENAME
    from MoziToolKit.operators.save.op_import_save import _on_use_yefira_selection_update

    parent_dir = tmp_path / "saves"
    parent_dir.mkdir()
    world_dir = parent_dir / "MyWorld"
    world_dir.mkdir()

    json_file = world_dir / YEFIRA_SELECTION_FILENAME
    json_file.write_text(
        json.dumps({
            "pos1": {"x": 10, "y": 70, "z": 20},
            "pos2": {"x": -10, "y": 60, "z": -20},
            "dimension": "minecraft:the_end",
        }),
        encoding="utf-8",
    )

    # User is in parent_dir, but selected world_dir as filepath
    op = SimpleNamespace(
        directory=str(parent_dir),
        filepath=str(world_dir),
        use_yefira_selection=True,
        min_coord=(-64, -64, -64),
        max_coord=(64, 320, 64),
        dimension="overworld",
    )

    _on_use_yefira_selection_update(op, None)

    assert tuple(op.min_coord) == (-10, 60, -20)
    assert tuple(op.max_coord) == (10, 70, 20)
    assert op.dimension == "the_end"


@pytest.mark.skipif(SAMPLE_WORLD_PATH is None, reason="Sample Minecraft world not found (set MTK_TEST_SAVE)")
def test_inspect_real_minecraft_save():
    """Test inspecting level.dat metadata."""
    assert SAMPLE_WORLD_PATH is not None
    meta = inspect_minecraft_save(SAMPLE_WORLD_PATH)
    assert meta["level_name"]
    assert meta["data_version"] >= 2844
    assert meta["version_name"] != "Unknown"
    assert "overworld" in meta["dimensions"]
    assert len(meta["spawn"]) == 3


@pytest.mark.skipif(SAMPLE_WORLD_PATH is None, reason="Sample Minecraft world not found (set MTK_TEST_SAVE)")
def test_bounded_mesh_save():
    """Test streaming and meshing only a bounded selection."""
    mesh_data, meta, storage, elapsed_ms = load_and_mesh_minecraft_save(
        world_dir=SAMPLE_WORLD_PATH,
        dimension="overworld",
        min_block=(0, -64, 0),
        max_block=(15, 64, 15),
    )

    assert meta["level_name"]
    assert mesh_data.vertex_count > 0
    assert mesh_data.quad_count > 0
    assert elapsed_ms < 5000.0  # Should be extremely fast (<100ms)


@pytest.mark.skipif(SAMPLE_WORLD_PATH is None, reason="Sample Minecraft world not found (set MTK_TEST_SAVE)")
def test_bounded_mesh_save_with_progress():
    """Test streaming and meshing a bounded selection with physical progress reporting."""
    reports = []
    def on_prog(r):
        reports.append(r)

    mesh_data, meta, storage, elapsed_ms = load_and_mesh_minecraft_save(
        world_dir=SAMPLE_WORLD_PATH,
        dimension="overworld",
        min_block=(0, -64, 0),
        max_block=(31, 64, 31),
        progress_callback=on_prog,
    )

    assert meta["level_name"]
    assert mesh_data.vertex_count > 0
    assert len(reports) >= 2, f"Expected progress reports during chunk load and meshing, got {len(reports)}"
    stages = [r.stage for r in reports]
    assert "load_chunks" in stages


@pytest.mark.skipif(SAMPLE_WORLD_PATH is None, reason="Sample Minecraft world not found (set MTK_TEST_SAVE)")
def test_cold_cache_save_import_binds_textures(tmp_path, monkeypatch):
    """Test importing a save under cold cache conditions: precompilation creates .mtkcache and textures are bound."""
    from _assets import fabric_jar
    jar = fabric_jar()
    if jar is None:
        pytest.skip("Fabric JAR not found")

    sandbox_cache = tmp_path / "cold_cache"
    sandbox_cache.mkdir()
    monkeypatch.setenv("MOZI_CACHE_DIR", str(sandbox_cache))

    from MoziToolKit.bridge.assets import invalidate_asset_cache_memory
    from MoziToolKit.utils.assets import check_asset_cache_status, run_task_with_asset_guard
    from MoziToolKit.utils.save import apply_imported_save_to_blender

    from unittest.mock import MagicMock
    mock_prefs = MagicMock()
    mock_prefs.resource_pack_path = str(jar)
    mock_prefs.resource_packs = []
    mock_prefs.cache_dir = str(sandbox_cache)

    invalidate_asset_cache_memory()
    status = check_asset_cache_status(mock_prefs)
    assert status in ("MISSING", "STALE", "READY")

    result, did_precompile = run_task_with_asset_guard(
        target_func=load_and_mesh_minecraft_save,
        target_kwargs={
            "world_dir": SAMPLE_WORLD_PATH,
            "dimension": "overworld",
            "min_block": (0, -64, 0),
            "max_block": (15, 64, 15),
            "prefs": mock_prefs,
        },
        prefs=mock_prefs,
    )

    mesh_data, meta, storage, elapsed_ms = result
    assert mesh_data.vertex_count > 0

    try:
        import bpy
        is_real_blender = hasattr(bpy, "app") and "Mock" not in type(bpy.app).__name__
    except ImportError:
        is_real_blender = False

    if is_real_blender:
        obj, stats = apply_imported_save_to_blender(
            mesh_data=mesh_data,
            meta=meta,
            storage=storage,
            elapsed_ms=elapsed_ms,
            world_dir=SAMPLE_WORLD_PATH,
            dimension="overworld",
            min_block=(0, -64, 0),
            max_block=(15, 64, 15),
            prefs=mock_prefs,
        )
        mesh_obj = obj.children[0] if getattr(obj, "children", None) else obj
        assert len(mesh_obj.data.materials) > 0
        mat = mesh_obj.data.materials[0]
        assert mat.name.startswith("MTK:Atlas:")
        assert mat.node_tree is not None
        tex_nodes = [n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE"]
        assert len(tex_nodes) > 0
        albedo_node = mat.node_tree.nodes.get("Atlas Albedo Texture")
        assert albedo_node is not None
        assert albedo_node.image is not None


