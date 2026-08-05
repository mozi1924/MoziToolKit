#!/usr/bin/env python3
"""
MoziToolKit Packaging Script
Packages the Blender extension into an installable .zip file in the dist/ directory.
Ignores files specified in .gitignore, as well as .gitignore itself and this script.
"""

import argparse
import fnmatch
import os
import re
import subprocess
import sys
import zipfile

try:
    import tomllib
except ImportError:
    tomllib = None


def parse_manifest(project_dir):
    """Extract extension id and version from blender_manifest.toml or __init__.py."""
    manifest_path = os.path.join(project_dir, "blender_manifest.toml")
    ext_id = None
    ext_version = None

    if os.path.exists(manifest_path):
        if tomllib:
            try:
                with open(manifest_path, "rb") as f:
                    data = tomllib.load(f)
                    ext_id = data.get("id")
                    ext_version = data.get("version")
            except Exception as e:
                print(f"[Warning] Failed to parse {manifest_path} with tomllib: {e}")

        if not ext_id or not ext_version:
            with open(manifest_path, "r", encoding="utf-8") as f:
                content = f.read()
                id_match = re.search(r'id\s*=\s*"([^"]+)"', content)
                version_match = re.search(r'version\s*=\s*"([^"]+)"', content)
                if id_match:
                    ext_id = id_match.group(1)
                if version_match:
                    ext_version = version_match.group(1)

    # Fallback to __init__.py if manifest doesn't give details
    if not ext_id or not ext_version:
        init_path = os.path.join(project_dir, "__init__.py")
        if os.path.exists(init_path):
            with open(init_path, "r", encoding="utf-8") as f:
                content = f.read()
                if not ext_id:
                    name_match = re.search(r'"name":\s*"([^"]+)"', content)
                    ext_id = name_match.group(1).lower() if name_match else "mozitoolkit"
                if not ext_version:
                    ver_match = re.search(r'"version":\s*\(([^)]+)\)', content)
                    if ver_match:
                        ext_version = ".".join([v.strip() for v in ver_match.group(1).split(",")])

    ext_id = ext_id or "mozitoolkit"
    ext_version = ext_version or "1.0.0"
    return ext_id, ext_version


def parse_gitignore(gitignore_path):
    """Parse .gitignore and return a list of pattern rules."""
    patterns = []
    if not os.path.exists(gitignore_path):
        return patterns

    with open(gitignore_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(line)
    return patterns


def matches_gitignore(rel_path, patterns):
    """Check if a relative path matches any gitignore pattern."""
    rel_path_str = rel_path.replace("\\", "/")
    is_dir = os.path.isdir(rel_path)

    for pattern in patterns:
        pat = pattern.strip()
        # Direct folder ignore pattern e.g. "dist/", "__pycache__/"
        dir_only = pat.endswith("/")
        if dir_only:
            pat = pat[:-1]

        # Handle root matching e.g. "/site"
        if pat.startswith("/"):
            pat = pat[1:]
            match_target = rel_path_str
        else:
            match_target = rel_path_str.split("/")[-1]

        if fnmatch.fnmatch(rel_path_str, pat) or fnmatch.fnmatch(match_target, pat):
            if not dir_only or is_dir:
                return True

        # Check path components
        parts = rel_path_str.split("/")
        for part in parts:
            if fnmatch.fnmatch(part, pat):
                return True

    return False


def get_files_via_git(project_dir):
    """Use git ls-files to get all tracked & untracked files respecting .gitignore."""
    try:
        res = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        files = [f.strip() for f in res.stdout.splitlines() if f.strip()]
        return files
    except Exception:
        return None


def get_files_to_package(project_dir, script_rel_path):
    """Get list of relative file paths to package in the extension zip."""
    # Try git command first
    git_files = get_files_via_git(project_dir)
    
    # Excluded files/dirs explicitly requested:
    # 1. .gitignore
    # 2. the script itself
    # 3. dist/ directory
    # 4. .git directory
    script_normalized = os.path.normpath(script_rel_path)

    if git_files is not None:
        valid_files = []
        for rel_path in git_files:
            norm = os.path.normpath(rel_path)
            if norm == ".gitignore":
                continue
            if norm == script_normalized:
                continue
            if norm.startswith("dist" + os.sep) or norm == "dist":
                continue
            if norm.startswith(".git" + os.sep) or norm == ".git":
                continue
            valid_files.append(rel_path)
        return sorted(valid_files)

    # Fallback to manual directory walk with .gitignore parsing
    gitignore_path = os.path.join(project_dir, ".gitignore")
    patterns = parse_gitignore(gitignore_path)

    valid_files = []
    for root, dirs, files in os.walk(project_dir):
        rel_root = os.path.relpath(root, project_dir)
        if rel_root == ".":
            rel_root = ""

        # Skip .git and dist directories
        dirs[:] = [
            d for d in dirs
            if d not in [".git", "dist", "__pycache__"]
            and not matches_gitignore(os.path.join(rel_root, d), patterns)
        ]

        for file in files:
            rel_file = os.path.join(rel_root, file) if rel_root else file
            norm_file = os.path.normpath(rel_file)

            if norm_file == ".gitignore":
                continue
            if norm_file == script_normalized:
                continue
            if matches_gitignore(rel_file, patterns):
                continue

            valid_files.append(rel_file)

    return sorted(valid_files)


def build_package():
    parser = argparse.ArgumentParser(description="Package MoziToolKit extension for Blender.")
    parser.add_argument("-o", "--output-dir", default="dist", help="Output directory for the package (default: dist)")
    args = parser.parse_args()

    project_dir = os.path.abspath(os.path.dirname(__file__))
    script_rel_path = os.path.relpath(__file__, project_dir)

    ext_id, ext_version = parse_manifest(project_dir)
    output_dir = os.path.abspath(os.path.join(project_dir, args.output_dir))
    os.makedirs(output_dir, exist_ok=True)

    zip_filename = f"{ext_id}-{ext_version}.zip"
    output_zip_path = os.path.join(output_dir, zip_filename)

    print(f"📦 Packaging extension '{ext_id}' v{ext_version}...")
    files_to_pack = get_files_to_package(project_dir, script_rel_path)

    print(f"📂 Selected {len(files_to_pack)} files to include:")
    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for rel_file in files_to_pack:
            abs_file = os.path.join(project_dir, rel_file)
            zipf.write(abs_file, rel_file)
            print(f"  + {rel_file}")

    file_size_kb = os.path.getsize(output_zip_path) / 1024
    print(f"\n✅ Packaging complete!")
    print(f"🎉 Created: {output_zip_path} ({file_size_kb:.2f} KB)")


if __name__ == "__main__":
    build_package()
