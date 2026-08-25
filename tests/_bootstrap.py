"""
Shared environment bootstrap for MoziToolKit test modules.

MoziToolKit source modules use package-relative imports that only resolve when
loaded under the ``MoziToolKit.*`` namespace (e.g. ``pipeline.steps.step_x``
imports ``...utils.mesh``). Test modules that import top-level names such as
``pipeline.presets`` or ``operators.sync`` therefore need the package to be
imported first and its subpackages aliased to top-level names in ``sys.modules``.

run_tests.py already performs this bootstrap. Importing this module from a test
file replicates it so the same test also works when executed standalone
(``blender -b --python tests/test_x.py``).
"""

import importlib.util
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
for p in [str(PROJECT_DIR), str(PROJECT_DIR.parent)]:
    if p not in sys.path:
        sys.path.insert(0, p)


def bootstrap_environment() -> None:
    """Import the MoziToolKit package and alias subpackages to top-level names."""
    if "MoziToolKit" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "MoziToolKit",
            str(PROJECT_DIR / "__init__.py"),
            submodule_search_locations=[str(PROJECT_DIR)],
        )
        if spec and spec.loader:
            pkg = importlib.util.module_from_spec(spec)
            sys.modules["MoziToolKit"] = pkg
            spec.loader.exec_module(pkg)

    for mod_name, mod in list(sys.modules.items()):
        if mod_name.startswith("MoziToolKit."):
            short_name = mod_name[len("MoziToolKit."):]
            if short_name not in sys.modules:
                sys.modules[short_name] = mod


bootstrap_environment()
