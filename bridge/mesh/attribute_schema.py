"""
Canonical mesh attribute schema consumed by the MoziToolKit glue layer.

The native core (`mtk-core::attributes`) is the single source of truth. The
checked-in `_attribute_schema_generated.py` mirror is produced by
`tools/sync_attribute_schema.py`; `tests/test_attribute_schema.py` verifies it
still matches the live native extension.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, NamedTuple, Optional

from . import _attribute_schema_generated as _generated

SCHEMA_HASH: str = _generated.SCHEMA_HASH


class AttributeSpec(NamedTuple):
    """One canonical mesh attribute declaration."""

    name: str
    domain: str
    data_type: str
    role: str


ATTRIBUTE_SPECS: Dict[str, AttributeSpec] = {
    name: AttributeSpec(name, domain, data_type, role)
    for name, domain, data_type, role in _generated.ATTRIBUTE_SPECS
}

ACTIVE_ATTRIBUTE_NAMES: FrozenSet[str] = frozenset(ATTRIBUTE_SPECS)
MATERIAL_ATTRIBUTE_NAMES: FrozenSet[str] = frozenset(
    name for name, spec in ATTRIBUTE_SPECS.items() if spec.role == "material"
)
METADATA_ATTRIBUTE_NAMES: FrozenSet[str] = frozenset(
    name for name, spec in ATTRIBUTE_SPECS.items() if spec.role == "metadata"
)
RETIRED_ATTRIBUTE_NAMES: FrozenSet[str] = _generated.RETIRED_ATTRIBUTE_NAMES


def _validate_schema() -> None:
    if not ACTIVE_ATTRIBUTE_NAMES:
        raise RuntimeError("Generated mesh attribute schema is empty")
    overlap = ACTIVE_ATTRIBUTE_NAMES & RETIRED_ATTRIBUTE_NAMES
    if overlap:
        raise RuntimeError(
            "Mesh attribute schema declares names as both active and retired: "
            + ", ".join(sorted(overlap))
        )
    unknown_roles = {
        spec.role for spec in ATTRIBUTE_SPECS.values() if spec.role not in ("material", "metadata")
    }
    if unknown_roles:
        raise RuntimeError(f"Unknown attribute role(s): {sorted(unknown_roles)}")


_validate_schema()


def attribute_spec(name: str) -> Optional[AttributeSpec]:
    """Returns the canonical spec for an active attribute, or None."""
    return ATTRIBUTE_SPECS.get(name)


def is_active(name: str) -> bool:
    """Whether the native core or host may write this attribute."""
    return name in ATTRIBUTE_SPECS


def is_retired(name: str) -> bool:
    """Whether this attribute must be purged and never written again."""
    return name in RETIRED_ATTRIBUTE_NAMES


# Re-export generated ATTR_* constants so callers have one import site.
for _name, _value in vars(_generated).items():
    if _name.startswith("ATTR_"):
        globals()[_name] = _value

# Retired legacy attribute constants kept for cleanup routines
ATTR_SOURCE_TEXTURE_KEY: str = "mtk_source_texture_key"

__all__ = [
    "SCHEMA_HASH",
    "AttributeSpec",
    "ATTRIBUTE_SPECS",
    "ACTIVE_ATTRIBUTE_NAMES",
    "MATERIAL_ATTRIBUTE_NAMES",
    "METADATA_ATTRIBUTE_NAMES",
    "RETIRED_ATTRIBUTE_NAMES",
    "attribute_spec",
    "is_active",
    "is_retired",
] + [name for name in globals() if name.startswith("ATTR_")]
