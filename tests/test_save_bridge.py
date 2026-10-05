"""
Unit and integration tests for Minecraft Save Bridge and Importer.
"""

from pathlib import Path
import pytest

from bridge.save import inspect_minecraft_save, load_and_mesh_minecraft_save
from operators.save.op_import_save import MTK_OT_import_minecraft_save

SAMPLE_WORLD_PATH = Path("/home/mozi/.minecraft/versions/26.2-Fabric/saves/New World")


def test_operator_definition():
    """Verify operator bl_idname and properties."""
    assert MTK_OT_import_minecraft_save.bl_idname == "mtk.import_minecraft_save"
    assert "directory" in MTK_OT_import_minecraft_save.__annotations__
    assert "min_coord" in MTK_OT_import_minecraft_save.__annotations__
    assert "max_coord" in MTK_OT_import_minecraft_save.__annotations__
    assert "dimension" in MTK_OT_import_minecraft_save.__annotations__
    assert "run_async" in MTK_OT_import_minecraft_save.__annotations__


@pytest.mark.skipif(not SAMPLE_WORLD_PATH.exists(), reason="Sample Minecraft world not found on system")
def test_inspect_real_minecraft_save():
    """Test inspecting level.dat metadata."""
    meta = inspect_minecraft_save(SAMPLE_WORLD_PATH)
    assert meta["level_name"] == "New World"
    assert meta["data_version"] >= 2844
    assert meta["version_name"] != "Unknown"
    assert "overworld" in meta["dimensions"]
    assert len(meta["spawn"]) == 3


@pytest.mark.skipif(not SAMPLE_WORLD_PATH.exists(), reason="Sample Minecraft world not found on system")
def test_bounded_mesh_save():
    """Test streaming and meshing only a bounded selection."""
    mesh_data, meta, storage, elapsed_ms = load_and_mesh_minecraft_save(
        world_dir=SAMPLE_WORLD_PATH,
        dimension="overworld",
        min_block=(0, -64, 0),
        max_block=(15, 64, 15),
    )

    assert meta["level_name"] == "New World"
    assert mesh_data.vertex_count > 0
    assert mesh_data.quad_count > 0
    assert elapsed_ms < 5000.0  # Should be extremely fast (<100ms)


@pytest.mark.skipif(not SAMPLE_WORLD_PATH.exists(), reason="Sample Minecraft world not found on system")
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

    assert meta["level_name"] == "New World"
    assert mesh_data.vertex_count > 0
    assert len(reports) >= 2, f"Expected progress reports during chunk load and meshing, got {len(reports)}"
    stages = [r.stage for r in reports]
    assert "load_chunks" in stages

