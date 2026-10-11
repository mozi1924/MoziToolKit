"""
Forward-compatibility DNA Resolver for Blender 5.x and future releases.

Extends DnaResolverV42 with forward-compatibility adaptations for upcoming Blender DNA changes.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .v4_2 import DnaResolverV42

logger = logging.getLogger("MoziToolKit.Bridge.DNA.V50")


class DnaResolverV50(DnaResolverV42):
    """Blender 5.x+ Forward-compatible DNA & Attribute Resolver."""

    def resolve_positions_ptr(
        self, mesh: Any, expected_count: Optional[int] = None
    ) -> Optional[int]:
        # Blender 5.x moves exclusively to bke::AttributeAccessor without MVert
        if mesh is None or not hasattr(mesh, "attributes"):
            return None

        pos_attr = mesh.attributes.get("position")
        if pos_attr is not None:
            if expected_count is None or len(pos_attr.data) == expected_count:
                return self.resolve_attribute_ptr(pos_attr)

        return None
