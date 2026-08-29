#!/usr/bin/env python3
"""
MoziToolKit Multi-Platform Build & Dependency Coordinator Script.

Coordinated features:
1. Locates Blender binary and queries its embedded Python environment.
2. Uses Blender's built-in Python and pip to download cross-platform wheels for:
   - Pillow (PIL)
   - websockets
   Targeting:
   - Linux AMD64 (manylinux x86_64)
   - Windows AMD64 (win_amd64)
   - Windows ARM64 (win_arm64)
   - macOS ARM64 (Apple Silicon)
3. Synchronizes `blender_manifest.toml` wheels list.
4. Validates manifest via `blender --command extension validate`.
5. Builds per-platform extension packages via `blender --command extension build --split-platforms`
   with pure-Python platform-splitting fallback.
"""

import argparse
import fnmatch
import glob
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

try:
    import tomllib
except ImportError:
    tomllib = None


# Default dependency targets aligned for Blender 4.2+ / 5.x Extensions
DEFAULT_DEPENDENCY_SPECS = [
    "pillow==12.3.0",
    "websockets==15.0.1",
]

TARGET_PLATFORMS = [
    {
        "id": "macos-arm64",
        "label": "macOS ARM64 (Apple Silicon)",
        "pip_platforms": ["macosx_11_0_arm64", "macosx_12_0_arm64"],
    },
    {
        "id": "windows-x64",
        "label": "Windows AMD64 (x86_64)",
        "pip_platforms": ["win_amd64"],
    },
    {
        "id": "windows-arm64",
        "label": "Windows ARM64",
        "pip_platforms": ["win_arm64"],
    },
    {
        "id": "linux-x64",
        "label": "Linux AMD64 (x86_64)",
        "pip_platforms": ["manylinux_2_28_x86_64", "manylinux2014_x86_64"],
    },
]


