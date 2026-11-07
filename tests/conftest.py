"""
Pytest configuration for the MoziToolKit test suite.

STRICT INVARIANT (GEMINI.md Rule 9):
All tests MUST execute inside a real Blender 5.x LTS host environment.
MagicMock and headless mock bpy/bmesh/mathutils environments are strictly forbidden.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest

os.environ.setdefault("MTK_TEST_SANDBOX", "1")

# 1. Enforce real Blender host environment gate
try:
    import bpy
    import bmesh
    import mathutils

    if not hasattr(bpy, "data") or not hasattr(bpy.data, "meshes") or type(bpy).__name__ == "MagicMock":
        raise ImportError("bpy.data is not accessible or is mocked")
except (ImportError, AttributeError) as exc:
    raise RuntimeError(
        "\n===============================================================================\n"
        "[FATAL] MoziToolKit tests must be run inside the real Blender host environment!\n"
        "Standalone python / mock execution is strictly forbidden (see GEMINI.md Rule 9).\n\n"
        "Run the test suite using:\n"
        "  MTK_TEST_SITE_PACKAGES=\"$(uv run python -c 'import site; print(site.getsitepackages()[0])')\" \\\n"
        "    blender --background --python tests/run_tests.py -- -q\n"
        "==============================================================================="
    ) from exc

# 2. Setup project paths and dev direct-link bindings
PROJECT_DIR = Path(__file__).parent.parent.resolve()
TESTS_DIR = Path(__file__).parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
site_pkgs = PROJECT_DIR / "site-packages"
dev_lib = PROJECT_DIR / "dev" / "lib"

for _path in (PROJECT_DIR, TESTS_DIR, PARENT_DIR, site_pkgs, dev_lib):
    if _path.exists() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

# Dev native module loader
try:
    from MoziToolKit.dev import loader as _dev_loader
    _dev_loader.setup_dev_environment()
except Exception:
    pass

try:
    from MoziToolKit.bridge.engine import get_libmtk
    get_libmtk()
except Exception:
    pass

# Ensure addon properties and operators are registered in Blender test runtime
try:
    import MoziToolKit
    MoziToolKit.register()
except Exception:
    pass


@pytest.fixture(autouse=True)
def clean_blender_state():
    """
    Ensure each test starts and ends with a clean Blender state.
    Purges temporary objects, meshes, and materials created during testing.
    """
    yield
    # Cleanup any orphan test meshes and objects
    try:
        if hasattr(bpy.data, "objects"):
            for obj in list(bpy.data.objects):
                if obj.name.startswith(("test_", "Test_", "Yefira_", "MTK_", "Mesh_", "Cloud_")):
                    bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:
        pass
