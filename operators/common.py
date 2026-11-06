"""
Common operator mixins and UI helpers for mesh reconstruction and import/export.
"""

from __future__ import annotations

from typing import Any

import bpy
from bpy.props import BoolProperty


class CommonMeshingOptionsMixin:
    """
    Shared RNA meshing and shader options for world save and scene import operators.
    Provides Single Source of Truth (SSOT) for geometry reconstruction and shading flags.
    """

    enable_ao: BoolProperty(  # type: ignore
        name="Ambient Occlusion",
        description="Calculate smooth 4-corner ambient occlusion lighting",
        default=True,
    )

    mesh_fluids: BoolProperty(  # type: ignore
        name="Mesh Fluids",
        description="Mesh physically accurate fluid surfaces",
        default=True,
    )

    weld_vertices: BoolProperty(  # type: ignore
        name="Weld Vertices",
        description="Weld adjacent shared coplanar vertices into seamless manifold topology",
        default=True,
    )

    origin_centered: BoolProperty(  # type: ignore
        name="Origin Centered",
        description="Center imported world geometry at the scene origin [0, 0, 0]",
        default=True,
    )

    enable_ctm: BoolProperty(  # type: ignore
        name="Connected Textures (CTM)",
        description="Enable OptiFine / Continuity connected textures during world meshing",
        default=True,
    )

    enable_animated_textures: BoolProperty(  # type: ignore
        name="Animated Textures",
        description="Enable animated texture frame playback for water, lava, fire, and animated blocks",
        default=True,
    )

    force: BoolProperty(  # type: ignore
        name="Force Unknown Blocks",
        description="Proceed with meshing even if unknown blocks without models/textures are detected",
        default=False,
    )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Ensure subclass inherits annotations and class attributes for inspection and Blender RNA registration
        if not hasattr(cls, "__annotations__") or cls.__annotations__ is None:
            cls.__annotations__ = {}
        for key, val in CommonMeshingOptionsMixin.__annotations__.items():
            if key not in cls.__annotations__:
                cls.__annotations__[key] = val
            if not hasattr(cls, key):
                setattr(cls, key, val)

    def draw_meshing_options(
        self,
        layout: bpy.types.UILayout,
        *,
        show_host_fallback: bool = False,
        show_ctm: bool = True,
    ) -> None:
        """Draws the shared Meshing & Shaders options box in operator file dialog sidebar."""
        draw_meshing_options(
            layout,
            self,
            show_host_fallback=show_host_fallback,
            show_ctm=show_ctm,
        )


def draw_meshing_options(
    layout: bpy.types.UILayout,
    target: Any,
    *,
    show_host_fallback: bool = False,
    show_ctm: bool = True,
) -> None:
    """
    Draws the canonical Meshing & Shaders options box for save/scene operators or property groups.
    """
    from ..i18n import tr

    box_mesh = layout.box()
    box_mesh.label(text=tr("Meshing & Shaders"), icon="MATERIAL")
    box_mesh.prop(target, "enable_ao", text=tr("Ambient Occlusion"))
    box_mesh.prop(target, "mesh_fluids", text=tr("Mesh Fluids"))
    box_mesh.prop(target, "weld_vertices", text=tr("Weld Vertices"))
    box_mesh.prop(target, "origin_centered", text=tr("Origin Centered"))
    if show_ctm and hasattr(target, "enable_ctm"):
        box_mesh.prop(target, "enable_ctm", text=tr("Connected Textures (CTM)"))
    box_mesh.prop(target, "enable_animated_textures", text=tr("Animated Textures"))
    if hasattr(target, "force"):
        box_mesh.prop(target, "force", text=tr("Force Unknown Blocks"))
    if show_host_fallback and hasattr(target, "allow_host_fallback"):
        box_mesh.prop(target, "allow_host_fallback", text=tr("Allow Host Fallback"))
