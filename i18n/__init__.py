import bpy
from .dictionary import translations_dict


def register():
    try:
        bpy.app.translations.register(__name__, translations_dict)
    except ValueError:
        # Avoid error if already registered
        pass


def unregister():
    try:
        bpy.app.translations.unregister(__name__)
    except ValueError:
        pass
