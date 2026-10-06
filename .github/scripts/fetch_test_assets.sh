#!/usr/bin/env bash
#
# Download the temporary real Minecraft assets used by the MoziToolKit real-pack tests
# and export the resolver environment variables via $GITHUB_ENV.
#
# Non-fatal by design: if the mirror is unavailable, asset-dependent tests skip.
set -euo pipefail

base="${MTK_CI_ASSETS_BASE:?MTK_CI_ASSETS_BASE must be set}"
work="${RUNNER_TEMP:-/tmp}/mtk-assets"
mkdir -p "$work"

if curl -fL --retry 3 -o "$work/mc.jar" "$base/26.2-Fabric.jar"; then
  rm -rf "$work/mc"
  mkdir -p "$work/mc"
  unzip -q "$work/mc.jar" -d "$work/mc"
  {
    echo "MTK_TEST_ASSETS=$work/mc"
    echo "MC_DIR=$work/mc"
    echo "MC_ASSETS_DIR=$work/mc"
    echo "MTK_TEST_JAR=$work/mc.jar"
  } >> "${GITHUB_ENV:?GITHUB_ENV must be set}"
else
  echo "::warning::Minecraft jar unavailable; real-pack tests will fall back to vendored fixtures."
fi

if curl -fL --retry 3 -o "$work/SPBR-21.zip" "$base/SPBR-21.zip"; then
  echo "MTK_TEST_RESOURCE_PACK=$work/SPBR-21.zip" >> "${GITHUB_ENV:?GITHUB_ENV must be set}"
else
  echo "::warning::External resource pack unavailable; companion-pack tests will be skipped."
fi

if curl -fL --retry 3 -o "$work/mtk-save-world.tar.gz" "$base/mtk-save-world.tar.gz"; then
  rm -rf "$work/mtk-save-world"
  tar -xzf "$work/mtk-save-world.tar.gz" -C "$work"
  echo "MTK_TEST_SAVE=$work/mtk-save-world" >> "${GITHUB_ENV:?GITHUB_ENV must be set}"
else
  echo "::warning::Sample save world unavailable; save-bridge tests will be skipped."
fi
