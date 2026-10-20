"""
Tests for content-based pack/JAR classification (``utils.pack_detect``).

Synthetic archives only: real Minecraft / mod / pack binaries are never committed. A single
optional test exercises the workspace vanilla client JAR when ``tests/_assets.py`` can find it.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from utils.pack_detect import (
    ALL_KINDS,
    KIND_DATA_PACK,
    KIND_MOD,
    KIND_MODPACK,
    KIND_RESOURCE_PACK,
    KIND_UNKNOWN,
    KIND_VANILLA_CLIENT,
    KIND_VANILLA_SERVER,
    TYPE_SOURCE_AUTO,
    TYPE_SOURCE_MANUAL,
    detect_pack_kind,
    invalidate_pack_probe,
    pack_probe_cache_info,
    peek_cached_probe,
    resolve_pack_type,
)

from _assets import fabric_jar

PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
EMPTY_JAR = b"PK\x05\x06" + b"\x00" * 18


def _write_zip(path: Path, entries) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return path


def _resource_pack_files() -> list:
    return [
        ("pack.mcmeta", json.dumps({"pack": {"pack_format": 88, "description": "Test Pack"}})),
        ("pack.png", PNG_HEADER),
        ("assets/minecraft/textures/block/stone.png", PNG_HEADER),
        ("assets/minecraft/models/block/stone.json", "{}"),
        ("assets/minecraft/lang/en_us.json", "{}"),
    ]


def _mod_files() -> list:
    return _resource_pack_files() + [
        ("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": "coolmod", "name": "Cool Mod", "version": "1.0.0"})),
        ("coolmod.mixins.json", "{}"),
        ("com/example/coolmod/CoolMod.class", b"\xca\xfe\xba\xbe"),
        ("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n"),
        ("META-INF/jars/Library-1.0.jar", EMPTY_JAR),
    ]


class PackDetectTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        invalidate_pack_probe()

    def tearDown(self) -> None:
        invalidate_pack_probe()
        self._tmp.cleanup()

    def make(self, name: str, entries) -> Path:
        return _write_zip(self.root / name, entries)

    def assertKind(self, probe, kind: str) -> None:
        self.assertEqual(probe.kind, kind, f"evidence={probe.evidence} details={probe.details}")
        self.assertIsNone(probe.error)


class TestArchiveClassification(PackDetectTestBase):
    def test_resource_pack_zip(self) -> None:
        probe = detect_pack_kind(self.make("pack.zip", _resource_pack_files()))
        self.assertKind(probe, KIND_RESOURCE_PACK)
        self.assertEqual(probe.suggested_pack_type, "RESOURCE_PACK")
        self.assertEqual(probe.details.get("pack_format"), 88)

    def test_resource_pack_shipped_as_jar(self) -> None:
        """CTM/PBR packs are routinely distributed with a .jar extension."""
        probe = detect_pack_kind(self.make("Connected Glass.jar", _resource_pack_files()))
        self.assertKind(probe, KIND_RESOURCE_PACK)
        self.assertEqual(probe.suggested_pack_type, "RESOURCE_PACK")

    def test_resource_pack_named_like_a_mod(self) -> None:
        """Filename heuristics used to flag anything containing 'mod' as a mod JAR."""
        probe = detect_pack_kind(self.make("Modern Glass mod.jar", _resource_pack_files()))
        self.assertKind(probe, KIND_RESOURCE_PACK)

    def test_fabric_mod_with_embedded_pack_mcmeta(self) -> None:
        probe = detect_pack_kind(self.make("coolmod.jar", _mod_files()))
        self.assertKind(probe, KIND_MOD)
        self.assertEqual(probe.suggested_pack_type, "MOD_JAR")
        self.assertEqual(probe.details.get("mod_id"), "coolmod")
        self.assertEqual(probe.details.get("mod_name"), "Cool Mod")

    def test_forge_universal_jar_prefers_mod_markers(self) -> None:
        """A Forge universal JAR carries both mods.toml and pack.mcmeta + assets/."""
        path = self.make(
            "forge-universal.jar",
            [
                ("META-INF/mods.toml", 'modLoader="javafml"\n'),
                ("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nFMLModType: MOD\n"),
                ("pack.mcmeta", json.dumps({"pack": {"pack_format": 15}})),
                ("assets/minecraft/textures/block/stone.png", PNG_HEADER),
                ("com/example/mod/Mod.class", b"\xca\xfe\xba\xbe"),
            ],
        )
        probe = detect_pack_kind(path)
        self.assertKind(probe, KIND_MOD)
        self.assertEqual(probe.suggested_pack_type, "MOD_JAR")

    def test_neoforge_mod(self) -> None:
        probe = detect_pack_kind(
            self.make(
                "neomod.jar",
                [
                    ("META-INF/neoforge.mods.toml", 'modLoader="javafml"\n'),
                    ("assets/examplemod/lang/en_us.json", "{}"),
                ],
            )
        )
        self.assertKind(probe, KIND_MOD)

    def test_quilt_mod(self) -> None:
        probe = detect_pack_kind(self.make("quilt.jar", [("quilt.mod.json", json.dumps({"quilt_loader": {}}))]))
        self.assertKind(probe, KIND_MOD)

    def test_vanilla_client_with_nested_datapack_metadata(self) -> None:
        """
        Real vanilla client JARs contain ``data/minecraft/datapacks/*/pack.mcmeta`` and a root
        ``pack.png``. Only exact root-level matching may classify them as vanilla.
        """
        path = self.make(
            "26.2-Fabric.jar",
            [
                ("version.json", json.dumps({"id": "26.2", "world_version": 4903})),
                ("net/minecraft/client/main/Main.class", b"\xca\xfe\xba\xbe"),
                ("net/minecraft/server/Main.class", b"\xca\xfe\xba\xbe"),
                ("assets/.mcassetsroot", ""),
                ("data/.mcassetsroot", ""),
                ("META-INF/MOJANGCS.RSA", b"sig"),
                ("META-INF/MOJANGCS.SF", b"sig"),
                ("pack.png", PNG_HEADER),
                ("data/minecraft/datapacks/experiments/pack.mcmeta", "{}"),
                ("assets/minecraft/textures/block/stone.png", PNG_HEADER),
            ],
        )
        probe = detect_pack_kind(path)
        self.assertKind(probe, KIND_VANILLA_CLIENT)
        self.assertEqual(probe.suggested_pack_type, "VANILLA")
        self.assertEqual(probe.details.get("mc_version"), "26.2")

    def test_vanilla_server_bundler(self) -> None:
        probe = detect_pack_kind(
            self.make(
                "server.jar",
                [
                    ("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nMain-Class: net.minecraft.bundler.Main\n"),
                    ("META-INF/versions.list", "abc\t26.2\tserver-26.2.jar\n"),
                    ("META-INF/libraries.list", "def\tlib\tlib.jar\n"),
                    ("META-INF/libraries/com/x/lib.jar", EMPTY_JAR),
                ],
            )
        )
        self.assertKind(probe, KIND_VANILLA_SERVER)
        self.assertEqual(probe.suggested_pack_type, "VANILLA")

    def test_data_pack_is_recognized_but_not_suggested(self) -> None:
        probe = detect_pack_kind(
            self.make(
                "datapack.zip",
                [
                    ("pack.mcmeta", json.dumps({"pack": {"pack_format": 107}})),
                    ("data/minecraft/recipe/example.json", "{}"),
                ],
            )
        )
        self.assertKind(probe, KIND_DATA_PACK)
        self.assertIsNone(probe.suggested_pack_type)
        self.assertFalse(probe.is_texture_source)

    def test_modpack_is_recognized_but_not_suggested(self) -> None:
        probe = detect_pack_kind(
            self.make(
                "modpack.zip",
                [
                    ("manifest.json", json.dumps({"name": "Pack", "files": []})),
                    ("overrides/mods/example.jar", EMPTY_JAR),
                ],
            )
        )
        self.assertKind(probe, KIND_MODPACK)
        self.assertIsNone(probe.suggested_pack_type)
        self.assertFalse(probe.is_texture_source)

    def test_wrapper_folder_is_reported(self) -> None:
        path = self.make(
            "MyPack.zip",
            [
                ("MyPack/pack.mcmeta", json.dumps({"pack": {"pack_format": 34}})),
                ("MyPack/pack.png", PNG_HEADER),
                ("MyPack/assets/minecraft/textures/block/stone.png", PNG_HEADER),
            ],
        )
        probe = detect_pack_kind(path)
        self.assertKind(probe, KIND_RESOURCE_PACK)
        self.assertEqual(probe.details.get("archive_root"), "MyPack")

    def test_library_jar_is_unknown(self) -> None:
        probe = detect_pack_kind(
            self.make(
                "library.jar",
                [
                    ("com/example/Lib.class", b"\xca\xfe\xba\xbe"),
                    ("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n"),
                ],
            )
        )
        self.assertEqual(probe.kind, KIND_UNKNOWN)
        self.assertIsNone(probe.suggested_pack_type)


class TestFailureModes(PackDetectTestBase):
    def test_empty_archive(self) -> None:
        probe = detect_pack_kind(self.make("empty.zip", []))
        self.assertEqual(probe.kind, KIND_UNKNOWN)
        self.assertEqual(probe.error, "archive is empty")

    def test_corrupt_archive(self) -> None:
        path = self.root / "corrupt.jar"
        path.write_bytes(b"definitely not a zip" * 64)
        probe = detect_pack_kind(path)
        self.assertEqual(probe.kind, KIND_UNKNOWN)
        self.assertIn("zip", probe.error.lower())

    def test_text_file_with_jar_extension(self) -> None:
        path = self.root / "fake.jar"
        path.write_text("hello")
        probe = detect_pack_kind(path)
        self.assertEqual(probe.kind, KIND_UNKNOWN)
        self.assertIsNotNone(probe.error)

    def test_missing_path(self) -> None:
        probe = detect_pack_kind(self.root / "nope.zip")
        self.assertEqual(probe.kind, KIND_UNKNOWN)
        self.assertEqual(probe.error, "path does not exist")

    def test_invalid_path_type(self) -> None:
        probe = detect_pack_kind(None)
        self.assertEqual(probe.kind, KIND_UNKNOWN)
        self.assertEqual(probe.error, "invalid path")

    def test_malformed_pack_mcmeta_still_classifies(self) -> None:
        probe = detect_pack_kind(
            self.make("bad.zip", [("pack.mcmeta", "{not json"), ("assets/minecraft/textures/block/stone.png", PNG_HEADER)])
        )
        self.assertKind(probe, KIND_RESOURCE_PACK)
        self.assertIsNone(probe.details.get("pack_format"))

    def test_oversized_metadata_is_truncated(self) -> None:
        payload = json.dumps({"pack": {"pack_format": 34, "description": "x" * (256 * 1024)}})
        probe = detect_pack_kind(
            self.make("huge_meta.zip", [("pack.mcmeta", payload), ("assets/minecraft/textures/block/stone.png", PNG_HEADER)])
        )
        self.assertKind(probe, KIND_RESOURCE_PACK)

    def test_never_raises_on_unexpected_error(self) -> None:
        with patch("utils.pack_detect._classify_file", side_effect=RuntimeError("boom")):
            probe = detect_pack_kind(self.make("any.zip", _resource_pack_files()))
        self.assertEqual(probe.kind, KIND_UNKNOWN)
        self.assertIn("boom", probe.error)


class TestDirectoryClassification(PackDetectTestBase):
    def test_extracted_resource_pack(self) -> None:
        root = self.root / "pack_dir"
        (root / "assets" / "minecraft" / "textures").mkdir(parents=True)
        (root / "pack.mcmeta").write_text(json.dumps({"pack": {"pack_format": 88}}))
        (root / "pack.png").write_bytes(PNG_HEADER)
        probe = detect_pack_kind(root)
        self.assertKind(probe, KIND_RESOURCE_PACK)
        self.assertEqual(probe.details.get("pack_format"), 88)

    def test_extracted_vanilla_client(self) -> None:
        root = self.root / "client_dir"
        (root / "net" / "minecraft" / "client").mkdir(parents=True)
        (root / "assets").mkdir()
        (root / "version.json").write_text(json.dumps({"id": "26.2"}))
        probe = detect_pack_kind(root)
        self.assertKind(probe, KIND_VANILLA_CLIENT)
        self.assertEqual(probe.details.get("mc_version"), "26.2")

    def test_extracted_fabric_mod(self) -> None:
        root = self.root / "mod_dir"
        root.mkdir()
        (root / "fabric.mod.json").write_text(json.dumps({"id": "coolmod", "name": "Cool Mod"}))
        (root / "assets").mkdir()
        probe = detect_pack_kind(root)
        self.assertKind(probe, KIND_MOD)
        self.assertEqual(probe.details.get("mod_id"), "coolmod")


class TestProbeCache(PackDetectTestBase):
    def test_second_probe_is_cached(self) -> None:
        path = self.make("cached.zip", _resource_pack_files())
        first = detect_pack_kind(path)
        self.assertFalse(first.cached)
        second = detect_pack_kind(path)
        self.assertTrue(second.cached)
        info = pack_probe_cache_info()
        self.assertGreaterEqual(info["hits"], 1)
        self.assertGreaterEqual(info["misses"], 1)
        self.assertEqual(second.kind, first.kind)

    def test_invalidate_forces_reprobe(self) -> None:
        path = self.make("cached.zip", _resource_pack_files())
        detect_pack_kind(path)
        invalidate_pack_probe(path)
        probe = detect_pack_kind(path)
        self.assertFalse(probe.cached)

    def test_replaced_archive_is_reprobed(self) -> None:
        path = self.make("mutable.jar", _resource_pack_files())
        self.assertEqual(detect_pack_kind(path).kind, KIND_RESOURCE_PACK)
        _write_zip(path, _mod_files())
        self.assertEqual(detect_pack_kind(path).kind, KIND_MOD)

    def test_peek_does_not_probe(self) -> None:
        path = self.make("peek.zip", _resource_pack_files())
        self.assertIsNone(peek_cached_probe(path))
        detect_pack_kind(path)
        self.assertIsNotNone(peek_cached_probe(path))
        self.assertIsNone(peek_cached_probe(self.root / "never-probed.zip"))

    def test_cache_opt_out(self) -> None:
        path = self.make("nocache.zip", _resource_pack_files())
        detect_pack_kind(path)
        probe = detect_pack_kind(path, use_cache=False)
        self.assertFalse(probe.cached)


class TestResolvePolicy(unittest.TestCase):
    def test_manual_choice_wins(self) -> None:
        probe = detect_pack_kind(self._fixture())
        self.assertEqual(probe.suggested_pack_type, "VANILLA")
        self.assertEqual(resolve_pack_type("RESOURCE_PACK", TYPE_SOURCE_MANUAL, probe), "RESOURCE_PACK")

    def test_auto_applies_suggestion(self) -> None:
        probe = detect_pack_kind(self._fixture())
        self.assertEqual(resolve_pack_type("RESOURCE_PACK", TYPE_SOURCE_AUTO, probe), "VANILLA")

    def test_auto_without_suggestion_keeps_current(self) -> None:
        probe = detect_pack_kind(self._fixture())
        probe.suggested_pack_type = None
        self.assertEqual(resolve_pack_type("MOD_JAR", TYPE_SOURCE_AUTO, probe), "MOD_JAR")
        self.assertEqual(resolve_pack_type("MOD_JAR", TYPE_SOURCE_AUTO, None), "MOD_JAR")

    def _fixture(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "client.jar"
        _write_zip(
            path,
            [
                ("version.json", json.dumps({"id": "26.2"})),
                ("net/minecraft/client/main/Main.class", b"\xca\xfe\xba\xbe"),
                ("assets/.mcassetsroot", ""),
            ],
        )
        return path


class TestKindCatalog(unittest.TestCase):
    def test_all_kinds_are_labeled(self) -> None:
        from utils.pack_detect import KIND_LABELS, KIND_TO_PACK_TYPE

        for kind in ALL_KINDS:
            self.assertIn(kind, KIND_LABELS)
            self.assertIn(kind, KIND_TO_PACK_TYPE)

    def test_three_tier_mapping_matches_ui_enum(self) -> None:
        from utils.pack_detect import KIND_TO_PACK_TYPE

        allowed = {None, "RESOURCE_PACK", "MOD_JAR", "VANILLA"}
        for value in KIND_TO_PACK_TYPE.values():
            self.assertIn(value, allowed)


@unittest.skipUnless(fabric_jar() is not None, "workspace vanilla client JAR unavailable")
class TestRealVanillaClient(unittest.TestCase):
    def test_workspace_client_jar(self) -> None:
        invalidate_pack_probe()
        probe = detect_pack_kind(fabric_jar())
        self.assertEqual(probe.kind, KIND_VANILLA_CLIENT, probe.evidence)
        self.assertEqual(probe.suggested_pack_type, "VANILLA")
        self.assertGreater(probe.entry_count, 1000)


if __name__ == "__main__":
    unittest.main()