def find_blender_binary() -> str | None:
    """Attempt to locate the Blender executable across standard platform locations."""
    # 1. Environment variables
    for env_var in ["BLENDER_BIN", "BLENDER_PATH", "BLENDER_EXECUTABLE"]:
        env_bin = os.environ.get(env_var)
        if env_bin and os.path.isfile(env_bin) and os.access(env_bin, os.X_OK):
            return env_bin

    # 2. In PATH
    which_bin = shutil.which("blender")
    if which_bin:
        return which_bin

    # 3. macOS standard paths
    mac_paths = [
        "/Applications/Blender.app/Contents/MacOS/blender",
        "/Applications/Blender 5.2.app/Contents/MacOS/blender",
        "/Applications/Blender 5.1.app/Contents/MacOS/blender",
        "/Applications/Blender 5.0.app/Contents/MacOS/blender",
        "/Applications/Blender 4.5.app/Contents/MacOS/blender",
        "/Applications/Blender 4.4.app/Contents/MacOS/blender",
        "/Applications/Blender 4.3.app/Contents/MacOS/blender",
        "/Applications/Blender 4.2.app/Contents/MacOS/blender",
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
        matches = glob.glob(win_pattern)
        if matches:
            return sorted(matches)[-1]

    return None


def get_blender_python_info(blender_bin: str) -> tuple[str | None, str, str]:
    """
    Query Blender to get its embedded Python executable path and version tags.
    Returns (python_bin, py_version_tag e.g. '313', py_ver_dotted e.g. '3.13').
    """
    expr = (
        "import sys; "
        "print('__PY_INFO__:' + f'{sys.version_info.major}.{sys.version_info.minor}:' + sys.executable)"
    )
    cmd = [blender_bin, "--background", "--python-expr", expr]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        for line in res.stdout.splitlines():
            if line.startswith("__PY_INFO__:"):
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    py_ver_dotted = parts[1].strip()
                    py_bin = parts[2].strip()
                    py_version_tag = py_ver_dotted.replace(".", "")
                    return py_bin, py_version_tag, py_ver_dotted
    except Exception as e:
        print(f"[Warning] Could not query Blender Python info: {e}")

    # Fallback to current host python
    host_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    return sys.executable, host_ver.replace(".", ""), host_ver


def parse_manifest(project_dir: str):
    """Extract extension metadata, supported platforms, wheels list, and build exclusions."""
    manifest_path = os.path.join(project_dir, "blender_manifest.toml")
    ext_id = None
    ext_version = None
    platforms = []
    wheels = []
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
        ".venv/",
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
                    platforms = data.get("platforms", [])
                    wheels = data.get("wheels", [])
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

    # Fallback to __init__.py if manifest is missing
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
    platforms = platforms or ["windows-x64", "windows-arm64", "macos-arm64", "linux-x64"]
    return ext_id, ext_version, platforms, wheels, exclude_patterns


def download_dependencies(
    blender_py: str,
    py_version_tag: str,
    wheels_dir: Path,
    clean_first: bool = False,
    specs: list[str] | None = None,
) -> list[Path]:
    """
    Download cross-platform wheels for specified dependencies using Blender's Python and pip.
    Returns list of downloaded wheel paths.
    """
    specs = specs or DEFAULT_DEPENDENCY_SPECS
    wheels_dir.mkdir(parents=True, exist_ok=True)

    if clean_first:
        print(f"🧹 Cleaning existing wheels in: {wheels_dir}")
        for whl in wheels_dir.glob("*.whl"):
            whl.unlink()

    print(f"\n📦 Coordinating with Blender Python ({blender_py}) to download dependencies:")
    print(f"   Target Python ABI: cp{py_version_tag} / Version Tag: {py_version_tag}")
    print(f"   Packages: {', '.join(specs)}\n")

    downloaded_files = set(wheels_dir.glob("*.whl"))

    for target in TARGET_PLATFORMS:
        plat_id = target["id"]
        label = target["label"]
        print(f"  ⬇️  Downloading wheels for platform [{plat_id}] ({label})...")

        for pkg in specs:
            success = False
            for plat_tag in target["pip_platforms"]:
                cmd = [
                    blender_py,
                    "-m",
                    "pip",
                    "download",
                    pkg,
                    "--only-binary=:all:",
                    "--platform",
                    plat_tag,
                    "--python-version",
                    py_version_tag,
                    "--implementation",
                    "cp",
                    "--abi",
                    f"cp{py_version_tag}",
                    "--no-deps",
                    "-d",
                    str(wheels_dir),
                ]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    success = True
                    break

            # Fallback to pure Python wheel if platform binary not available (e.g. websockets for win_arm64)
            if not success:
                cmd_any = [
                    blender_py,
                    "-m",
                    "pip",
                    "download",
                    pkg,
                    "--no-deps",
                    "-d",
                    str(wheels_dir),
                ]
                res_any = subprocess.run(cmd_any, capture_output=True, text=True)
                if res_any.returncode == 0:
                    success = True

            if success:
                print(f"     ✓ {pkg} ready for {plat_id}")
            else:
                print(f"     ⚠️ Failed downloading {pkg} for {plat_id}")

    all_wheels = sorted(wheels_dir.glob("*.whl"))
    new_wheels = set(all_wheels) - downloaded_files
    if new_wheels:
        print(f"\n✨ Added {len(new_wheels)} new wheel(s) to {wheels_dir}")
    print(f"📁 Current wheels repository contains {len(all_wheels)} file(s).\n")
    return all_wheels


def sync_manifest_wheels(project_dir: Path, wheels_dir: Path) -> list[str]:
    """
    Ensure blender_manifest.toml has an up-to-date `wheels = [...]` array matching all wheels in `wheels/`.
    """
    manifest_path = project_dir / "blender_manifest.toml"
    if not manifest_path.exists():
        return []

    relative_wheels = sorted([f"wheels/{whl.name}" for whl in wheels_dir.glob("*.whl")])
    with open(manifest_path, "r", encoding="utf-8") as f:
        content = f.read()

    wheels_toml_block = "wheels = [\n" + "".join(f'  "{w}",\n' for w in relative_wheels) + "]"

    if "wheels = [" in content:
        new_content = re.sub(r"wheels\s*=\s*\[[^\]]*\]", wheels_toml_block, content, flags=re.DOTALL)
    else:
        new_content = content + f"\n# Bundled Python Wheels\n{wheels_toml_block}\n"

    if new_content != content:
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"📝 Synchronized {len(relative_wheels)} wheels in {manifest_path.name}")

    return relative_wheels


