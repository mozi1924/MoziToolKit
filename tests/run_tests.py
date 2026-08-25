"""
Headless Automated Test Suite and CLI Test Runner for MoziToolKit.

Usage:
  blender -b --python tests/run_tests.py -- [options]

Options:
  -f, --fast          Run only fast unit tests (execution time < 3s, ideal for rapid dev & Agent loops)
  -a, --all           Run the full test suite including all integration tests (default)
  -k <pattern>        Run tests / modules whose names match the substring or pattern
  -l, --list          List all discovered test modules and their test cases
  -v, --verbose       Verbose output (verbosity=2)
  -h, --help          Show this help message
"""

import argparse
import importlib
import importlib.util
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
PARENT_DIR = PROJECT_DIR.parent
TESTS_DIR = PROJECT_DIR / "tests"

for p in [str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Activate isolated test sandbox immediately to guarantee 0 contamination of user data/prefs
from tests.test_env import setup_test_sandbox, get_sandbox_path, cleanup_test_sandbox
sandbox_path = setup_test_sandbox()

# Extract bundled extension wheels for headless testing if needed
wheels_dir = PROJECT_DIR / "wheels"
if wheels_dir.exists():
    unpack_dir = Path(tempfile.gettempdir()) / "mozitoolkit_test_wheels"
    unpack_dir.mkdir(parents=True, exist_ok=True)
    if str(unpack_dir) not in sys.path:
        sys.path.insert(0, str(unpack_dir))

    import zipfile
    machine = os.uname().machine if hasattr(os, "uname") else "arm64"
    is_arm = "arm" in machine or "aarch64" in machine

    for prefix, check_folder in [("pillow", "PIL"), ("websockets", "websockets")]:
        if not (unpack_dir / check_folder).exists():
            matched_whl = None
            for whl in sorted(wheels_dir.glob(f"{prefix}*.whl")):
                if sys.platform == "darwin":
                    if "macosx" in whl.name:
                        if is_arm and "arm64" in whl.name:
                            matched_whl = whl
                            break
                        elif not is_arm and "x86_64" in whl.name:
                            matched_whl = whl
                            break
                    elif "py3-none-any" in whl.name:
                        matched_whl = whl
                elif sys.platform == "win32":
                    if "win" in whl.name or "py3-none-any" in whl.name:
                        matched_whl = whl
                        break
                elif sys.platform.startswith("linux"):
                    if "manylinux" in whl.name or "py3-none-any" in whl.name:
                        matched_whl = whl
                        break
            if matched_whl and matched_whl.exists():
                with zipfile.ZipFile(matched_whl, "r") as zf:
                    zf.extractall(unpack_dir)

# Ensure any existing add-on instance is cleanly unloaded in the test sandbox
try:
    import addon_utils
    for mod in list(addon_utils.modules()):
        if "mozitoolkit" in mod.__name__.lower() or "mozitoolkit" in getattr(mod, "__file__", "").lower():
            if addon_utils.check(mod.__name__)[0]:
                addon_utils.disable(mod.__name__)
except Exception:
    pass

# Ensure MoziToolKit package is registered in sys.modules
if "MoziToolKit" not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        "MoziToolKit",
        str(PROJECT_DIR / "__init__.py"),
        submodule_search_locations=[str(PROJECT_DIR)]
    )
    if spec and spec.loader:
        pkg = importlib.util.module_from_spec(spec)
        sys.modules["MoziToolKit"] = pkg
        spec.loader.exec_module(pkg)
        if hasattr(pkg, "register"):
            try:
                pkg.register()
            except Exception:
                pass

# Alias top-level subpackages so both `from utils...` and `from MoziToolKit.utils...` work
for mod_name, mod in list(sys.modules.items()):
    if mod_name.startswith("MoziToolKit."):
        short_name = mod_name[len("MoziToolKit."):]
        if short_name not in sys.modules:
            sys.modules[short_name] = mod

# Modules classified as fast unit tests (pure math, conversions, parsers, resolvers)
FAST_UNIT_MODULES = {
    "test_atlas_material_metadata",
    "test_atlas_uv_rotation",
    "test_atlas_uv_tiling",
    "test_biome_materials",
    "test_config_manager",
    "test_dependencies",
    "test_directional_block_orientations",
    "test_jmc2obj_matching",
    "test_live_sync_empty_slots_and_entities",
    "test_live_sync_protocol_and_storage",
    "test_mc_model_baker",
    "test_mineways_atlas_unpack",
    "test_mineways_matching",
    "test_pack_stack_and_fallback",
    "test_pbr_pack_stack",
    "test_rect_packer",
    "test_repair_fluid_uv",
    "test_sandbox_isolation",
    "test_yefira_multiface_states",
}


