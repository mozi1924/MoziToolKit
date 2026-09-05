"""
MoziToolKit Utilities Root Package.
Organized into functional domains:
- materials: Material construction, resource pack parsing, atlas generation & layout
- mesh: Geometry math, bmesh contexts, UV helpers, selection scopes
- node_groups: LabPBR and animation shader template generators
- pixel_split: Adaptive pixel subdivision algorithms
- extrude_repair: Extruded side face UV & crease repair
- system: Python dependency management and right-click menu registry
"""

from . import materials
from . import mesh
from . import system
from . import culling

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

if HAS_BPY:
    from . import node_groups
    from . import pixel_split
    from . import extrude_repair
else:
    node_groups = None
    pixel_split = None
    extrude_repair = None

__all__ = [
    "materials",
    "mesh",
    "node_groups",
    "pixel_split",
    "extrude_repair",
    "system",
    "culling",
]

