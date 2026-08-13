"""Diagnose Ice Cube material matching against an unpacked resource pack.

Run with Blender so image nodes in the source library are available::

    /Applications/Blender.app/Contents/MacOS/blender -b \
      "/Users/jaxlocke/Desktop/Ice Cube Asset Library.blend" \
      --python tests/analyze_ice_cube_material_matches.py -- \
      "/Users/jaxlocke/Downloads/Vanilla Mashup 1.5" \
      "/tmp/mozi-material-match-report.json"

The script is read-only: it neither saves the opened .blend nor changes its
datablocks.  Its exact-match column deliberately uses the add-on's current
``extract_material_texture_keys`` rules, making the report a regression
fixture for future matching improvements.
"""

from __future__ import annotations

import difflib
import json
import sys
from collections import Counter
from pathlib import Path

import bpy


PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from utils.material_matching import extract_material_texture_keys
from utils.zip_resource_pack import ZipResourcePack


def resource_pack_albedo_index(pack_path: Path) -> dict[str, set[str]]:
    """Return albedo texture stems by namespace from a pack directory/archive.

    ``*_n`` and ``*_s`` files are LabPBR auxiliary channels and intentionally
    cannot count as a replacement by themselves, just like the production
    replacement step.
    """
    pack = ZipResourcePack(str(pack_path), use_cache=True)
    result: dict[str, set[str]] = {}
    for (namespace, texture_name), texture_info in pack.texture_index.items():
        if texture_info["albedo"]:
            result.setdefault(namespace, set()).add(texture_name)
    return result


def closest_names(candidates: list[str], available: set[str]) -> list[str]:
    """Give diagnostic hints only; these suggestions are never auto-matched."""
    suggestions = []
    for candidate in candidates:
        suggestions.extend(difflib.get_close_matches(candidate, available, n=3, cutoff=0.72))
    return list(dict.fromkeys(suggestions))[:5]


def source_category(mat: bpy.types.Material) -> str:
    """Classify Ice Cube source materials for focused matching summaries."""
    image_paths = []
    if mat.use_nodes and mat.node_tree:
        image_paths = [
            (node.image.filepath or node.image.name).lower()
            for node in mat.node_tree.nodes
            if node.type == "TEX_IMAGE" and node.image
        ]
    if any("mob objs" in path or "/entity/" in path for path in image_paths):
        return "entity"
    if any("armor objs" in path for path in image_paths):
        return "equipment"
    return "other"


def main(pack_path: Path, output_path: Path) -> None:
    index = resource_pack_albedo_index(pack_path)
    rows = []
    for mat in sorted(bpy.data.materials, key=lambda item: item.name.casefold()):
        namespace, candidates = extract_material_texture_keys(mat)
        available = index.get(namespace, set())
        matches = [candidate for candidate in candidates if candidate in available]
        rows.append({
            "material": mat.name,
            "namespace": namespace,
            "candidates": candidates,
            "matched_texture": matches[0] if matches else None,
            "near_matches": [] if matches else closest_names(candidates, available),
            "source_category": source_category(mat),
        })

    matched = [row for row in rows if row["matched_texture"]]
    unmatched = [row for row in rows if not row["matched_texture"]]
    report = {
        "source_blend": bpy.data.filepath,
        "resource_pack": str(pack_path.resolve()),
        "materials_total": len(rows),
        "matched_exactly": len(matched),
        "unmatched": len(unmatched),
        "match_rate": round(len(matched) / len(rows), 4) if rows else 0,
        "unmatched_by_primary_candidate": Counter(
            row["candidates"][0] if row["candidates"] else "<no candidate>"
            for row in unmatched
        ).most_common(),
        "by_source_category": {
            category: {
                "total": sum(row["source_category"] == category for row in rows),
                "matched_exactly": sum(
                    row["source_category"] == category and row["matched_texture"] is not None
                    for row in rows
                ),
            }
            for category in ("entity", "equipment", "other")
        },
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[MoziToolKit] Material match report: {output_path}")
    print(
        f"[MoziToolKit] Exact matches: {len(matched)}/{len(rows)} "
        f"({report['match_rate']:.1%}); unmatched: {len(unmatched)}"
    )
    for row in unmatched[:30]:
        hint = f"; near: {', '.join(row['near_matches'])}" if row["near_matches"] else ""
        print(f"  UNMATCHED {row['material']!r} -> {row['candidates']}{hint}")


if __name__ == "__main__":
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(arguments) != 2:
        raise SystemExit("Expected: <resource-pack-directory-or-archive> <report.json>")
    main(Path(arguments[0]), Path(arguments[1]))
