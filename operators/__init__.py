"""
MoziToolKit Operators Package
"""

from . import mesh
from . import misc
from . import object
from . import sync
from . import uv


def register():
    mesh.register()
    misc.register()
    object.register()
    sync.register()
    uv.register()


def unregister():
    uv.unregister()
    sync.unregister()
    object.unregister()
    misc.unregister()
    mesh.unregister()
