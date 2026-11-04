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
    "description": "Minecraft asset processing, live world sync, and smart UV tools",
    "blender": (5, 0, 0),
    "version": (2, 0, 0),
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


from . import bridge
from . import i18n
from . import operators
from . import ui


def register():
    # 0. Sync OS system proxies into process environment
    try:
        from .utils.system.network import sync_system_proxies
        sync_system_proxies()
    except Exception:
        pass

    # 1. Development environment & local native library mounting
    try:
        from . import dev
        dev.register()
    except ImportError:
        pass

    i18n.register()
    operators.register()
    ui.register()


def unregister():
    ui.unregister()
    operators.unregister()
    i18n.unregister()

    try:
        from . import dev
        dev.unregister()
    except ImportError:
        pass


