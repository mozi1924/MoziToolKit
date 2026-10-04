"""
MoziToolKit Development Loader.
Dynamically resolves and mounts local development native libraries (libmtk_py)
without requiring extension wheel installations.
"""

import os
import sys
import platform
from pathlib import Path

DEV_DIR = Path(__file__).parent.resolve()
DEV_LIB_DIR = DEV_DIR / "lib"
TOOLKIT_ROOT = DEV_DIR.parent.resolve()
RUST_ROOT = TOOLKIT_ROOT.parent / "libmozitoolkit"


def ensure_dev_binary() -> Path | None:
    """
    Locates or symlinks the native libmtk_py shared library for development.
    Returns the path to the resolved .so / .pyd if found.
    """
    DEV_LIB_DIR.mkdir(parents=True, exist_ok=True)

    is_windows = platform.system() == "Windows"
    target_names = ["libmtk_py.pyd"] if is_windows else ["libmtk_py.so", "libmtk_py.abi3.so"]

    # 1. Check existing in dev/lib/
    for name in target_names:
        candidate = DEV_LIB_DIR / name
        if candidate.exists():
            return candidate

    # 2. Check rust workspace target/release/
    rust_release_dir = RUST_ROOT / "target" / "release"
    rust_candidates = [
        rust_release_dir / "libmtk_py.so",
        rust_release_dir / "liblibmtk_py.so",
        rust_release_dir / "libmtk_py.dylib",
        rust_release_dir / "liblibmtk_py.dylib",
        rust_release_dir / "libmtk_py.dll",
        rust_release_dir / "libmtk_py.pyd",
    ]

    for rust_bin in rust_candidates:
        if rust_bin.exists():
            dest_name = "libmtk_py.pyd" if is_windows else "libmtk_py.so"
            dest = DEV_LIB_DIR / dest_name
            try:
                if dest.is_symlink() or dest.exists():
                    dest.unlink()
                dest.symlink_to(rust_bin.resolve())
                return dest
            except OSError:
                # If symlink not permitted (e.g. non-admin Windows), copy instead
                try:
                    import shutil
                    shutil.copy2(rust_bin, dest)
                    return dest
                except Exception:
                    pass

    return None


def reload_dev_binary() -> bool:
    """
    Forces hot-reloading of the latest compiled Rust binary into running Python process.
    Bypasses OS dlopen inode/path caching by creating timestamped version files.
    """
    rust_release_dir = RUST_ROOT / "target" / "release"
    rust_candidates = [
        rust_release_dir / "liblibmtk_py.so",
        rust_release_dir / "libmtk_py.so",
        rust_release_dir / "libmtk_py.pyd",
    ]
    rust_bin = next((p for p in rust_candidates if p.exists()), None)
    if not rust_bin:
        return False

    import shutil
    import importlib.machinery
    mtime = int(rust_bin.stat().st_mtime)
    ext = rust_bin.suffix
    dest = DEV_LIB_DIR / f"libmtk_py_hot_{mtime}{ext}"
    if not dest.exists():
        shutil.copy2(rust_bin, dest)

    try:
        loader = importlib.machinery.ExtensionFileLoader("libmtk_py", str(dest))
        spec = importlib.machinery.ModuleSpec(name="libmtk_py", loader=loader, origin=str(dest))
        mod = loader.create_module(spec)
        loader.exec_module(mod)
        sys.modules["libmtk_py"] = mod
        try:
            from ..bridge import engine
            engine._libmtk = mod
        except Exception:
            pass
        return True
    except Exception:
        return False


def setup_dev_environment() -> bool:
    """
    Ensures dev/lib is added to sys.path and libmtk_py is importable.
    Returns True if libmtk_py is successfully available.
    """
    dev_bin = ensure_dev_binary()
    if dev_bin and str(DEV_LIB_DIR) not in sys.path:
        sys.path.insert(0, str(DEV_LIB_DIR))

    try:
        import libmtk_py  # noqa: F401
        return True
    except ImportError:
        return False


def get_engine_status() -> dict:
    """
    Inspects active libmtk_py runtime state, build origin, and capabilities.
    """
    info = {
        "available": False,
        "mode": "Not Found",
        "path": "None",
        "version": "Unknown",
        "is_dev": False,
    }

    try:
        import libmtk_py
        info["available"] = True
        info["version"] = getattr(libmtk_py, "version", lambda: "Unknown")()
        mod_file = getattr(libmtk_py, "__file__", "")
        info["path"] = mod_file

        if str(DEV_LIB_DIR) in mod_file or "target/release" in mod_file:
            info["mode"] = "Dev Direct Shared Library (.so)"
            info["is_dev"] = True
        else:
            info["mode"] = "Extension Wheel / Isolated Env"
            info["is_dev"] = False
    except ImportError as e:
        info["error"] = str(e)

    return info
