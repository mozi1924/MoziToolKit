#!/usr/bin/env python3
"""
Precompile the MoziToolKit asset cache for CI real-pack tests.

Reads the fetched real assets from the standard `MTK_TEST_*` environment variables and
emits the Blender-compatible asset cache (models.bin, atlas_mapping.json, ...) into
`MOZI_CACHE_DIR`. Tests then resolve the same directory through `bridge.assets.get_cache_dir()`.

Required env:
  MOZI_CACHE_DIR      Output cache directory (sandbox override honoured by the bridge).
Optional env:
  MTK_TEST_JAR            Minecraft client / modpack jar (preferred).
  MTK_TEST_ASSETS         Unpacked assets root (used if no jar is provided).
  MTK_TEST_RESOURCE_PACK  External resource pack zip (e.g. SPBR) for override fidelity.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _build_stack(mtk):
    stack = mtk.ResourcePackStack()
    added = 0

    jar = os.environ.get("MTK_TEST_JAR")
    assets = os.environ.get("MTK_TEST_ASSETS")
    if jar and Path(jar).is_file():
        stack.add_zip_pack(str(Path(jar).resolve()))
        added += 1
    elif assets and (Path(assets) / "assets").is_dir():
        stack.add_directory_pack(str(Path(assets).resolve()), "VanillaAssets")
        added += 1

    resource_pack = os.environ.get("MTK_TEST_RESOURCE_PACK")
    if resource_pack and Path(resource_pack).is_file():
        stack.add_zip_pack(str(Path(resource_pack).resolve()))
        added += 1

    return stack, added


def main() -> int:
    cache_dir = os.environ.get("MOZI_CACHE_DIR")
    if not cache_dir:
        print("::error::MOZI_CACHE_DIR is not set")
        return 1

    out = Path(cache_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    try:
        import libmtk_py as mtk
    except ImportError:
        # Local dev convenience: mount the dev direct-link `.so` if no wheel is installed.
        dev_lib = Path(__file__).resolve().parents[2] / "dev" / "lib"
        if dev_lib.is_dir():
            sys.path.insert(0, str(dev_lib))
        try:
            import libmtk_py as mtk
        except ImportError as exc:
            print(f"::error::libmtk_py is not importable: {exc}")
            return 1

    stack, added = _build_stack(mtk)
    if added == 0:
        print("::warning::no resource packs available; skipping asset precompilation")
        return 0

    result = mtk.precompile_all_assets(
        stack,
        str(out),
        atlas_category="blocks",
        max_atlas_width=4096,
        max_atlas_height=4096,
        compile_atlas=True,
        compile_standalone=True,
        compile_models=True,
    )
    print(f"Precompiled asset cache into {out}: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
