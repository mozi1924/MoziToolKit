"""B0 Blender smoke: registration, context menus, debug world, carving remesh.

Run from a Blender background process:

    blender --background --python tools/b0_blender_smoke.py

Writes machine-readable snapshots to ``tests/fixtures/`` and exits non-zero on
any failed check.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
from pathlib import Path

import bpy

PROJECT_DIR = Path(__file__).resolve().parents[1]
PARENT_DIR = PROJECT_DIR.parent
for _path in (PROJECT_DIR, PARENT_DIR, PROJECT_DIR / "dev" / "lib"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import MoziToolKit  # noqa: E402
from MoziToolKit.utils.system.menu_registry import (  # noqa: E402
    draw_dynamic_menu,
    get_all_operators,
)

FIXTURES = PROJECT_DIR / "tests" / "fixtures"
FIXTURES.mkdir(parents=True, exist_ok=True)

INTERNAL_IDS = {
    "mozi.remesh_from_voxel_cloud",
    "mozi.rematerialize_from_voxel_cloud",
    "mozi.clean_empty_material_slots",
    "mozi.update_material_shading_adaptation",
}


class MenuRecorder:
    def __init__(self) -> None:
        self.operator_context = ""
        self.operators: list[str] = []
        self.labels: list[str] = []

    def separator(self) -> None:
        pass

    def label(self, text: str = "", **kwargs) -> None:
        self.labels.append(text)

    def operator(self, operator: str, text: str | None = None, **kwargs) -> None:
        self.operators.append(operator)


def _register_addon() -> None:
    if hasattr(bpy.types, "MOZI_OT_rebuild_mesh"):
        return
    MoziToolKit.register()


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _draw_menu(view: str) -> list[str]:
    recorder = MenuRecorder()
    draw_dynamic_menu(recorder, view)
    return recorder.operators


def _cleanup_objects(*names: str) -> None:
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)


def main() -> None:
    addon_version = "2.0.0"
    try:
        import tomllib

        manifest = tomllib.loads((PROJECT_DIR / "blender_manifest.toml").read_text(encoding="utf-8"))
        addon_version = str(manifest.get("version", addon_version))
    except Exception:
        pass

    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "blender_version": bpy.app.version_string,
        "addon_version": addon_version,
        "status": "running",
        "checks": {},
    }
    try:
        _register_addon()
        report["checks"]["registration"] = hasattr(bpy.types, "MOZI_OT_rebuild_mesh")

        operator_details = get_all_operators()
        operators = sorted(operator_details)
        report["operators"] = operators
        report["operator_details"] = operator_details
        report["operator_count"] = len(operators)
        report["checks"]["no_internal_operators"] = not (INTERNAL_IDS & set(operators))
        report["checks"]["rebuild_operator_registered"] = "mozi.rebuild_mesh" in operators
        report["checks"]["no_empty_uv_menu"] = not hasattr(
            bpy.types, "MOZI_MT_select_uv_menu"
        )

        object_menu = _draw_menu("object")
        mesh_menu = _draw_menu("mesh")
        report["menus"] = {"object": object_menu, "mesh": mesh_menu}
        report["checks"]["object_menu_nonempty"] = bool(object_menu)
        report["checks"]["mesh_menu_nonempty"] = bool(mesh_menu)
        report["checks"]["menus_only_registered"] = set(object_menu + mesh_menu).issubset(
            set(operators)
        )
        report["checks"]["rebuild_in_object_menu"] = "mozi.rebuild_mesh" in object_menu
        report["checks"]["rebuild_in_mesh_menu"] = "mozi.rebuild_mesh" in mesh_menu
        report["checks"]["no_internal_menu_items"] = not (
            INTERNAL_IDS & set(object_menu + mesh_menu)
        )

        # Debug world ingestion.
        from MoziToolKit.utils.world import create_debug_world_object

        debug_obj, debug_stats = create_debug_world_object(
            name="B0_Debug_World",
            reuse_existing=False,
        )
        report["debug_world"] = {
            "object": debug_obj.name,
            "vertices": len(debug_obj.data.vertices),
            "polygons": len(debug_obj.data.polygons),
            "stats": {
                key: debug_stats.get(key)
                for key in ("voxel_count", "elapsed_ms", "meshing_time_ms")
                if key in debug_stats
            },
        }
        report["checks"]["debug_world_mesh"] = (
            len(debug_obj.data.vertices) > 1000
            and len(debug_obj.data.polygons) > 1000
        )
        _cleanup_objects(debug_obj.name)

        # Carve the center of a 3x3x3 cube and rebuild through the real operator.
        import libmtk_py
        from MoziToolKit.bridge.point_cloud import (
            extract_voxel_point_cloud,
            inject_voxel_point_cloud,
        )
        from MoziToolKit.utils.world import ingest_voxel_world

        storage = libmtk_py.VoxelStorage()
        storage.set_bounds(0, 0, 0, 16, 16, 16)
        for x in range(3):
            for y in range(3):
                for z in range(3):
                    storage.set_block(x, y, z, "minecraft:stone", "minecraft:plains")

        carve_obj, carve_stats = ingest_voxel_world(storage, name="B0_Carve_World")
        cloud_name = carve_stats["voxel_cloud_name"]
        cloud_obj = bpy.data.objects[cloud_name]
        initial_polys = len(carve_obj.data.polygons)
        extracted = extract_voxel_point_cloud(cloud_obj)
        _assert(len(extracted) == 27, "3x3x3 cloud must contain 27 points")

        carved = libmtk_py.VoxelPointCloud()
        positions = extracted.positions_memoryview().cast("f")
        state_palette = extracted.get_state_palette()
        biome_palette = extracted.get_biome_palette()
        state_indices = extracted.state_indices_memoryview().cast("i")
        biome_indices = extracted.biome_indices_memoryview().cast("i")
        for i in range(len(extracted)):
            bx = extracted.block_x_memoryview().cast("i")[i]
            by = extracted.block_y_memoryview().cast("i")[i]
            bz = extracted.block_z_memoryview().cast("i")[i]
            if (bx, by, bz) == (1, 1, 1):
                continue
            off = i * 3
            carved.push(
                [positions[off], positions[off + 1], positions[off + 2]],
                [bx, by, bz],
                state_palette[state_indices[i]],
                biome_palette[biome_indices[i]],
                0,
            )
        _assert(len(carved) == 26, "carved cloud must contain 26 points")
        inject_voxel_point_cloud(cloud_obj, carved)

        bpy.context.view_layer.objects.active = carve_obj
        carve_obj.select_set(True)
        result = bpy.ops.mozi.rebuild_mesh(run_async=False)
        carved_polys = len(carve_obj.data.polygons)
        report["carve"] = {
            "initial_polygons": initial_polys,
            "carved_polygons": carved_polys,
            "result": sorted(result),
        }
        report["checks"]["carve_operator_finished"] = result == {"FINISHED"}
        report["checks"]["carve_exposes_cavity"] = (
            initial_polys == 54 and carved_polys == 60
        )
        _cleanup_objects(carve_obj.name, cloud_name)
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        (FIXTURES / "b0_blender_smoke.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        raise
    else:
        report["status"] = "pass"
        failures = [name for name, ok in report["checks"].items() if not ok]
        report["failures"] = failures
        if failures:
            report["status"] = "failed"
        (FIXTURES / "b0_blender_smoke.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (FIXTURES / "b0_operators.json").write_text(
            json.dumps(
                {
                    "generated_at": report["generated_at"],
                    "addon_version": report["addon_version"],
                    "operators": operators,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print("B0_SMOKE_REPORT", json.dumps(report, sort_keys=True))
        if failures:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
