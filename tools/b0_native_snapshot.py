"""Record the B0 native API surface for libmtk_py + libmtk_blender_dna."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "dev" / "lib"))

import libmtk_py  # noqa: E402
import libmtk_blender_dna  # noqa: E402

FIXTURES = PROJECT_DIR / "tests" / "fixtures"
FIXTURES.mkdir(parents=True, exist_ok=True)

FORBIDDEN = (
    "SectionMesher",
    "process_mesh",
    "process_mesh_extrude_repair",
    "process_random_extrude_mesh",
    "get_block_states",
    "get_biomes",
)
FORBIDDEN_PREFIXES = ("direct_copy_",)
REQUIRED = (
    "VoxelWorld",
    "VoxelPointCloud",
    "VoxelStorage",
    "MeshData",
    "build_material_palette",
    "compute_biome_tint_attributes_paletted",
)


def main() -> None:
    top_level = sorted(name for name in dir(libmtk_py) if not name.startswith("_"))
    mesh_methods = sorted(
        name for name in dir(libmtk_py.MeshData) if not name.startswith("_")
    )
    unstable = getattr(libmtk_py, "unstable", None)
    unstable_names = sorted(
        name for name in dir(unstable) if not name.startswith("_")
    ) if unstable is not None else []

    forbidden_hits = [
        name
        for name in top_level
        if name in FORBIDDEN or any(name.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)
    ]
    missing_required = [name for name in REQUIRED if name not in top_level]
    checks = {
        "api_version": libmtk_py.api_version() == 1,
        "dna_api_version": libmtk_blender_dna.api_version() == 1,
        "core_has_no_blender_dna": not hasattr(unstable, "blender_dna"),
        "forbidden_native_symbols_absent": not forbidden_hits,
        "required_native_symbols_present": not missing_required,
        "from_flat_polygons_present": hasattr(libmtk_py.MeshData, "from_flat_polygons"),
        "dna_generic_copy_surface": all(
            hasattr(libmtk_blender_dna, name)
            for name in ("copy_f32", "copy_i32", "copy_u32", "copy_u8")
        ),
    }
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "libmtk_py": {
            "version": libmtk_py.version(),
            "api_version": libmtk_py.api_version(),
            "top_level": top_level,
            "mesh_data_methods": mesh_methods,
            "unstable": unstable_names,
        },
        "libmtk_blender_dna": {
            "api_version": libmtk_blender_dna.api_version(),
            "functions": sorted(
                name
                for name in dir(libmtk_blender_dna)
                if not name.startswith("_")
            ),
        },
        "forbidden_hits": forbidden_hits,
        "missing_required": missing_required,
        "checks": checks,
        "status": "pass" if all(checks.values()) else "failed",
    }
    (FIXTURES / "b0_native_api.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("B0_NATIVE_SNAPSHOT", json.dumps(report, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
