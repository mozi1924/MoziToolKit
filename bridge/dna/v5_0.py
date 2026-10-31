"""
Forward-compatibility DNA Resolver for Blender 5.x and future releases.
"""

from __future__ import annotations

from .v4_2 import DnaResolverV42

# Modern DNA resolver is unified across Blender 4.2+ and 5.x+ (AttributeAccessor based).
DnaResolverV50 = DnaResolverV42
