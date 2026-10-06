"""
MoziToolKit Development Module.
Active only during development. Automatically mounts local .so/.pyd native libraries
and exposes developer diagnostics, N-panel tools, and headless test APIs.
"""

from . import loader
from . import api

try:
    import bpy
    from . import ops
    from . import ui
    HAS_BPY = True
except ImportError:
    ops = None
    ui = None
    HAS_BPY = False

__all__ = ["loader", "ops", "ui", "api"]


def register():
    # 1. Mount local native engine binary if available
    loader.setup_dev_environment()

    # 2. Register operators and sidebar UI if running in Blender
    if HAS_BPY and ops and ui:
        ops.register()
        ui.register()


def unregister():
    if HAS_BPY and ops and ui:
        ui.unregister()
        ops.unregister()
