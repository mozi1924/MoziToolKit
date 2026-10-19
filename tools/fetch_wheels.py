#!/usr/bin/env python3
"""
Wheel Fetcher for MoziToolKit.

Downloads precompiled libmtk_py abi3 wheels from libmozitoolkit GitHub Releases.
Supports:
  - Downloading a specific platform wheel (e.g. for CI testing: linux-x64)
  - Downloading all 6 supported platform wheels (for packaging: --all)
  - Fetching from the latest stable release, rolling 'ci-latest', or a specific tag
  - Falling back to 'ci-latest' when 'latest' has no stable release yet
    (opt out with --no-fallback)
  - Picking the newest matching wheel when a release still carries stale
    duplicates from earlier builds
"""

import argparse
import json
import os
from pathlib import Path
import platform
import sys
import urllib.error
import urllib.request

# The status output uses emoji; Windows pipes default to the legacy ANSI code
# page and would raise UnicodeEncodeError when CI captures stdout.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SUPPORTED_PLATFORMS = [
    "linux-x64",
    "linux-arm64",
    "windows-x64",
    "windows-arm64",
    "macos-x64",
    "macos-arm64",
]


def detect_current_platform() -> str:
    """Detect platform ID corresponding to the current host machine."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        return "macos-arm64" if machine in ("arm64", "aarch64") else "macos-x64"
    elif system == "linux":
        return "linux-arm64" if machine in ("arm64", "aarch64") else "linux-x64"
    elif system in ("windows", "win32"):
        return "windows-arm64" if machine in ("arm64", "aarch64") else "windows-x64"
    else:
        raise RuntimeError(f"Unsupported operating system: {system} ({machine})")


def matches_platform(filename: str, platform_id: str) -> bool:
    """Check if a wheel filename matches the requested platform ID."""
    name = filename.lower()
    if not name.endswith(".whl"):
        return False

    if platform_id == "linux-x64":
        return "manylinux" in name and "x86_64" in name
    elif platform_id == "linux-arm64":
        return "manylinux" in name and ("aarch64" in name or "arm64" in name)
    elif platform_id == "windows-x64":
        return "win_amd64" in name
    elif platform_id == "windows-arm64":
        return "win_arm64" in name
    elif platform_id == "macos-x64":
        return "macosx" in name and ("x86_64" in name or "universal2" in name)
    elif platform_id == "macos-arm64":
        return "macosx" in name and ("arm64" in name or "universal2" in name)
    return False


def get_release_data(repo: str, release_tag: str, token: str | None = None) -> dict:
    """Fetch GitHub Release metadata via GitHub REST API."""
    if release_tag == "latest":
        url = f"https://api.github.com/repos/{repo}/releases/latest"
    else:
        url = f"https://api.github.com/repos/{repo}/releases/tags/{release_tag}"

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "MoziToolKit-Wheel-Fetcher",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(f"Release '{release_tag}' not found in repo '{repo}'.") from e
        elif e.code in (401, 403):
            raise RuntimeError(
                f"GitHub API authorization or rate limit error ({e.code}): {e.reason}. "
                "Set GITHUB_TOKEN or GH_TOKEN to authenticate."
            ) from e
        else:
            raise RuntimeError(f"GitHub API error ({e.code}): {e.reason}") from e
    except Exception as e:
        raise RuntimeError(f"Failed to connect to GitHub API: {e}") from e


def asset_recency_key(asset: dict) -> tuple[str, int]:
    """Sort key that prefers the most recently uploaded release asset.

    `created_at` is an ISO-8601 timestamp, so lexical ordering is chronological.
    `id` is used as a tie-breaker for assets uploaded within the same second.
    """
    try:
        asset_id = int(asset.get("id") or 0)
    except (TypeError, ValueError):
        asset_id = 0
    return (str(asset.get("created_at") or ""), asset_id)


def resolve_release_data(
    repo: str,
    release: str,
    token: str | None = None,
    allow_prerelease_fallback: bool = True,
) -> tuple[str, dict]:
    """Resolve release metadata, optionally falling back from `latest` to `ci-latest`.

    Returns the release tag that was actually used together with its metadata.
    The fallback exists so upstream CI is not blocked before the first stable
    libmozitoolkit release has been tagged; pass `allow_prerelease_fallback=False`
    (CLI: `--no-fallback`) for a strict official build.
    """
    try:
        return release, get_release_data(repo, release, token)
    except RuntimeError as exc:
        if release == "latest" and allow_prerelease_fallback:
            print(
                f"⚠️  No stable release resolved ({exc}); "
                "falling back to the rolling 'ci-latest' release."
            )
            return "ci-latest", get_release_data(repo, "ci-latest", token)
        raise


def download_file(url: str, dest_path: Path, token: str | None = None) -> None:
    """Download a file with streaming and progress reporting."""
    headers = {
        "User-Agent": "MoziToolKit-Wheel-Fetcher",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_suffix(".tmp")

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as response, open(temp_path, "wb") as out_file:
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0
            chunk_size = 1024 * 64

            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                out_file.write(chunk)
                downloaded += len(chunk)

        temp_path.replace(dest_path)
        size_mb = dest_path.stat().st_size / (1024 * 1024)
        print(f"  ✓ {dest_path.name} ({size_mb:.2f} MB)")
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise RuntimeError(f"Failed to download {url}: {e}") from e


def fetch_wheels(
    repo: str = "mozi1924/libmozitoolkit",
    release: str = "ci-latest",
    target_platforms: list[str] | None = None,
    out_dir: Path = Path("wheels"),
    clean: bool = False,
    token: str | None = None,
    allow_prerelease_fallback: bool = True,
) -> list[Path]:
    """Fetch matching wheels from GitHub Releases."""
    token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    target_platforms = target_platforms or [detect_current_platform()]

    print(f"🔍 Querying {repo} release '{release}' for platform(s): {', '.join(target_platforms)}...")
    release, rel_data = resolve_release_data(
        repo,
        release,
        token,
        allow_prerelease_fallback=allow_prerelease_fallback,
    )

    assets = rel_data.get("assets", [])
    if not assets:
        raise RuntimeError(f"No release assets found in {repo} release '{release}'.")

    whl_assets = [a for a in assets if a.get("name", "").endswith(".whl")]
    print(f"📦 Release '{release}' contains {len(whl_assets)} wheel asset(s).")

    out_dir.mkdir(parents=True, exist_ok=True)
    if clean:
        print(f"🧹 Cleaning existing wheels in {out_dir}...")
        for existing in out_dir.glob("libmtk_py*.whl"):
            existing.unlink()

    downloaded: list[Path] = []
    missing_platforms: list[str] = []

    for platform_id in target_platforms:
        matched = [a for a in whl_assets if matches_platform(a["name"], platform_id)]
        if not matched:
            missing_platforms.append(platform_id)
            continue

        # Releases are append-only in practice: stale wheels from earlier runs
        # under a different manylinux tag are not overwritten by `--clobber`.
        # Always take the newest matching asset instead of relying on API order.
        matched.sort(key=asset_recency_key, reverse=True)
        target_asset = matched[0]
        if len(matched) > 1:
            print(
                f"  ℹ️  [{platform_id}] {len(matched)} candidate wheels in release; "
                f"using newest: {target_asset['name']}"
            )

        dest = out_dir / target_asset["name"]

        # Skip download if already exists with matching size
        if dest.exists() and dest.stat().st_size == target_asset.get("size", -1):
            print(f"  • {dest.name} already cached ({dest.stat().st_size / 1024 / 1024:.2f} MB)")
            downloaded.append(dest)
            continue

        print(f"  ⬇️ Downloading for [{platform_id}]: {target_asset['name']}...")
        download_file(target_asset["browser_download_url"], dest, token)
        downloaded.append(dest)

    if missing_platforms:
        available_names = [a["name"] for a in whl_assets]
        raise RuntimeError(
            f"Release '{release}' is missing wheels for platform(s): {', '.join(missing_platforms)}. "
            f"Available assets: {available_names}"
        )

    print(f"✅ Successfully resolved {len(downloaded)} wheel(s) into {out_dir}.\n")
    return downloaded


def main():
    parser = argparse.ArgumentParser(description="Fetch precompiled libmtk_py wheels from libmozitoolkit releases.")
    parser.add_argument(
        "--repo",
        default="mozi1924/libmozitoolkit",
        help="GitHub repository in owner/repo format (default: mozi1924/libmozitoolkit)",
    )
    parser.add_argument(
        "--release",
        default="ci-latest",
        help="Release tag or shortcut: 'latest' (stable), 'ci-latest' (rolling), or tag name (default: ci-latest)",
    )
    parser.add_argument(
        "--platform",
        default=None,
        help=f"Target platform ({', '.join(SUPPORTED_PLATFORMS)} or 'current')",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Download wheels for all 6 supported platforms",
    )
    parser.add_argument(
        "--out",
        "-o",
        default="wheels",
        help="Output directory (default: wheels)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean destination directory before downloading",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="GitHub personal access token (optional, falls back to GITHUB_TOKEN or GH_TOKEN env)",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help=(
            "Fail when '--release latest' has no stable release instead of "
            "falling back to the rolling 'ci-latest' release"
        ),
    )

    args = parser.parse_args()

    if args.all:
        targets = list(SUPPORTED_PLATFORMS)
    elif args.platform:
        if args.platform == "current":
            targets = [detect_current_platform()]
        elif args.platform in SUPPORTED_PLATFORMS:
            targets = [args.platform]
        else:
            print(f"❌ Invalid platform '{args.platform}'. Supported: {', '.join(SUPPORTED_PLATFORMS)}")
            sys.exit(1)
    else:
        targets = [detect_current_platform()]

    try:
        fetch_wheels(
            repo=args.repo,
            release=args.release,
            target_platforms=targets,
            out_dir=Path(args.out),
            clean=args.clean,
            token=args.token,
            allow_prerelease_fallback=not args.no_fallback,
        )
    except Exception as e:
        print(f"❌ Wheel fetch failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
