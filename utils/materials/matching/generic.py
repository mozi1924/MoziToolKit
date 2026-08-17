"""
Generic standard format adapter (fallback for generic materials, image names, and literal keys).
"""

from __future__ import annotations

import bpy
from .base import ImporterAdapter, base_texture_candidates


def generic_texture_candidates(mat: bpy.types.Material) -> tuple[str, list[str]]:
    """Literal image and material-name matching with standard Minecraft category fallbacks."""
    namespace, base_cands = base_texture_candidates(mat)
    candidates = list(base_cands)
    for cand in base_cands:
        if "/" not in cand and not cand.startswith("atlas_chunk_"):
            candidates.append(f"block/{cand}")
            candidates.append(f"entity/{cand}")
            candidates.append(f"item/{cand}")
    return namespace, list(dict.fromkeys(candidates))


class GenericAdapter(ImporterAdapter):
    """Standard generic adapter matching literal image and material names."""

    identifier = "generic"
    description = "Literal image and material-name matching"

    def detect(self, mat: bpy.types.Material | None) -> bool:
        return True

    def extract_keys(self, mat: bpy.types.Material) -> tuple[str, list[str]]:
        return generic_texture_candidates(mat)
