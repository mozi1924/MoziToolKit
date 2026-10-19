#!/usr/bin/env bash
#
# Fetch the `libmtk_py` abi3 wheel for MoziToolKit CI.
# Usage: fetch_libmtk_wheel.sh <output-dir> [git-ref-or-tag] [platform-id]
set -euo pipefail

out_dir="${1:?usage: fetch_libmtk_wheel.sh <output-dir> [git-ref-or-tag] [platform-id]}"
ref="${2:-ci-latest}"
platform_id="${3:-linux-x64}"

mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

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

# Try fetching via fetch_wheels.py first
if "$PYTHON" "$ROOT_DIR/tools/fetch_wheels.py" --release "${ref:-ci-latest}" --platform "$platform_id" --out "$out_dir"; then
  echo "Successfully resolved $platform_id wheel from release '${ref:-ci-latest}'"
  exit 0
fi

echo "::warning::Could not fetch precompiled wheel from release; attempting fallback build from source"
build_from_source "${ref:-main}"
