"""
Memory safety guards and pointer validation utilities for Blender DNA operations.

Prevents hard crashes / segfaults by defensively inspecting memory addresses
before passing them to native Rust kernels or ctypes calls.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("MoziToolKit.Bridge.DNA.Guard")

# Lower bound for valid user-space memory on 64-bit platforms (guards against null page).
MIN_VALID_POINTER: int = 4096

# Upper bound for 64-bit virtual address space.
MAX_VALID_POINTER: int = 0x00007FFFFFFFFFFF


def is_valid_pointer(ptr: Any) -> bool:
    """
    Checks if a given address is a plausible, non-null, aligned user-space pointer.
    Guards against null pointers (0), small integers, and non-integer types.
    """
    if not isinstance(ptr, int):
        return False
    return MIN_VALID_POINTER <= ptr <= MAX_VALID_POINTER


def check_pointer_alignment(ptr: int, align: int = 4) -> bool:
    """
    Verifies that the pointer is aligned to the given byte boundary (e.g., 4 bytes for float/int32).
    """
    if not is_valid_pointer(ptr):
        return False
    return (ptr % align) == 0


def safe_as_pointer(obj: Any, required_align: int = 4) -> Optional[int]:
    """
    Defensively retrieves and validates the raw memory pointer from an object.
    Supports objects providing `.as_pointer()` (e.g. Blender RNA datablocks / attribute items).

    Returns:
        The valid integer pointer address, or None if invalid or unavailable.
    """
    if obj is None:
        return None

    as_ptr_fn = getattr(obj, "as_pointer", None)
    if not callable(as_ptr_fn):
        return None

    try:
        raw_ptr = as_ptr_fn()
        if is_valid_pointer(raw_ptr) and check_pointer_alignment(raw_ptr, required_align):
            return raw_ptr
        logger.debug("safe_as_pointer rejected invalid/misaligned pointer: %s", raw_ptr)
        return None
    except Exception as e:
        logger.debug("safe_as_pointer encountered exception on %r: %s", obj, e)
        return None
