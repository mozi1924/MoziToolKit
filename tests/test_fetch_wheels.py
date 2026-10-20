"""Tests for the CI wheel fetcher (release resolution and asset selection)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tools.fetch_wheels as fw


def _asset(name: str, created_at: str, asset_id: int, size: int = 1024) -> dict:
    return {
        "name": name,
        "created_at": created_at,
        "id": asset_id,
        "size": size,
        "browser_download_url": f"https://example.invalid/{name}",
    }


OLD_LINUX = _asset(
    "libmtk_py-0.1.0-cp311-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
    "2026-10-18T23:44:37Z",
    1,
)
NEW_LINUX = _asset(
    "libmtk_py-0.1.0-cp311-abi3-manylinux_2_28_x86_64.whl",
    "2026-10-19T05:51:52Z",
    2,
)
NEW_LINUX_DNA = _asset(
    "libmtk_blender_dna-0.1.0-cp311-abi3-manylinux_2_28_x86_64.whl",
    "2026-10-19T05:51:53Z",
    3,
)


class TestMatchesPlatform(unittest.TestCase):
    def test_all_supported_platforms(self):
        cases = {
            "libmtk_py-0.1.0-cp311-abi3-manylinux_2_28_x86_64.whl": "linux-x64",
            "libmtk_py-0.1.0-cp311-abi3-manylinux_2_28_aarch64.whl": "linux-arm64",
            "libmtk_py-0.1.0-cp311-abi3-win_amd64.whl": "windows-x64",
            "libmtk_py-0.1.0-cp311-abi3-win_arm64.whl": "windows-arm64",
            "libmtk_py-0.1.0-cp311-abi3-macosx_10_12_x86_64.whl": "macos-x64",
            "libmtk_py-0.1.0-cp311-abi3-macosx_11_0_arm64.whl": "macos-arm64",
        }
        for filename, platform_id in cases.items():
            with self.subTest(platform=platform_id):
                self.assertTrue(fw.matches_platform(filename, platform_id))
                for other in set(fw.SUPPORTED_PLATFORMS) - {platform_id}:
                    self.assertFalse(
                        fw.matches_platform(filename, other),
                        f"{filename} must not match {other}",
                    )

    def test_universal2_matches_both_macos_platforms(self):
        name = "libmtk_py-0.1.0-cp311-abi3-macosx_10_9_universal2.whl"
        self.assertTrue(fw.matches_platform(name, "macos-x64"))
        self.assertTrue(fw.matches_platform(name, "macos-arm64"))

    def test_non_wheel_is_ignored(self):
        self.assertFalse(fw.matches_platform("SHA256SUMS.txt", "linux-x64"))


class TestFetchWheels(unittest.TestCase):
    def _run(self, release_data, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(
            fw, "get_release_data", return_value=release_data
        ), mock.patch.object(fw, "download_file") as download:
            downloaded = fw.fetch_wheels(
                repo="owner/repo",
                target_platforms=["linux-x64"],
                out_dir=Path(tmp.name),
                **kwargs,
            )
        return downloaded, download

    def test_prefers_newest_matching_asset(self):
        downloaded, download = self._run(
            {"assets": [OLD_LINUX, NEW_LINUX, NEW_LINUX_DNA]},
            release="ci-latest",
        )
        self.assertEqual({p.name for p in downloaded}, {NEW_LINUX["name"], NEW_LINUX_DNA["name"]})
        self.assertEqual(download.call_count, 2)
        downloaded_urls = {call.args[0] for call in download.call_args_list}
        self.assertIn(NEW_LINUX["name"], " ".join(downloaded_urls))
        self.assertIn(NEW_LINUX_DNA["name"], " ".join(downloaded_urls))

    def test_latest_falls_back_to_ci_latest(self):
        calls = []

        def fake_get(repo, release_tag, token=None):
            calls.append(release_tag)
            if release_tag == "latest":
                raise RuntimeError("Release 'latest' not found in repo 'owner/repo'.")
            return {"assets": [NEW_LINUX, NEW_LINUX_DNA]}

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(fw, "get_release_data", side_effect=fake_get), mock.patch.object(
            fw, "download_file"
        ):
            downloaded = fw.fetch_wheels(
                repo="owner/repo",
                release="latest",
                target_platforms=["linux-x64"],
                out_dir=Path(tmp.name),
            )

        self.assertEqual(calls, ["latest", "ci-latest"])
        self.assertEqual({p.name for p in downloaded}, {NEW_LINUX["name"], NEW_LINUX_DNA["name"]})

    def test_no_fallback_propagates_error(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(
            fw, "get_release_data", side_effect=RuntimeError("not found")
        ):
            with self.assertRaises(RuntimeError):
                fw.fetch_wheels(
                    repo="owner/repo",
                    release="latest",
                    target_platforms=["linux-x64"],
                    out_dir=Path(tmp.name),
                    allow_prerelease_fallback=False,
                )

    def test_missing_platform_raises(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(
            fw, "get_release_data", return_value={"assets": [NEW_LINUX, NEW_LINUX_DNA]}
        ), mock.patch.object(fw, "download_file"):
            with self.assertRaises(RuntimeError) as ctx:
                fw.fetch_wheels(
                    repo="owner/repo",
                    release="ci-latest",
                    target_platforms=["linux-x64", "windows-x64"],
                    out_dir=Path(tmp.name),
                )
        self.assertIn("windows-x64", str(ctx.exception))

    def test_clean_removes_previous_wheels(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        stale = Path(tmp.name) / "libmtk_py-0.1.0-cp311-abi3-win_amd64.whl"
        stale.write_bytes(b"stale")
        stale_dna = Path(tmp.name) / "libmtk_blender_dna-0.1.0-cp311-abi3-win_amd64.whl"
        stale_dna.write_bytes(b"stale")

        with mock.patch.object(
            fw, "get_release_data", return_value={"assets": [NEW_LINUX, NEW_LINUX_DNA]}
        ), mock.patch.object(fw, "download_file"):
            fw.fetch_wheels(
                repo="owner/repo",
                release="ci-latest",
                target_platforms=["linux-x64"],
                out_dir=Path(tmp.name),
                clean=True,
            )

        self.assertFalse(stale.exists())
        self.assertFalse(stale_dna.exists())


if __name__ == "__main__":
    unittest.main()
