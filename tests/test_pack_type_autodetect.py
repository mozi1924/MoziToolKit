"""
Integration tests for automatic pack type detection in the preferences glue layer.

Covers the pure apply policy (``ui.preferences_packs.apply_probe_to_entry``), the update-callback
behaviour that keeps manual corrections authoritative, and the persistence round-trip of
``pack_type_source`` / ``detected_kind``.
"""

from __future__ import annotations

import json
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import bpy

import ui.preferences_packs as packs_ui
from utils.config.models import PackEntry
from utils.pack_detect import (
    KIND_DATA_PACK,
    KIND_MOD,
    KIND_RESOURCE_PACK,
    KIND_UNKNOWN,
    KIND_VANILLA_CLIENT,
    PackProbe,
    detect_pack_kind,
    invalidate_pack_probe,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _write_zip(path: Path, entries) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return path


def _resource_pack(path: Path) -> Path:
    return _write_zip(
        path,
        [
            ("pack.mcmeta", json.dumps({"pack": {"pack_format": 88, "description": "Test"}})),
            ("pack.png", PNG),
            ("assets/minecraft/textures/block/stone.png", PNG),
        ],
    )


def _vanilla_client(path: Path) -> Path:
    return _write_zip(
        path,
        [
            ("version.json", json.dumps({"id": "26.2"})),
            ("net/minecraft/client/main/Main.class", b"\xca\xfe\xba\xbe"),
            ("assets/.mcassetsroot", ""),
        ],
    )


def _entry(path: Path, **overrides) -> types.SimpleNamespace:
    values = {
        "name": "Resource Pack #1",
        "path": str(path),
        "enabled": True,
        "pack_type": "RESOURCE_PACK",
        "pack_type_source": "AUTO",
        "detected_kind": "",
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


class TestApplyProbePolicy(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        invalidate_pack_probe()

    def tearDown(self) -> None:
        invalidate_pack_probe()
        self._tmp.cleanup()

    def test_auto_mode_applies_detected_type(self) -> None:
        path = _vanilla_client(self.root / "client.jar")
        probe = detect_pack_kind(path)
        item = _entry(path, name="client")
        self.assertTrue(packs_ui.apply_probe_to_entry(item, probe))
        self.assertEqual(item.pack_type, "VANILLA")
        self.assertEqual(item.detected_kind, KIND_VANILLA_CLIENT)
        self.assertEqual(item.pack_type_source, "AUTO")

    def test_manual_mode_keeps_user_choice(self) -> None:
        path = _vanilla_client(self.root / "client.jar")
        probe = detect_pack_kind(path)
        item = _entry(path, name="my pack", pack_type="RESOURCE_PACK", pack_type_source="MANUAL")
        packs_ui.apply_probe_to_entry(item, probe)
        self.assertEqual(item.pack_type, "RESOURCE_PACK")
        self.assertEqual(item.detected_kind, KIND_VANILLA_CLIENT)
        self.assertEqual(item.pack_type_source, "MANUAL")

    def test_unknown_probe_keeps_type(self) -> None:
        item = _entry(self.root / "whatever.zip")
        packs_ui.apply_probe_to_entry(item, PackProbe(kind=KIND_UNKNOWN, error="nope"))
        self.assertEqual(item.pack_type, "RESOURCE_PACK")
        self.assertEqual(item.detected_kind, KIND_UNKNOWN)

    def test_mod_detection_uses_mod_tier(self) -> None:
        path = _write_zip(
            self.root / "mod.jar",
            [("fabric.mod.json", json.dumps({"id": "coolmod", "name": "Cool Mod"})), ("assets/x/lang/en_us.json", "{}")],
        )
        probe = detect_pack_kind(path)
        item = _entry(path, name="mod.jar")
        packs_ui.apply_probe_to_entry(item, probe)
        self.assertEqual(item.pack_type, "MOD_JAR")
        self.assertEqual(item.detected_kind, KIND_MOD)

    def test_name_is_upgraded_only_when_untouched(self) -> None:
        path = _vanilla_client(self.root / "26.2-Fabric.jar")
        probe = detect_pack_kind(path)

        auto_named = _entry(path, name="26.2 Fabric")
        packs_ui.apply_probe_to_entry(auto_named, probe)
        self.assertEqual(auto_named.name, "Minecraft 26.2")

        custom_named = _entry(path, name="My custom pack")
        packs_ui.apply_probe_to_entry(custom_named, probe)
        self.assertEqual(custom_named.name, "My custom pack")

    def test_data_pack_records_kind_without_type_change(self) -> None:
        path = _write_zip(
            self.root / "datapack.zip",
            [("pack.mcmeta", json.dumps({"pack": {"pack_format": 107}})), ("data/minecraft/recipe/x.json", "{}")],
        )
        probe = detect_pack_kind(path)
        item = _entry(path)
        packs_ui.apply_probe_to_entry(item, probe)
        self.assertEqual(item.detected_kind, KIND_DATA_PACK)
        self.assertEqual(item.pack_type, "RESOURCE_PACK")


class TestDetectionPresentation(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        invalidate_pack_probe()

    def tearDown(self) -> None:
        invalidate_pack_probe()
        self._tmp.cleanup()

    def test_undetected_entry_label(self) -> None:
        text, icon = packs_ui.describe_detected_kind(types.SimpleNamespace(detected_kind="", path=""))
        self.assertTrue(text)
        self.assertEqual(icon, "INFO")

    def test_detected_label_includes_confidence_when_cached(self) -> None:
        path = _resource_pack(self.root / "pack.zip")
        probe = detect_pack_kind(path)
        text, icon = packs_ui.describe_detected_kind(
            types.SimpleNamespace(detected_kind=KIND_RESOURCE_PACK, path=str(path))
        )
        self.assertIn("%", text)
        self.assertEqual(icon, "PACKAGE")
        self.assertTrue(probe.is_known)

    def test_data_pack_warning(self) -> None:
        warning = packs_ui.detected_kind_warning(types.SimpleNamespace(detected_kind=KIND_DATA_PACK, path=""))
        self.assertIsNotNone(warning)

    def test_no_warning_for_resource_pack(self) -> None:
        self.assertIsNone(
            packs_ui.detected_kind_warning(types.SimpleNamespace(detected_kind=KIND_RESOURCE_PACK, path=""))
        )

    def test_wrapped_archive_warning(self) -> None:
        path = _write_zip(
            self.root / "wrapped.zip",
            [
                ("MyPack/pack.mcmeta", json.dumps({"pack": {"pack_format": 34}})),
                ("MyPack/assets/minecraft/textures/block/stone.png", PNG),
            ],
        )
        detect_pack_kind(path)
        warning = packs_ui.detected_kind_warning(
            types.SimpleNamespace(detected_kind=KIND_RESOURCE_PACK, path=str(path))
        )
        self.assertIsNotNone(warning)


class TestUpdateCallbacks(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        invalidate_pack_probe()
        packs_ui._set_is_probing(False)
        packs_ui._set_is_reordering(False)

    def tearDown(self) -> None:
        invalidate_pack_probe()
        packs_ui._set_is_probing(False)
        packs_ui._set_is_reordering(False)
        self._tmp.cleanup()

    def test_manual_pack_type_marks_source_manual(self) -> None:
        item = _entry(self.root / "x.zip", pack_type_source="AUTO")
        with patch.object(packs_ui, "_safe_get_prefs", return_value=None):
            packs_ui.on_pack_type_changed(item, None)
        self.assertEqual(item.pack_type_source, "MANUAL")

    def test_existing_manual_source_is_not_downgraded(self) -> None:
        item = _entry(self.root / "x.zip", pack_type_source="MANUAL")
        with patch.object(packs_ui, "_safe_get_prefs", return_value=None):
            packs_ui.on_pack_type_changed(item, None)
        self.assertEqual(item.pack_type_source, "MANUAL")

    def test_path_change_detects_and_applies_without_timers(self) -> None:
        path = _vanilla_client(self.root / "client.jar")
        item = _entry(path)
        prefs = types.SimpleNamespace(resource_packs=[item])
        manager = MagicMock()
        manager.is_syncing.return_value = False
        with patch.object(packs_ui, "_safe_get_prefs", return_value=prefs), patch.object(
            packs_ui, "get_config_manager", return_value=manager
        ), patch.object(packs_ui, "refresh_ui_and_menus"), patch.object(
            packs_ui, "_timers_available", return_value=False
        ):
            packs_ui.on_pack_path_changed(item, None)
        self.assertEqual(item.pack_type, "VANILLA")
        self.assertEqual(item.detected_kind, KIND_VANILLA_CLIENT)

    def test_path_change_respects_manual_source(self) -> None:
        path = _vanilla_client(self.root / "client.jar")
        item = _entry(path, pack_type="RESOURCE_PACK", pack_type_source="MANUAL")
        prefs = types.SimpleNamespace(resource_packs=[item])
        manager = MagicMock()
        manager.is_syncing.return_value = False
        with patch.object(packs_ui, "_safe_get_prefs", return_value=prefs), patch.object(
            packs_ui, "get_config_manager", return_value=manager
        ), patch.object(packs_ui, "refresh_ui_and_menus"), patch.object(
            packs_ui, "_timers_available", return_value=False
        ):
            packs_ui.on_pack_path_changed(item, None)
        self.assertEqual(item.pack_type, "RESOURCE_PACK")
        self.assertEqual(item.detected_kind, "")

    def test_missing_path_does_not_probe(self) -> None:
        item = _entry(self.root / "missing.zip")
        with patch.object(packs_ui, "_safe_get_prefs", return_value=None), patch.object(
            packs_ui, "_timers_available", return_value=False
        ):
            packs_ui.on_pack_path_changed(item, None)
        self.assertEqual(item.detected_kind, "")


class TestPersistence(unittest.TestCase):
    def test_pack_entry_round_trip(self) -> None:
        entry = PackEntry(
            name="Client",
            path="/tmp/client.jar",
            enabled=True,
            pack_type="VANILLA",
            pack_type_source="MANUAL",
            detected_kind=KIND_VANILLA_CLIENT,
        )
        restored = PackEntry.from_dict(entry.to_dict())
        self.assertEqual(restored.pack_type_source, "MANUAL")
        self.assertEqual(restored.detected_kind, KIND_VANILLA_CLIENT)
        self.assertEqual(restored.pack_type, "VANILLA")

    def test_legacy_config_defaults_to_auto(self) -> None:
        restored = PackEntry.from_dict({"name": "Old", "path": "/tmp/old.zip", "enabled": True, "pack_type": "MOD_JAR"})
        self.assertEqual(restored.pack_type_source, "AUTO")
        self.assertEqual(restored.detected_kind, "")
        self.assertEqual(restored.pack_type, "MOD_JAR")

    def test_invalid_source_falls_back_to_auto(self) -> None:
        restored = PackEntry.from_dict({"pack_type_source": "SOMETHING"})
        self.assertEqual(restored.pack_type_source, "AUTO")


class TestRegistration(unittest.TestCase):
    def test_detect_operator_is_registered(self) -> None:
        names = [cls.bl_idname for cls in packs_ui.PACKS_CLASSES if hasattr(cls, "bl_idname")]
        self.assertIn("mozi.pack_detect", names)

    def test_entry_property_group_declares_detection_fields(self) -> None:
        annotations = getattr(packs_ui.MOZI_PG_resource_pack_entry, "__annotations__", {})
        self.assertIn("pack_type_source", annotations)
        self.assertIn("detected_kind", annotations)


class _RecordingLayout:
    """Minimal UILayout double that records what the panel asks for."""

    def __init__(self, calls=None):
        self.calls = calls if calls is not None else []

    def _child(self):
        return _RecordingLayout(self.calls)

    def row(self, align=False):
        return self._child()

    def column(self, align=False):
        return self._child()

    def box(self):
        return self._child()

    def label(self, text="", icon="NONE"):
        self.calls.append(("label", text, icon))

    def prop(self, data, name, **kwargs):
        self.calls.append(("prop", name, kwargs.get("text", "")))

    def operator(self, idname, **kwargs):
        self.calls.append(("operator", idname))
        return types.SimpleNamespace()

    def separator(self, factor=1.0):
        pass

    def template_list(self, *args, **kwargs):
        self.calls.append(("template_list", args[0]))


class TestPanelDraw(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        invalidate_pack_probe()

    def tearDown(self) -> None:
        invalidate_pack_probe()
        self._tmp.cleanup()

    def _prefs(self, item):
        return types.SimpleNamespace(
            resource_packs=[item],
            resource_packs_index=0,
            pack_textures=True,
            enable_ctm=True,
            enable_animated_textures=True,
        )

    def test_draw_renders_detection_rows(self) -> None:
        from MoziToolKit.ui.preferences import MOZI_AddonPreferences

        path = _resource_pack(self.root / "pack.zip")
        detect_pack_kind(path)
        item = _entry(path, detected_kind=KIND_RESOURCE_PACK)
        layout = _RecordingLayout()
        MOZI_AddonPreferences.draw_resource_packs(self._prefs(item), layout, None)

        prop_names = [call[1] for call in layout.calls if call[0] == "prop"]
        operators = [call[1] for call in layout.calls if call[0] == "operator"]
        self.assertIn("pack_type_source", prop_names)
        self.assertIn("mozi.pack_detect", operators)
        from MoziToolKit.i18n import tr

        self.assertTrue(any(call[0] == "label" and call[1].startswith(tr("Detected")) for call in layout.calls))

    def test_draw_shows_warning_for_data_pack(self) -> None:
        from MoziToolKit.ui.preferences import MOZI_AddonPreferences

        path = self.root / "datapack.zip"
        _write_zip(
            path,
            [("pack.mcmeta", json.dumps({"pack": {"pack_format": 107}})), ("data/minecraft/recipe/x.json", "{}")],
        )
        item = _entry(path, detected_kind=KIND_DATA_PACK)
        layout = _RecordingLayout()
        MOZI_AddonPreferences.draw_resource_packs(self._prefs(item), layout, None)
        from MoziToolKit.i18n import tr

        expected = tr("This archive provides no textures for baking (data pack / modpack).")
        self.assertTrue(any(call[0] == "label" and call[1] == expected for call in layout.calls))

    def test_draw_without_path(self) -> None:
        from MoziToolKit.ui.preferences import MOZI_AddonPreferences

        item = types.SimpleNamespace(
            name="Empty",
            path="",
            enabled=True,
            pack_type="RESOURCE_PACK",
            pack_type_source="AUTO",
            detected_kind="",
        )
        layout = _RecordingLayout()
        MOZI_AddonPreferences.draw_resource_packs(self._prefs(item), layout, None)
        from MoziToolKit.i18n import tr

        self.assertTrue(any(call[0] == "label" and call[1].startswith(tr("Detected")) for call in layout.calls))


class TestStartupMigration(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        invalidate_pack_probe()

    def tearDown(self) -> None:
        invalidate_pack_probe()
        self._tmp.cleanup()

    def test_only_unclassified_auto_entries_are_scheduled(self) -> None:
        present = _resource_pack(self.root / "present.zip")
        entries = [
            _entry(present),
            _entry(present, pack_type_source="MANUAL"),
            _entry(present, detected_kind=KIND_RESOURCE_PACK),
            _entry(self.root / "missing.zip"),
        ]
        prefs = types.SimpleNamespace(resource_packs=entries)
        with patch.object(packs_ui, "schedule_pack_probe") as schedule:
            count = packs_ui.schedule_pending_pack_detection(prefs)
        self.assertEqual(count, 1)
        schedule.assert_called_once_with(str(present))

    def test_none_prefs_is_safe(self) -> None:
        self.assertEqual(packs_ui.schedule_pending_pack_detection(None), 0)


class TestAsyncProbePipeline(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        invalidate_pack_probe()
        packs_ui._set_is_probing(False)
        packs_ui._set_is_reordering(False)

    def tearDown(self) -> None:
        invalidate_pack_probe()
        packs_ui._set_is_probing(False)
        packs_ui._set_is_reordering(False)
        self._tmp.cleanup()

    def test_tick_applies_queued_result_then_goes_idle(self) -> None:
        path = _vanilla_client(self.root / "client.jar")
        item = _entry(path)
        prefs = types.SimpleNamespace(resource_packs=[item])
        manager = MagicMock()
        manager.is_syncing.return_value = False
        probe = detect_pack_kind(path)
        packs_ui._probe_results.put((str(path), probe))
        with patch.object(packs_ui, "_safe_get_prefs", return_value=prefs), patch.object(
            packs_ui, "get_config_manager", return_value=manager
        ), patch.object(packs_ui, "refresh_ui_and_menus"):
            self.assertIsNone(packs_ui._pack_probe_tick())
        self.assertEqual(item.pack_type, "VANILLA")
        self.assertEqual(item.detected_kind, KIND_VANILLA_CLIENT)

    def test_worker_thread_publishes_result(self) -> None:
        path = _resource_pack(self.root / "pack.zip")
        import time

        packs_ui._start_probe(str(path))
        deadline = time.monotonic() + 5.0
        result = None
        while time.monotonic() < deadline:
            try:
                result = packs_ui._probe_results.get(timeout=0.05)
                break
            except Exception:
                continue
        self.assertIsNotNone(result, "worker did not publish a probe result")
        key, probe = result
        self.assertEqual(key, str(path))
        self.assertEqual(probe.kind, KIND_RESOURCE_PACK)


if __name__ == "__main__":
    unittest.main()
