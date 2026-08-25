"""
Test Environment Sandbox Guard for MoziToolKit.

Ensures that running unit or integration tests NEVER reads, writes, or modifies
the user's real Blender configuration, keymaps, startup files, resource pack stack,
or baked texture caches.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

_SANDBOX_DIR: Optional[tempfile.TemporaryDirectory] = None
_IS_SANDBOX_ACTIVE = False


def setup_test_sandbox() -> Path:
    """
    Initialize and activate the isolated test sandbox.
    Redirects all configuration and cache directories to an isolated temporary sandbox.
    """
    global _SANDBOX_DIR, _IS_SANDBOX_ACTIVE
    existing_sandbox = os.environ.get("MOZI_TEST_SANDBOX_PATH")
    if existing_sandbox and Path(existing_sandbox).exists():
        _IS_SANDBOX_ACTIVE = True
        return Path(existing_sandbox)

    if _IS_SANDBOX_ACTIVE and _SANDBOX_DIR is not None:
        return Path(_SANDBOX_DIR.name)

    _SANDBOX_DIR = tempfile.TemporaryDirectory(prefix="mozi_test_sandbox_")
    sandbox_path = Path(_SANDBOX_DIR.name)

    config_dir = sandbox_path / "config"
    cache_dir = sandbox_path / "cache"
    temp_dir = sandbox_path / "temp"
    blender_config = sandbox_path / "blender_config"
    blender_scripts = sandbox_path / "blender_scripts"
    blender_datafiles = sandbox_path / "blender_datafiles"

    for d in [config_dir, cache_dir, temp_dir, blender_config, blender_scripts, blender_datafiles]:
        d.mkdir(parents=True, exist_ok=True)

    os.environ["MOZI_TESTING"] = "1"
    os.environ["MOZI_TEST_SANDBOX_PATH"] = str(sandbox_path)
    os.environ["MOZI_CONFIG_DIR"] = str(config_dir)
    os.environ["MOZI_CACHE_DIR"] = str(cache_dir)
    os.environ["MOZI_TEMP_DIR"] = str(temp_dir)
    os.environ["BLENDER_USER_CONFIG"] = str(blender_config)
    os.environ["BLENDER_USER_SCRIPTS"] = str(blender_scripts)
    os.environ["BLENDER_USER_DATAFILES"] = str(blender_datafiles)

    _IS_SANDBOX_ACTIVE = True
    atexit.register(cleanup_test_sandbox)
    return sandbox_path


def cleanup_test_sandbox() -> None:
    """Tear down and remove the temporary test sandbox directory."""
    global _SANDBOX_DIR, _IS_SANDBOX_ACTIVE
    if _SANDBOX_DIR is not None:
        try:
            _SANDBOX_DIR.cleanup()
        except Exception:
            pass
        _SANDBOX_DIR = None
    existing_sandbox = os.environ.pop("MOZI_TEST_SANDBOX_PATH", None)
    if existing_sandbox:
        try:
            shutil.rmtree(existing_sandbox, ignore_errors=True)
        except Exception:
            pass
    _IS_SANDBOX_ACTIVE = False


def get_sandbox_path() -> Optional[Path]:
    """Get current active sandbox directory path."""
    env_path = os.environ.get("MOZI_TEST_SANDBOX_PATH")
    if env_path:
        return Path(env_path)
    if _SANDBOX_DIR is not None:
        return Path(_SANDBOX_DIR.name)
    return None


def is_sandbox_active() -> bool:
    """Return True if isolated test sandbox is active."""
    return _IS_SANDBOX_ACTIVE or bool(os.environ.get("MOZI_TESTING") == "1")


# Automatically activate sandbox whenever this module is imported
setup_test_sandbox()
