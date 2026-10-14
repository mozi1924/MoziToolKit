"""
Tests for CTM (Connected Textures) Internationalization & Localization.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

try:
    import bpy
    HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "meshes") and not isinstance(bpy.data, MagicMock)
except ImportError:
    HAS_BPY = False

from i18n import tr, _get_expanded_translations_dict
from i18n.dictionary import translations_dict


class TestCtmI18n(unittest.TestCase):
    """Test suite for CTM UI translations in both mock and real Blender host environments."""

    def test_ctm_dictionary_entries_present(self):
        """Verify all CTM core strings are in zh_HANS translations_dict."""
        hans = translations_dict.get("zh_HANS", {})
        
        expected_mappings = {
            "Connected Textures (CTM)": "连接纹理 (CTM)",
            "Connected Textures": "连接纹理",
            "Enable Connected Textures (CTM)": "启用连接纹理 (CTM)",
            "Enable OptiFine and Continuity connected textures resolution": "启用 OptiFine 与 Continuity 连接纹理求解",
            "Enable OptiFine / Continuity connected textures during world meshing": "在世界网格化过程中启用 OptiFine / Continuity 连接纹理",
            "Clean Connected Glass": "纯净连接玻璃",
            "Vanilla Connected Glass": "原版风格连接玻璃",
            "Connected Glass": "连接玻璃",
            "Connected textures for glass blocks and panes.": "玻璃方块与玻璃板的连接纹理。",
            "Seamless connected textures for glass and stained glass.": "玻璃及染色玻璃的无缝连接纹理。",
            "Vanilla styled connected textures for all types of glass blocks.": "全类型玻璃方块的原版风格连接纹理。",
            "CTM Rules": "CTM 规则",
            "CTM Solver": "CTM 求解器",
        }

        for msgid, expected in expected_mappings.items():
            self.assertIn(("*", msgid), hans, f"Missing dictionary entry for '{msgid}'")
            self.assertEqual(hans[("*", msgid)], expected)

    def test_tr_function_fallback(self):
        """Verify the tr() helper returns the correct Chinese translations."""
        self.assertEqual(tr("Connected Textures (CTM)"), "连接纹理 (CTM)")
        self.assertEqual(tr("Enable Connected Textures (CTM)"), "启用连接纹理 (CTM)")
        self.assertEqual(tr("Enable OptiFine and Continuity connected textures resolution"), "启用 OptiFine 与 Continuity 连接纹理求解")
        self.assertEqual(tr("Enable OptiFine / Continuity connected textures during world meshing"), "在世界网格化过程中启用 OptiFine / Continuity 连接纹理")
        self.assertEqual(tr("CTM Rules"), "CTM 规则")
        self.assertEqual(tr("CTM Solver"), "CTM 求解器")

    def test_expanded_translations_dict(self):
        """Verify expanded dictionary populates Operator/UI contexts and mirrors zh_HANS to zh_CN."""
        expanded = _get_expanded_translations_dict()
        self.assertIn("zh_HANS", expanded)
        self.assertIn("zh_CN", expanded)

        for lang in ("zh_HANS", "zh_CN"):
            lang_dict = expanded[lang]
            self.assertEqual(lang_dict.get(("UI", "Connected Textures (CTM)")), "连接纹理 (CTM)")
            self.assertEqual(lang_dict.get(("Operator", "Connected Textures (CTM)")), "连接纹理 (CTM)")
            self.assertEqual(lang_dict.get(("DEFAULT", "Connected Textures (CTM)")), "连接纹理 (CTM)")

    def test_blender_host_pgettext(self):
        """Verify real Blender host translations via bpy.app.translations."""
        if not HAS_BPY:
            self.skipTest("Requires real Blender host environment")

        import i18n
        i18n.register()

        # Configure Blender view to Simplified Chinese
        saved_lang = getattr(bpy.context.preferences.view, "language", "DEFAULT")
        saved_ui = getattr(bpy.context.preferences.view, "use_translate_interface", False)
        saved_tips = getattr(bpy.context.preferences.view, "use_translate_tooltips", False)

        try:
            bpy.context.preferences.view.language = "zh_HANS"
            bpy.context.preferences.view.use_translate_interface = True
            bpy.context.preferences.view.use_translate_tooltips = True

            self.assertEqual(bpy.app.translations.pgettext("Connected Textures (CTM)"), "连接纹理 (CTM)")
            self.assertEqual(
                bpy.app.translations.pgettext("Enable OptiFine and Continuity connected textures resolution"),
                "启用 OptiFine 与 Continuity 连接纹理求解",
            )
            self.assertEqual(
                bpy.app.translations.pgettext("Enable OptiFine / Continuity connected textures during world meshing"),
                "在世界网格化过程中启用 OptiFine / Continuity 连接纹理",
            )

            # Test operator RNA property translation
            from operators.save.op_import_save import MTK_OT_import_minecraft_save
            was_registered = False
            try:
                bpy.utils.register_class(MTK_OT_import_minecraft_save)
                was_registered = True
            except ValueError:
                pass

            try:
                rna_type = bpy.ops.mtk.import_minecraft_save.get_rna_type()
                rna_prop = rna_type.properties["enable_ctm"]
                trans_name = bpy.app.translations.pgettext_data(rna_prop.name, "Operator")
                trans_desc = bpy.app.translations.pgettext_tip(rna_prop.description, "Operator")

                self.assertEqual(trans_name, "连接纹理 (CTM)")
                self.assertEqual(trans_desc, "在世界网格化过程中启用 OptiFine / Continuity 连接纹理")
            finally:
                if was_registered:
                    try:
                        bpy.utils.unregister_class(MTK_OT_import_minecraft_save)
                    except Exception:
                        pass

        finally:
            bpy.context.preferences.view.language = saved_lang
            bpy.context.preferences.view.use_translate_interface = saved_ui
            bpy.context.preferences.view.use_translate_tooltips = saved_tips


if __name__ == "__main__":
    unittest.main()
