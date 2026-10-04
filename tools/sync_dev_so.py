#!/usr/bin/env python3
"""
MoziToolKit Developer Helper:
Synchronizes or compiles the release libmtk_py shared library into dev/lib/.
"""

import sys
from pathlib import Path

import importlib.util

DEV_DIR = Path(__file__).parent.parent / "dev"
spec = importlib.util.spec_from_file_location("loader", DEV_DIR / "loader.py")
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)

ensure_dev_binary = loader.ensure_dev_binary
get_engine_status = loader.get_engine_status


def main():
    print("🔧 Synchronizing MoziToolKit Dev Shared Library...")
    dev_bin = ensure_dev_binary()
    if dev_bin:
        print(f"✅ Active development binary: {dev_bin}")
        loader.setup_dev_environment()
        status = get_engine_status()
        print(f"📊 Engine Status: {status['mode']} (v{status['version']})")
    else:
        print("❌ Could not find native binary in target/release/ or dev/lib/.")
        print("💡 Hint: run 'cargo build --release -p mtk-py --features extension-module' in libmozitoolkit first.")
        sys.exit(1)


if __name__ == "__main__":
    main()
