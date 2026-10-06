"""
Headless pytest entrypoint for the MoziToolKit test suite.

Works both as a standalone script and inside Blender:

    python tests/run_tests.py -q

    # Full Blender host suite (bpy-backed integration tests enabled):
    blender --background --python tests/run_tests.py -- -q

When invoked from Blender, point `MTK_TEST_SITE_PACKAGES` at the virtualenv
site-packages directory so `pytest` and the `libmtk_py` abi3 wheel are importable:

    MTK_TEST_SITE_PACKAGES="$(python -c 'import site; print(site.getsitepackages()[0])')" \\
        blender --background --python tests/run_tests.py -- -q
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
for _path in (PROJECT_DIR, PROJECT_DIR.parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

_site_packages = os.environ.get("MTK_TEST_SITE_PACKAGES")
if _site_packages and _site_packages not in sys.path:
    sys.path.insert(0, _site_packages)


def main() -> int:
    try:
        import pytest
    except ImportError as exc:  # pragma: no cover - environment misconfiguration
        raise SystemExit(
            "pytest is not importable. Install it into the active interpreter or set "
            "MTK_TEST_SITE_PACKAGES to the virtualenv site-packages directory."
        ) from exc

    extra_args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return pytest.main([str(PROJECT_DIR / "tests"), *extra_args])


if __name__ == "__main__":
    raise SystemExit(main())
