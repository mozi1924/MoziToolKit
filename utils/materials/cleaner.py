"""
Utility for cleaning empty and unused material slots on Blender mesh objects.
Ensures zero-copy or high-efficiency remapping of polygon material indices.
"""

from __future__ import annotations

import array
import logging
from typing import Any, Dict, List, Optional, Set

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

logger = logging.getLogger(__name__)


def compact_mesh_material_slots(
    mesh: Any,
    chunk_to_slot: Optional[Dict[int, int]] = None,
    target_materials: Optional[List[Any]] = None,
) -> int:
    """
    Safely reassigns mesh.materials to a compact list and remaps polygon material indices.
    
    If `chunk_to_slot` is provided, remaps polygon material_index according to the dict.
    If `target_materials` is provided, replaces mesh.materials with target_materials.
    Returns the number of removed empty/unused slots.
    """
    if not hasattr(mesh, "materials") or not hasattr(mesh, "polygons"):
        return 0

    old_slot_count = len(mesh.materials)
    num_polys = len(mesh.polygons)

    if target_materials is not None:
        mesh.materials.clear()
        for mat in target_materials:
            mesh.materials.append(mat)

    if chunk_to_slot is not None and num_polys > 0:
        if HAS_NUMPY and hasattr(mesh.polygons, "foreach_get") and hasattr(mesh.polygons, "foreach_set"):
            try:
                poly_mats = np.empty(num_polys, dtype=np.int32)
                mesh.polygons.foreach_get("material_index", poly_mats)
                remapped = np.array([chunk_to_slot.get(int(idx), 0) for idx in poly_mats], dtype=np.int32)
                mesh.polygons.foreach_set("material_index", remapped)
            except Exception as e:
                logger.debug("NumPy polygon material remapping failed: %s", e)
                for p in mesh.polygons:
                    p.material_index = chunk_to_slot.get(p.material_index, 0)
        else:
            for p in mesh.polygons:
                p.material_index = chunk_to_slot.get(p.material_index, 0)

    new_slot_count = len(mesh.materials)
    return max(0, old_slot_count - new_slot_count)



def clean_object_material_slots(
    obj: Any,
    remove_unused: bool = False,
) -> Dict[str, Any]:
    """
    Cleans empty (and optionally unused) material slots on a Blender mesh object.
    Preserves face material assignments by remapping polygon material_index.

    Args:
        obj: Blender Object of type MESH.
        remove_unused: If True, also removes slots that have materials but no faces assigned.

    Returns:
        Dict with keys:
            - success: bool
            - object_name: str
            - removed_slots: int
            - remaining_slots: int
            - message: str
    """
    if not obj or getattr(obj, "type", None) != "MESH":
        return {
            "success": False,
            "object_name": getattr(obj, "name", "None"),
            "removed_slots": 0,
            "remaining_slots": 0,
            "message": "Target object is not a valid mesh object.",
        }

    mesh = obj.data
    if not mesh or not hasattr(mesh, "materials") or len(mesh.materials) == 0:
        return {
            "success": True,
            "object_name": obj.name,
            "removed_slots": 0,
            "remaining_slots": 0,
            "message": "Object has no material slots.",
        }

    num_slots = len(mesh.materials)
    num_polys = len(mesh.polygons) if hasattr(mesh, "polygons") else 0

    # 1. Identify which slot indices are actually used by mesh faces
    used_indices: Set[int] = set()
    poly_mats: Optional[Any] = None

    if num_polys > 0:
        if HAS_NUMPY and hasattr(mesh.polygons, "foreach_get"):
            try:
                poly_mats = np.empty(num_polys, dtype=np.int32)
                mesh.polygons.foreach_get("material_index", poly_mats)
                used_indices = set(np.unique(poly_mats).tolist())
            except Exception:
                used_indices = {p.material_index for p in mesh.polygons}
                poly_mats = None
        else:
            used_indices = {p.material_index for p in mesh.polygons}

    # 2. Build list of valid, non-empty materials and old_to_new slot mapping
    new_materials: List[Any] = []
    old_to_new_map: Dict[int, int] = {}
    has_empty = False

    for old_idx, mat in enumerate(mesh.materials):
        if mat is None:
            has_empty = True
            continue

        if remove_unused and num_polys > 0 and old_idx not in used_indices:
            continue

        new_idx = len(new_materials)
        new_materials.append(mat)
        old_to_new_map[old_idx] = new_idx

    removed_count = num_slots - len(new_materials)
    if removed_count == 0 and not has_empty:
        return {
            "success": True,
            "object_name": obj.name,
            "removed_slots": 0,
            "remaining_slots": len(new_materials),
            "message": "No empty or unused material slots found.",
        }

    # 3. Reconstruct mesh.materials first so valid slots exist for remapping
    mesh.materials.clear()
    for mat in new_materials:
        mesh.materials.append(mat)

    # 4. Remap polygon material indices safely
    if num_polys > 0:
        if HAS_NUMPY and poly_mats is not None and hasattr(mesh.polygons, "foreach_set"):
            try:
                remapped_poly_mats = np.array(
                    [old_to_new_map.get(int(idx), 0) for idx in poly_mats],
                    dtype=np.int32,
                )
                mesh.polygons.foreach_set("material_index", remapped_poly_mats)
            except Exception as e:
                logger.debug("NumPy remap failed, falling back to iteration: %s", e)
                for p in mesh.polygons:
                    p.material_index = old_to_new_map.get(getattr(p, "material_index", 0), 0)
        else:
            for p in mesh.polygons:
                p.material_index = old_to_new_map.get(getattr(p, "material_index", 0), 0)

    return {

        "success": True,
        "object_name": obj.name,
        "removed_slots": removed_count,
        "remaining_slots": len(new_materials),
        "message": f"Cleaned {removed_count} material slot(s) for {obj.name}.",
    }


def clean_scene_material_slots(
    scene: Optional[Any] = None,
    selected_only: bool = False,
    remove_unused: bool = False,
) -> Dict[str, Any]:
    """
    Cleans empty and unused material slots across multiple mesh objects in a scene.
    """
    if not HAS_BPY:
        return {"success": False, "cleaned_objects": 0, "total_removed_slots": 0}

    target_scene = scene or (bpy.context.scene if bpy.context else None)
    if not target_scene:
        return {"success": False, "cleaned_objects": 0, "total_removed_slots": 0}

    if selected_only and bpy.context and hasattr(bpy.context, "selected_objects"):
        objects = [o for o in bpy.context.selected_objects if o.type == "MESH"]
    else:
        objects = [o for o in target_scene.objects if o.type == "MESH"]

    cleaned_objects = 0
    total_removed_slots = 0

    for obj in objects:
        res = clean_object_material_slots(obj, remove_unused=remove_unused)
        if res.get("success") and res.get("removed_slots", 0) > 0:
            cleaned_objects += 1
            total_removed_slots += res["removed_slots"]

    return {
        "success": True,
        "cleaned_objects": cleaned_objects,
        "total_removed_slots": total_removed_slots,
        "message": f"Cleaned {total_removed_slots} empty slot(s) across {cleaned_objects} mesh object(s).",
    }
