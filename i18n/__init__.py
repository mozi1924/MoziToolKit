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


def register():
    try:
        bpy.app.translations.register(__name__, translations_dict)
    except ValueError:
        # Avoid error if already registered, unregister and re-register
        try:
            bpy.app.translations.unregister(__name__)
            bpy.app.translations.register(__name__, translations_dict)
        except Exception:
            pass


def unregister():
    try:
        bpy.app.translations.unregister(__name__)
    except ValueError:
        pass

