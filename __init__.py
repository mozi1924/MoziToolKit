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
    "blender": (5, 2, 0),
    "version": (1, 1, 0),
    "location": "UV > Scale UV Faces / Select Transparent Faces, Edge > Select Hard & Sharp Edges, Object / Mesh > Set Image Interpolation to Closest / Clear Custom Normals",
    "warning": "",
    "category": "3D View",
}

from . import i18n
from . import operators
from . import pipeline
from . import ui


def register():
    from .utils.system import ensure_sys_paths
    ensure_sys_paths()
    i18n.register()
    operators.register()
    pipeline.register()
    ui.register()


def unregister():
    ui.unregister()
    pipeline.unregister()
    operators.unregister()
    i18n.unregister()