def matches_exclude_patterns(rel_path: str, patterns: list[str]) -> bool:
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


def get_files_to_package_fallback(project_dir: str, exclude_patterns: list[str] | None = None) -> list[str]:
    """Fallback directory walk strictly adhering to paths_exclude_pattern."""
    exclude_patterns = exclude_patterns or []
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


def is_wheel_for_platform(whl_name: str, platform_id: str) -> bool:
    """Determine if a wheel file belongs to a given platform id."""
    name = whl_name.lower()
    if "py3-none-any" in name:
        return True

    if platform_id == "macos-arm64":
        return "macosx" in name and "arm64" in name
    elif platform_id == "macos-x64":
        return "macosx" in name and ("x86_64" in name or "universal2" in name)
    elif platform_id == "windows-x64":
        return "win_amd64" in name
    elif platform_id == "windows-arm64":
        return "win_arm64" in name
    elif platform_id == "linux-x64":
        return "manylinux" in name and "x86_64" in name
    elif platform_id == "linux-arm64":
        return "manylinux" in name and ("aarch64" in name or "arm64" in name)
    return False


def build_fallback_split_packages(project_dir: str, output_dir: str, ext_id: str, ext_version: str, platforms: list[str], exclude_patterns: list[str]):
    """Pure Python fallback for splitting packages per platform if Blender CLI is not present."""
    base_files = get_files_to_package_fallback(project_dir, exclude_patterns)

    for plat in platforms:
        plat_suffix = plat.replace("-", "_")
        zip_filename = f"{ext_id}-{ext_version}-{plat_suffix}.zip"
        zip_path = os.path.join(output_dir, zip_filename)

        plat_files = []
        for rel_file in base_files:
            if rel_file.startswith("wheels/"):
                whl_name = os.path.basename(rel_file)
                if not is_wheel_for_platform(whl_name, plat):
                    continue
            plat_files.append(rel_file)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for rel_file in plat_files:
                abs_file = os.path.join(project_dir, rel_file)
                zipf.write(abs_file, rel_file)

        size_kb = os.path.getsize(zip_path) / 1024
        print(f"  ✓ Created fallback package: {zip_filename} ({size_kb:.2f} KB, {len(plat_files)} files)")


def summarize_output(output_dir: str):
    """Print detailed summary of all generated packages in output_dir."""
    zips = sorted(glob.glob(os.path.join(output_dir, "*.zip")))
    if not zips:
        print("⚠️ No output packages found.")
        return

    print("\n" + "=" * 78)
    print(" 🎉 BUILD & PACKAGING COMPLETE - ARTIFACTS SUMMARY")
    print("=" * 78)
    for zpath in zips:
        fname = os.path.basename(zpath)
        size_mb = os.path.getsize(zpath) / (1024 * 1024)
        print(f"\n📦 File: {fname} ({size_mb:.2f} MB)")
        try:
            with zipfile.ZipFile(zpath, "r") as zf:
                bundled_wheels = [n for n in zf.namelist() if n.startswith("wheels/") and n.endswith(".whl")]
                print(f"   Bundled Wheels ({len(bundled_wheels)}):")
                for w in bundled_wheels:
                    print(f"     - {os.path.basename(w)}")
        except Exception:
            pass
    print("\n" + "=" * 78 + "\n")