def discover_test_modules():
    """Discover all test_*.py modules in the tests directory."""
    modules = []
    for file in sorted(TESTS_DIR.glob("test_*.py")):
        mod_name = file.stem
        modules.append(mod_name)
    return modules


def load_suite_for_modules(module_names, filter_pattern=None):
    """Load test cases from the specified module names, optionally filtering by pattern."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    loaded_counts = {}

    for mod_name in module_names:
        try:
            mod = importlib.import_module(f"tests.{mod_name}")
            mod_suite = loader.loadTestsFromModule(mod)

            if filter_pattern:
                filtered_suite = unittest.TestSuite()
                for test in _flatten_suite(mod_suite):
                    test_id = test.id().lower()
                    if filter_pattern.lower() in test_id or filter_pattern.lower() in mod_name.lower():
                        filtered_suite.addTest(test)
                mod_suite = filtered_suite

            count = mod_suite.countTestCases()
            if count > 0:
                suite.addTest(mod_suite)
                loaded_counts[mod_name] = count
        except Exception as e:
            print(f"[ERROR] Failed to load {mod_name}: {e}")

    return suite, loaded_counts


def _flatten_suite(suite):
    """Yield all individual TestCase instances from a TestSuite."""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten_suite(item)
        else:
            yield item


def list_tests(module_names):
    """Print all discovered test modules and their test cases."""
    print("=" * 70)
    print("DISCOVERED TEST MODULES")
    print("=" * 70)
    total_tests = 0
    for mod_name in module_names:
        is_fast = mod_name in FAST_UNIT_MODULES
        tag = "[FAST]" if is_fast else "[INTEGRATION]"
        try:
            mod = importlib.import_module(f"tests.{mod_name}")
            mod_suite = unittest.TestLoader().loadTestsFromModule(mod)
            tests = list(_flatten_suite(mod_suite))
            print(f"  {tag:<15} {mod_name} ({len(tests)} tests)")
            for t in tests:
                print(f"      - {t._testMethodName}")
            total_tests += len(tests)
        except Exception as e:
            print(f"  [ERROR]         {mod_name}: {e}")
    print("=" * 70)
    print(f"Total: {len(module_names)} modules, {total_tests} tests")
    print("=" * 70)


def main():
    # Filter out blender args up to '--'
    cli_args = []
    if "--" in sys.argv:
        cli_args = sys.argv[sys.argv.index("--") + 1:]

    parser = argparse.ArgumentParser(
        description="MoziToolKit Automated Test Runner",
        prog="blender -b --python tests/run_tests.py --"
    )
    parser.add_argument("-f", "--fast", action="store_true", help="Run fast unit tests only (<3s)")
    parser.add_argument("-a", "--all", action="store_true", help="Run all tests (default)")
    parser.add_argument("-k", "--filter", type=str, default=None, help="Filter tests by substring pattern")
    parser.add_argument("-l", "--list", action="store_true", help="List discovered tests")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args(cli_args)

    all_modules = discover_test_modules()

    if args.list:
        list_tests(all_modules)
        return 0

    if args.fast and not args.filter:
        target_modules = [m for m in all_modules if m in FAST_UNIT_MODULES]
        mode_label = f"FAST UNIT TESTS ({len(target_modules)} modules)"
    else:
        target_modules = all_modules
        mode_label = f"FULL TEST SUITE ({len(target_modules)} modules)"

    suite, counts = load_suite_for_modules(target_modules, filter_pattern=args.filter)
    total_test_count = suite.countTestCases()

    print("=" * 70)
    print(f"MOZITOOLKIT TEST RUNNER: {mode_label}")
    print(f"SANDBOX ISOLATION: ACTIVE ({get_sandbox_path()})")
    print(f"USER BLENDER CONFIG & BAKED CACHES: PROTECTED")
    if args.filter:
        print(f"Pattern Filter: '{args.filter}'")
    print(f"Executing {total_test_count} tests across {len(counts)} modules...")
    print("=" * 70)

    start_time = time.time()
    verbosity = 2 if args.verbose else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    elapsed = time.time() - start_time

    print("=" * 70)
    print(f"SUMMARY: Ran {result.testsRun} tests in {elapsed:.2f}s")
    print(f"  - Passed:   {result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)}")
    print(f"  - Failures: {len(result.failures)}")
    print(f"  - Errors:   {len(result.errors)}")
    print(f"  - Skipped:  {len(result.skipped)}")
    print("=" * 70)

    if not result.wasSuccessful():
        return 1
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
