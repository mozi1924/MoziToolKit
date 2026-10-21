"""
Import convention guards for the MoziToolKit package.

Production code uses package-relative imports only. Tests and tools address the
package through its canonical ``MoziToolKit.*`` name, so every submodule has
exactly one module instance (no dual top-level/package import modes and no
per-call-site fallback branches).
"""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
PACKAGE_ROOTS = ("bridge", "utils", "operators", "ui", "dev", "i18n")
FILE_ROOTS = ("tests", "tools")


def _python_files(base: Path):
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def _absolute_import_roots(tree: ast.AST):
    """Yields (node, root) for every absolute import of a first-party module."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and (node.level or 0) == 0:
            yield node, node.module.split(".")[0]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield node, alias.name.split(".")[0]


def _offenders(base: Path, roots: tuple[str, ...]):
    found = []
    for path in _python_files(base):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node, root in _absolute_import_roots(tree):
            if root in roots:
                found.append(f"{path.relative_to(PROJECT_DIR)}:{node.lineno} imports '{root}'")
    return found


def test_production_uses_relative_imports_only():
    for folder in PACKAGE_ROOTS:
        offenders = _offenders(PROJECT_DIR / folder, (*PACKAGE_ROOTS, "MoziToolKit"))
        assert not offenders, (
            "Production modules must use package-relative imports, not absolute "
            "first-party imports:\n" + "\n".join(offenders)
        )

    entry = PROJECT_DIR / "__init__.py"
    tree = ast.parse(entry.read_text(encoding="utf-8"), filename=str(entry))
    offenders = [
        f"__init__.py:{node.lineno} imports '{root}'"
        for node, root in _absolute_import_roots(tree)
        if root in (*PACKAGE_ROOTS, "MoziToolKit")
    ]
    assert not offenders, "The package entry point must not import itself absolutely:\n" + "\n".join(offenders)


def test_tests_and_tools_use_the_canonical_package_name():
    for folder in FILE_ROOTS:
        offenders = _offenders(PROJECT_DIR / folder, PACKAGE_ROOTS)
        assert not offenders, (
            "Tests/tools must import package modules through 'MoziToolKit.*' so they "
            "share the same module instances as production:\n" + "\n".join(offenders)
        )


def test_relative_imports_do_not_escape_the_package():
    offenders = []
    for folder in PACKAGE_ROOTS:
        for path in _python_files(PROJECT_DIR / folder):
            max_level = len(path.relative_to(PROJECT_DIR).parts)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.level or 0) > max_level:
                    offenders.append(
                        f"{path.relative_to(PROJECT_DIR)}:{node.lineno} "
                        f"climbs {node.level} levels (max {max_level})"
                    )
    assert not offenders, "Relative imports climb past the package root:\n" + "\n".join(offenders)
