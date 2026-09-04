import bpy
from .dictionary import translations_dict


def tr(msgid: str, msgctxt: str | None = None) -> str:
    """Translate string using Blender i18n registry, falling back to msgid if untranslated."""
    if not msgid:
        return ""
    try:
        return bpy.app.translations.pgettext(msgid, msgctxt)
    except Exception:
        return msgid


def _get_expanded_translations_dict() -> dict:
    """Ensure all wildcard '*' context translations are also available under 'Operator' context."""
    expanded = {}
    for lang, entries in translations_dict.items():
        lang_dict = {}
        for (ctx, msgid), trans in entries.items():
            lang_dict[(ctx, msgid)] = trans
            if ctx == "*":
                # Ensure operator context is populated so BLT_pgettext("Operator", ...) resolves correctly
                op_key = ("Operator", msgid)
                if op_key not in entries:
                    lang_dict[op_key] = trans
        expanded[lang] = lang_dict
    return expanded


def register():
    expanded_dict = _get_expanded_translations_dict()
    try:
        bpy.app.translations.register(__name__, expanded_dict)
    except ValueError:
        # Avoid error if already registered, unregister and re-register
        try:
            bpy.app.translations.unregister(__name__)
            bpy.app.translations.register(__name__, expanded_dict)
        except Exception:
            pass


def unregister():
    try:
        bpy.app.translations.unregister(__name__)
    except ValueError:
        pass

