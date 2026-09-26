try:
    import bpy
except ImportError:
    bpy = None

from .dictionary import translations_dict


def tr(msgid: str, msgctxt: str | None = None) -> str:
    """Translate string using Blender i18n registry, falling back to dictionary/msgid if untranslated."""
    if not msgid:
        return ""
    if bpy is not None and hasattr(bpy, "app") and hasattr(bpy.app, "translations"):
        try:
            return bpy.app.translations.pgettext(msgid, msgctxt)
        except Exception:
            pass

    # Direct dictionary fallback for testing or non-Blender environments
    hans = translations_dict.get("zh_HANS", {})
    if msgctxt and (msgctxt, msgid) in hans:
        return hans[(msgctxt, msgid)]
    if ("*", msgid) in hans:
        return hans[("*", msgid)]
    return msgid


def _get_expanded_translations_dict() -> dict:
    """Ensure all wildcard '*' context translations are also available under 'Operator' and 'operator_default' contexts, and mirror zh_HANS / zh_CN."""
    expanded = {}
    for lang, entries in translations_dict.items():
        lang_dict = {}
        for (ctx, msgid), trans in entries.items():
            lang_dict[(ctx, msgid)] = trans
            if ctx == "*":
                # Ensure operator contexts are populated so BLT_pgettext resolves correctly
                for extra_ctx in ("Operator", "operator_default"):
                    extra_key = (extra_ctx, msgid)
                    if extra_key not in entries:
                        lang_dict[extra_key] = trans
        expanded[lang] = lang_dict

    # Mirror zh_HANS <-> zh_CN so both Blender locale identifiers work seamlessly
    if "zh_HANS" in expanded and "zh_CN" not in expanded:
        expanded["zh_CN"] = expanded["zh_HANS"].copy()
    elif "zh_CN" in expanded and "zh_HANS" not in expanded:
        expanded["zh_HANS"] = expanded["zh_CN"].copy()

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

