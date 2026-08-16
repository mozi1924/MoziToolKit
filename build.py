#!/usr/bin/env python3
"""
MoziToolKit Packaging Script
Packages the Blender extension into an installable .zip file in the dist/ directory.
Defaults to using the official `blender --command extension build` when Blender is available,
with a manifest-compliant pure Python packaging fallback.
"""

import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import zipfile

try:
    import tomllib
except ImportError:
    tomllib = None


def find_blender_binary():
    """Attempt to locate the Blender executable on various platforms."""
    # 1. Environment variable
    env_bin = os.environ.get("BLENDER_BIN") or os.environ.get("BLENDER_PATH")
    if env_bin and os.path.isfile(env_bin) and os.access(env_bin, os.X_OK):
        return env_bin

    # 2. In PATH
    which_bin = shutil.which("blender")
    if which_bin:
        return which_bin

    # 3. macOS standard paths
    mac_paths = [
        "/Applications/Blender.app/Contents/MacOS/blender",
        os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/blender"),
    ]
    for p in mac_paths:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p

    # 4. Linux standard paths
    linux_paths = [
        "/usr/bin/blender",
        "/usr/local/bin/blender",
        "/snap/bin/blender",
        os.path.expanduser("~/.local/bin/blender"),
    ]
    for p in linux_paths:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p

    # 5. Windows standard paths
    for drive in ["C:", "D:", "E:"]:
        win_pattern = os.path.join(drive, r"\Program Files\Blender Foundation\Blender *\blender.exe")
        import glob
        matches = glob.glob(win_pattern)
        if matches:
            return sorted(matches)[-1]

    return None


def parse_manifest(project_dir):
    """Extract extension id, version, and build exclusions from blender_manifest.toml or __init__.py."""
    manifest_path = os.path.join(project_dir, "blender_manifest.toml")
    ext_id = None
    ext_version = None
    exclude_patterns = [
        "__pycache__/",
        "/.git/",
        "/*.zip",
        "tests/",
        "dist/",
        "*.blend",
        "*.blend1",
        ".DS_Store",
        ".vscode/",
        "build.py",
        ".gitignore",
    ]

    if os.path.exists(manifest_path):
        if tomllib:
            try:
                with open(manifest_path, "rb") as f:
                    data = tomllib.load(f)
                    ext_id = data.get("id")
                    ext_version = data.get("version")
                    if "build" in data and "paths_exclude_pattern" in data["build"]:
                        exclude_patterns = data["build"]["paths_exclude_pattern"]
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
    return ext_id, ext_version, exclude_patterns


def matches_exclude_patterns(rel_path, patterns):
    """Check if a relative path matches any exclude pattern from manifest."""
    rel_path_str = rel_path.replace("\\", "/")
    for pat in patterns:
        pat_clean = pat.strip()
        if not pat_clean:
            continue
        if pat_clean.endswith("/"):
            folder_name = pat_clean.rstrip("/")
            if folder_name.startswith("/"):
                folder_name = folder_name.lstrip("/")
            if rel_path_str == folder_name or rel_path_str.startswith(folder_name + "/"):
                return True
        elif pat_clean.startswith("/*"):
            ext = pat_clean[2:]
            if rel_path_str.endswith(ext) or fnmatch.fnmatch(rel_path_str, "*" + ext):
                return True
        elif fnmatch.fnmatch(rel_path_str, pat_clean) or fnmatch.fnmatch(os.path.basename(rel_path_str), pat_clean):
            return True
        parts = rel_path_str.split("/")
        for part in parts:
            if fnmatch.fnmatch(part, pat_clean.rstrip("/")):
                return True
    return False


def get_files_to_package_fallback(project_dir, exclude_patterns=None):
    """Fallback directory walk strictly adhering to paths_exclude_pattern."""
    if exclude_patterns is None:
        exclude_patterns = []

    valid_files = []
    for root, dirs, files in os.walk(project_dir):
        rel_root = os.path.relpath(root, project_dir)
        if rel_root == ".":
            rel_root = ""

        # Filter out directories matching exclusion patterns
        dirs[:] = [
            d for d in dirs
            if not matches_exclude_patterns(
                (f"{rel_root}/{d}" if rel_root else d) + "/",
                exclude_patterns
            )
        ]

        for file in files:
            rel_file = f"{rel_root}/{file}" if rel_root else file
            if matches_exclude_patterns(rel_file, exclude_patterns):
                continue
            valid_files.append(rel_file)

    return sorted(valid_files)


def build_package():
    parser = argparse.ArgumentParser(description="Package MoziToolKit extension for Blender.")
    parser.add_argument("-o", "--output-dir", default="dist", help="Output directory for the package (default: dist)")
    parser.add_argument("--blender", default="", help="Path to Blender binary to use for official extension build")
    parser.add_argument("--split-platforms", action="store_true", help="Build separate packages per platform (via Blender)")
    parser.add_argument("--fallback-only", action="store_true", help="Force pure Python packaging instead of Blender CLI")
    args = parser.parse_args()

    project_dir = os.path.abspath(os.path.dirname(__file__))
    output_dir = os.path.abspath(os.path.join(project_dir, args.output_dir))
    os.makedirs(output_dir, exist_ok=True)

    ext_id, ext_version, exclude_patterns = parse_manifest(project_dir)

    blender_bin = args.blender or find_blender_binary()

    if blender_bin and not args.fallback_only:
        print(f"🚀 Using official Blender extension builder: {blender_bin}")
        cmd = [
            blender_bin,
            "--command",
            "extension",
            "build",
            "--source-dir",
            project_dir,
            "--output-dir",
            output_dir,
        ]
        if args.split_platforms:
            cmd.append("--split-platforms")

        try:
            res = subprocess.run(cmd, cwd=project_dir, check=True)
            if res.returncode == 0:
                print(f"\n✅ Official build complete in: {output_dir}")
                return
        except Exception as e:
            print(f"[Warning] Official Blender extension build encountered an error: {e}")
            print("Falling back to Python package generator...")

    # Fallback to pure Python package builder
    print(f"📦 Packaging extension '{ext_id}' v{ext_version} via Python fallback...")
    zip_filename = f"{ext_id}-{ext_version}.zip"
    output_zip_path = os.path.join(output_dir, zip_filename)

    files_to_pack = get_files_to_package_fallback(project_dir, exclude_patterns)

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
