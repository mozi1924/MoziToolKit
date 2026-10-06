import os
import sys
import types
from unittest.mock import MagicMock
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
TESTS_DIR = Path(__file__).parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
site_pkgs = PROJECT_DIR / "site-packages"
dev_lib = PROJECT_DIR / "dev" / "lib"

# Make both `import MoziToolKit...` and top-level `import bridge...` work, and mount the
# dev direct-link native library before test modules are collected (several modules do
# `import libmtk_py` at import time).
for _path in (PROJECT_DIR, TESTS_DIR, PARENT_DIR, site_pkgs, dev_lib):
    if _path.exists() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

if "mathutils" not in sys.modules:
    sys.modules["mathutils"] = MagicMock()

if "bmesh" not in sys.modules:
    sys.modules["bmesh"] = MagicMock()

if "bpy_extras" not in sys.modules:
    bpy_extras = types.ModuleType("bpy_extras")
    bpy_extras.__path__ = []
    io_utils = types.ModuleType("bpy_extras.io_utils")
    io_utils.ExportHelper = object
    io_utils.ImportHelper = object
    bpy_extras.io_utils = io_utils
    sys.modules["bpy_extras"] = bpy_extras
    sys.modules["bpy_extras.io_utils"] = io_utils

try:
    import bpy
    HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "meshes")
except ImportError:
    bpy = MagicMock()
    HAS_BPY = False

if not HAS_BPY:
    class _MockOperator: pass
    class _MockPanel: pass
    class _MockMenu: pass
    class _MockPropertyGroup: pass
    class _MockUIList: pass
    class _MockAddonPreferences: pass

    class _MockTypes:
        Operator = _MockOperator
        Panel = _MockPanel
        Menu = _MockMenu
        PropertyGroup = _MockPropertyGroup
        UIList = _MockUIList
        AddonPreferences = _MockAddonPreferences

    bpy.types = _MockTypes
    bpy.app = MagicMock()
    bpy.props = MagicMock()

    sys.modules["bpy"] = bpy
    sys.modules["bpy.props"] = bpy.props
    sys.modules["bpy.types"] = _MockTypes
    sys.modules["bpy.app"] = bpy.app
    sys.modules["bmesh"] = MagicMock()

# Best-effort native engine mount (dev direct-link). Runs after bpy is mocked so that
# importing the `MoziToolKit` package does not pull real Blender APIs.
try:
    from MoziToolKit.dev import loader as _dev_loader

    _dev_loader.setup_dev_environment()
except Exception:
    pass

try:
    from MoziToolKit.bridge.engine import get_libmtk

    get_libmtk()
except Exception:
    try:
        from bridge.engine import get_libmtk

        get_libmtk()
    except Exception:
        pass
