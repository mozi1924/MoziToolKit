# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTIBILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

bl_info = {
    "name": "MoziToolKit",
    "author": "Mozi Arasaka",
    "description": "Quick utility toolkit for Blender modelling & UV editing",
    "blender": (5, 0, 0),
    "version": (1, 1, 0),
    "location": "UV > Scale UV Faces / Select Transparent Faces, Edge > Select Hard & Sharp Edges, Object / Mesh > Set Image Interpolation to Closest / Clear Custom Normals",
    "warning": "",
    "category": "3D View",
}

import sys

# 0. Early development bootstrap: ensure dev/lib (.so) is mounted on sys.path
try:
    from .dev import loader
    loader.setup_dev_environment()
except ImportError:
    pass

# Aliasing for Blender 4.2+ extension repos (e.g. bl_ext.vscode_development.MoziToolKit)
if __name__ not in ("MoziToolKit", "__main__"):
    sys.modules.setdefault("MoziToolKit", sys.modules[__name__])

from . import i18n
from . import operators
from . import ui


def register():
    # 0. Development environment & local native library mounting
    try:
        from . import dev
        dev.register()
    except ImportError:
        pass

    i18n.register()
    operators.register()
    ui.register()

    # Inject canonical material properties configuration into Rust core
    try:
        from .bridge.material import load_material_properties_config
        load_material_properties_config()
    except Exception:
        pass

    # Register persistent real-time render engine adaptation listeners
    try:
        from .utils.materials.builder.adaptation import register_render_engine_adaptation_handlers
        register_render_engine_adaptation_handlers()
    except Exception:
        pass


def unregister():
    try:
        from .utils.materials.builder.adaptation import unregister_render_engine_adaptation_handlers
        unregister_render_engine_adaptation_handlers()
    except Exception:
        pass

    ui.unregister()
    operators.unregister()
    i18n.unregister()

    try:
        from . import dev
        dev.unregister()
    except ImportError:
        pass


