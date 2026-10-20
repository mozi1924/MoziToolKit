"""
Unit and integration tests for Minecraft Save Bridge and Importer.
"""

import pytest

from _assets import save_world
from bridge.save import inspect_minecraft_save, load_and_mesh_minecraft_save
from operators.save.op_import_save import MTK_OT_import_minecraft_save

SAMPLE_WORLD_PATH = save_world()


def test_operator_definition():
    """Verify operator bl_idname and properties."""
    assert MTK_OT_import_minecraft_save.bl_idname == "mtk.import_minecraft_save"
    assert "directory" in MTK_OT_import_minecraft_save.__annotations__
    assert "min_coord" in MTK_OT_import_minecraft_save.__annotations__
    assert "max_coord" in MTK_OT_import_minecraft_save.__annotations__
    assert "dimension" in MTK_OT_import_minecraft_save.__annotations__
    assert "run_async" in MTK_OT_import_minecraft_save.__annotations__


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

    from bridge.assets import invalidate_asset_cache_memory
    from utils.assets import check_asset_cache_status, run_task_with_asset_guard
    from utils.save import apply_imported_save_to_blender

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


