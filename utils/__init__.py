"""
MoziToolKit Utilities Root Package.
Organized into core glue and Blender orchestration domains:
- system: Python dependency management and right-click menu registry
- config: Addon preference manager and persistence backends
- node_groups: Pure Blender shader node template generators (LabPBR, parallax, atlas UV, animations)
"""

from . import system
from . import config
from . import progress
from . import async_task

import bpy

from . import node_groups

__all__ = [
    "system",
    "config",
    "progress",
    "async_task",
    "node_groups",
]


