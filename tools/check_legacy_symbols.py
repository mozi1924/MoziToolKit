"""Fail on retired 2.0 symbols that must not reappear in live code.

Historical planning docs, tests that assert absence, localized DIM strings, and
the legitimate internal `SectionMesher` used by mtk-voxel/WASM/bench are excluded.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
MOZI = ROOT / "MoziToolKit"
LIB = ROOT / "libmozitoolkit"

SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "target",
    "wheels",
    "dist",
    "node_modules",
    "site-packages",
}
SKIP_SUFFIXES = {".md"}
SCAN_SUFFIXES = {".py", ".rs", ".toml", ".json", ".yml", ".yaml", ".sh", ".ps1", ".js", ".ts"}

PATTERNS = {
    "SectionMesher": re.compile(r"\bSectionMesher\b"),
    "process_mesh_extrude_repair": re.compile(r"\bprocess_mesh_extrude_repair\b"),
    "process_random_extrude_mesh": re.compile(r"\bprocess_random_extrude_mesh(?!_)"),
    "process_mesh(": re.compile(r"\bprocess_mesh\("),
    "direct_copy_": re.compile(r"\bdirect_copy_"),
    "unified_mesh": re.compile(r"\bunified_mesh\b"),
    "remesh_from_voxel_cloud": re.compile(r"\bremesh_from_voxel_cloud\b"),
    "rematerialize_from_voxel_cloud": re.compile(r"\brematerialize_from_voxel_cloud\b"),
    "update_material_shading_adaptation": re.compile(r"\bupdate_material_shading_adaptation\b"),
    "clean_empty_material_slots": re.compile(r"\bclean_empty_material_slots\b"),
    "mozi.replace_materials": re.compile(r"\bmozi\.replace_materials\b"),
    "MENU_SCHEMA_VERSION": re.compile(r"\bMENU_SCHEMA_VERSION\b"),
    "Lz4": re.compile(r"\bLz4\b"),
    "XxHash64": re.compile(r"\bXxHash64\b"),
    "DIM-1": re.compile(r"\bDIM-1\b"),
    "DIM1": re.compile(r"\bDIM1\b"),
    "REPLAY_DELTAS": re.compile(r"\bREPLAY_DELTAS\b"),
}

SECTION_MESHER_ALLOWED = (
    "libmozitoolkit/crates/mtk-voxel/",
    "libmozitoolkit/bindings/mtk-wasm/",
    "libmozitoolkit/crates/mtk-bench/",
    "libmozitoolkit/crates/libmtk/src/lib.rs",
)
DIM_ALLOWED = (
    "MoziToolKit/i18n/",
    "MoziToolKit/operators/save/op_import_save.py",
)


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _skip(path: Path) -> bool:
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    if path.suffix.lower() not in SCAN_SUFFIXES:
        return True
    rel = _relative(path)
    if any(part in SKIP_DIRS for part in path.parts):
        return True
    if "/tests/" in f"/{rel}" or rel.startswith("MoziToolKit/tests/"):
        return True
    if rel.startswith(("MoziToolKit/tools/", "libmozitoolkit/tools/")):
        return True
    return False


def _allowed(name: str, rel: str) -> bool:
    if name == "SectionMesher" and rel.startswith(SECTION_MESHER_ALLOWED):
        return True
    if name in ("DIM-1", "DIM1") and rel.startswith(DIM_ALLOWED):
        return True
    if name in ("process_mesh_extrude_repair", "process_random_extrude_mesh") and rel.startswith(
        "libmozitoolkit/crates/mtk-core/"
    ):
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit a JSON summary")
    args = parser.parse_args()

    violations: list[dict] = []
    allowed_hits: list[dict] = []
    scanned = 0
    for repo in (MOZI, LIB):
        if not repo.is_dir():
            continue
        for path in repo.rglob("*"):
            if not path.is_file() or _skip(path):
                continue
            scanned += 1
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            rel = _relative(path)
            for line_no, line in enumerate(text.splitlines(), 1):
                for name, pattern in PATTERNS.items():
                    if not pattern.search(line):
                        continue
                    hit = {"pattern": name, "path": rel, "line": line_no, "text": line.strip()}
                    if _allowed(name, rel):
                        allowed_hits.append(hit)
                    else:
                        violations.append(hit)

    summary = {
        "status": "pass" if not violations else "failed",
        "scanned_files": scanned,
        "violations": violations,
        "allowed_hits": allowed_hits,
    }
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"scanned {scanned} files; {len(violations)} violation(s), {len(allowed_hits)} allowed hit(s)")
        for hit in violations:
            print(f"  {hit['path']}:{hit['line']}: {hit['pattern']}: {hit['text']}")
        for hit in allowed_hits:
            print(f"  allowed {hit['path']}:{hit['line']}: {hit['pattern']}")
    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
