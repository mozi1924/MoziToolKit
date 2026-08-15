"""
Generic standard format adapter (fallback for generic materials, image names, and literal keys).
"""

from __future__ import annotations

import bpy
from .base import ImporterAdapter, base_texture_candidates


def generic_texture_candidates(mat: bpy.types.Material) -> tuple[str, list[str]]:
    """Literal image and material-name matching."""
    return base_texture_candidates(mat)


class GenericAdapter(ImporterAdapter):
    """Standard generic adapter matching literal image and material names."""

    identifier = "generic"
    description = "Literal image and material-name matching"

    def detect(self, mat: bpy.types.Material | None) -> bool:
        return True

    def extract_keys(self, mat: bpy.types.Material) -> tuple[str, list[str]]:
        return generic_texture_candidates(mat)
