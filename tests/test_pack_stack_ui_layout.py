"""
Layout tests for the Resource Pack / Base JAR preferences tab.

Covers two UI contracts:

* Newly added pack entries are inserted at the **top** of the stack (highest resolution
  priority), matching Minecraft's "new pack overrides everything below it" model.
* Material replacement defaults (``pack_textures`` / CTM / animated textures) live in the
  **Material & Shading** tab, not in the Resource Packs tab.
"""

from __future__ import annotations

import types
import unittest
from unittest.mock import MagicMock, patch

import ui.preferences_packs as packs_ui
from MoziToolKit.i18n import tr
from MoziToolKit.ui.preferences import MOZI_AddonPreferences


class _RecordingLayout:
    """Minimal UILayout double that records what a panel asks for."""

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

    # -- helpers -------------------------------------------------------
    def labels(self):
        return [call[1] for call in self.calls if call[0] == "label"]

    def prop_names(self):
        return [call[1] for call in self.calls if call[0] == "prop"]

    def operators(self):
        return [call[1] for call in self.calls if call[0] == "operator"]


class _FakeCollection(list):
    """Stand-in for a Blender CollectionProperty (add/move/len/iteration)."""

    def add(self):
        item = types.SimpleNamespace(
            name="",
            path="",
            enabled=False,
            pack_type="RESOURCE_PACK",
            pack_type_source="AUTO",
            detected_kind="",
        )
        self.append(item)
        return item

    def move(self, from_index: int, to_index: int) -> None:
        self.insert(to_index, self.pop(from_index))

    def clear(self):
        del self[:]


def _pack(name: str, path: str = "") -> types.SimpleNamespace:
    return types.SimpleNamespace(
        name=name,
        path=path,
        enabled=True,
        pack_type="RESOURCE_PACK",
        pack_type_source="AUTO",
        detected_kind="",
    )


class TestAddInsertsAtTop(unittest.TestCase):
    def _prefs(self, names):
        coll = _FakeCollection(_pack(name, f"/packs/{name}.zip") for name in names)
        return types.SimpleNamespace(resource_packs=coll, resource_packs_index=0, is_initialized=True)

    def _run_add(self, prefs):
        manager = MagicMock()
        manager.is_syncing.return_value = False
        with patch.object(packs_ui, "_safe_get_prefs", return_value=prefs), patch.object(
            packs_ui, "get_config_manager", return_value=manager
        ), patch.object(packs_ui, "refresh_ui_and_menus"):
            result = packs_ui.MOZI_OT_pack_add.execute(types.SimpleNamespace(), None)
        return result

    def test_new_entry_is_prepended(self) -> None:
        prefs = self._prefs(["A", "B", "C"])
        self.assertEqual(self._run_add(prefs), {"FINISHED"})
        names = [item.name for item in prefs.resource_packs]
        self.assertEqual(names, ["Resource Pack #4", "A", "B", "C"])

    def test_new_entry_becomes_the_active_selection(self) -> None:
        prefs = self._prefs(["A", "B"])
        prefs.resource_packs_index = 1
        self._run_add(prefs)
        self.assertEqual(prefs.resource_packs_index, 0)
        self.assertEqual(prefs.resource_packs[0].name, "Resource Pack #3")

    def test_new_entry_defaults_stay_automatic(self) -> None:
        prefs = self._prefs([])
        self._run_add(prefs)
        new_item = prefs.resource_packs[0]
        self.assertEqual(new_item.pack_type, "RESOURCE_PACK")
        self.assertEqual(new_item.pack_type_source, "AUTO")
        self.assertEqual(new_item.detected_kind, "")
        self.assertTrue(new_item.enabled)

    def test_single_entry_list_still_works(self) -> None:
        prefs = self._prefs(["A"])
        self._run_add(prefs)
        self.assertEqual([item.name for item in prefs.resource_packs], ["Resource Pack #2", "A"])


class TestMaterialSettingsPlacement(unittest.TestCase):
    def _prefs(self):
        return types.SimpleNamespace(
            resource_packs=[_pack("A", "/packs/A.zip")],
            resource_packs_index=0,
            pack_textures=True,
            enable_ctm=True,
            enable_animated_textures=True,
            material_render_engine="AUTO",
            enable_game_semantics=True,
            material_transmission_mode="AUTO",
            material_thin_wall_mode="AUTO",
            material_subsurface_method="BURLEY",
            material_disable_subsurface=False,
        )

    def test_material_replacement_box_is_not_in_the_pack_tab(self) -> None:
        layout = _RecordingLayout()
        MOZI_AddonPreferences.draw_resource_packs(self._prefs(), layout, None)
        self.assertNotIn(tr("Default Material Replacement Settings:"), layout.labels())
        self.assertNotIn("pack_textures", layout.prop_names())
        self.assertNotIn("enable_ctm", layout.prop_names())

    def test_material_tab_hosts_replacement_settings(self) -> None:
        layout = _RecordingLayout()
        context = types.SimpleNamespace(scene=types.SimpleNamespace(render=types.SimpleNamespace(engine="CYCLES")))
        MOZI_AddonPreferences.draw_material(self._prefs(), layout, context)
        self.assertIn(tr("Default Material Replacement Settings:"), layout.labels())
        self.assertIn("pack_textures", layout.prop_names())
        self.assertIn("enable_ctm", layout.prop_names())
        self.assertIn("enable_animated_textures", layout.prop_names())

    def test_pack_tab_keeps_cache_actions(self) -> None:
        layout = _RecordingLayout()
        MOZI_AddonPreferences.draw_resource_packs(self._prefs(), layout, None)
        self.assertIn("mozi.precompile_cache", layout.operators())
        self.assertIn("mozi.open_cache_folder", layout.operators())


if __name__ == "__main__":
    unittest.main()
