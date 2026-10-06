#!/usr/bin/env bash
#
# Fetch the `libmtk_py` abi3 wheel for MoziToolKit CI.
#
# Priority:
#   1. If a git ref is given, build libmozitoolkit from source at that ref.
#   2. Otherwise download the wheel published to the rolling `ci-latest` pre-release
#      of mozi1924/libmozitoolkit (fast GitHub-internal download).
#   3. Fallback: build libmozitoolkit `main` from source.
#
# Usage: fetch_libmtk_wheel.sh <output-dir> [git-ref]
set -euo pipefail

out_dir="${1:?usage: fetch_libmtk_wheel.sh <output-dir> [git-ref]}"
ref="${2:-}"

mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd)"

PYTHON="$(command -v python || command -v python3 || true)"
if [ -z "$PYTHON" ]; then
  echo "::error::python interpreter not found on PATH"
  exit 1
fi

build_from_source() {
  local checkout_ref="$1"
  local src
  src="$(mktemp -d)/libmozitoolkit"
  echo "Building libmtk_py from source (${checkout_ref:-main}) -> ${src}"
  if [ -n "$checkout_ref" ]; then
    git clone --depth 1 --branch "$checkout_ref" \
      https://github.com/mozi1924/libmozitoolkit "$src" || {
      git clone https://github.com/mozi1924/libmozitoolkit "$src"
      git -C "$src" checkout "$checkout_ref"
    }
  else
    git clone --depth 1 https://github.com/mozi1924/libmozitoolkit "$src"
  fi
  "$PYTHON" -m pip install --upgrade maturin >/dev/null
  (cd "$src" && "$PYTHON" -m maturin build --release --out "$out_dir" -m bindings/mtk-py/Cargo.toml)
}

if [ -n "$ref" ]; then
  build_from_source "$ref"
  exit 0
fi

api="https://api.github.com/repos/mozi1924/libmozitoolkit/releases/tags/ci-latest"
wheel_url="$(curl -sL "$api" | "$PYTHON" -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
assets = data.get("assets", []) if isinstance(data, dict) else []
print(next((a["browser_download_url"] for a in assets if a["name"].endswith(".whl")), ""))
' 2>/dev/null || true)"

if [ -n "$wheel_url" ]; then
  asset_name="$(basename "${wheel_url%%\?*}")"
  if curl -fL -o "$out_dir/$asset_name" "$wheel_url"; then
    echo "Using published ci-latest wheel: $asset_name"
    exit 0
  fi
fi

echo "::warning::ci-latest wheel unavailable; building libmtk_py from source (main)"
build_from_source ""
