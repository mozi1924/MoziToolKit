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
    "blender": (4, 2, 0),
    "version": (1, 0, 0),
    "location": "UV > Scale UV Faces / Select Transparent Faces, Edge > Select Hard & Sharp Edges, Object / Mesh > Set Image Interpolation to Closest / Clear Custom Normals",
    "warning": "",
    "category": "3D View",
}

from . import auto_load
from . import i18n

auto_load.init()


def register():
    i18n.register()
    auto_load.register()


def unregister():
    auto_load.unregister()
    i18n.unregister()