def main():
    parser = argparse.ArgumentParser(description="MoziToolKit Multi-Platform Build & Dependency Coordinator.")
    parser.add_argument("-o", "--output-dir", default="dist", help="Output directory for build artifacts (default: dist)")
    parser.add_argument("--blender", default="", help="Path to custom Blender executable")
    parser.add_argument("--download-deps", action="store_true", default=True, help="Download / verify cross-platform dependencies via Blender's Python (default: True)")
    parser.add_argument("--no-download-deps", dest="download_deps", action="store_false", help="Skip downloading dependencies")
    parser.add_argument("--clean-wheels", action="store_true", help="Clean wheels directory before downloading")
    parser.add_argument("--split-platforms", action="store_true", default=True, help="Build separate packages per platform (default: True)")
    parser.add_argument("--universal", action="store_true", help="Also build universal package containing all wheels")
    parser.add_argument("--validate-only", action="store_true", help="Validate manifest only without building")
    parser.add_argument("--fallback-only", action="store_true", help="Force pure Python packaging without Blender CLI")
    args = parser.parse_args()

    project_dir = Path(__file__).parent.resolve()
    wheels_dir = project_dir / "wheels"
    output_dir = Path(project_dir / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    ext_id, ext_version, platforms, _, exclude_patterns = parse_manifest(str(project_dir))
    blender_bin = args.blender or find_blender_binary()

    print("=" * 78)
    print(f" 🚀 MoziToolKit Build Coordinator: {ext_id} v{ext_version}")
    print("=" * 78)

    if blender_bin:
        print(f" Blender Binary: {blender_bin}")
        blender_py, py_version_tag, py_ver_dotted = get_blender_python_info(blender_bin)
        print(f" Embedded Python: {blender_py} (v{py_ver_dotted} / cp{py_version_tag})")
    else:
        print("⚠️ Blender executable not found in PATH or standard locations.")
        blender_py = sys.executable
        py_version_tag = f"{sys.version_info.major}{sys.version_info.minor}"
        py_ver_dotted = f"{sys.version_info.major}.{sys.version_info.minor}"
        print(f" Host Python: {blender_py} (v{py_ver_dotted} / cp{py_version_tag})")

    # Step 1: Download / Synchronize Dependencies
    if args.download_deps:
        download_dependencies(
            blender_py=blender_py,
            py_version_tag=py_version_tag,
            wheels_dir=wheels_dir,
            clean_first=args.clean_wheels,
        )

    # Step 2: Synchronize Manifest wheels list
    sync_manifest_wheels(project_dir, wheels_dir)

    # Step 3: Validate Extension
    if blender_bin and not args.fallback_only:
        print("🔍 Validating Blender Extension manifest...")
        val_cmd = [blender_bin, "--command", "extension", "validate", "."]
        val_res = subprocess.run(val_cmd, cwd=str(project_dir))
        if val_res.returncode != 0:
            print("❌ Extension validation failed!")
            sys.exit(val_res.returncode)
        print("✅ Extension manifest is valid.\n")

    if args.validate_only:
        print("🏁 Validation completed successfully.")
        return

    # Step 4: Build Split-Platform Packages
    if blender_bin and not args.fallback_only:
        print(f"🔨 Building extension packages via Blender official CLI...")
        build_cmd = [
            blender_bin,
            "--command",
            "extension",
            "build",
            "--source-dir",
            str(project_dir),
            "--output-dir",
            str(output_dir),
        ]
        if args.split_platforms:
            build_cmd.append("--split-platforms")

        res = subprocess.run(build_cmd, cwd=str(project_dir))
        if res.returncode != 0:
            print("⚠️ Official Blender build failed, switching to Python fallback...")
            build_fallback_split_packages(str(project_dir), str(output_dir), ext_id, ext_version, platforms, exclude_patterns)
        elif args.universal:
            # Build universal package as well
            print("🔨 Building universal package...")
            uni_cmd = [
                blender_bin,
                "--command",
                "extension",
                "build",
                "--source-dir",
                str(project_dir),
                "--output-dir",
                str(output_dir),
            ]
            subprocess.run(uni_cmd, cwd=str(project_dir))
    else:
        print(f"📦 Packaging extension '{ext_id}' v{ext_version} via Python fallback...")
        build_fallback_split_packages(str(project_dir), str(output_dir), ext_id, ext_version, platforms, exclude_patterns)

    # Step 5: Summary
    summarize_output(str(output_dir))


if __name__ == "__main__":
    main()
