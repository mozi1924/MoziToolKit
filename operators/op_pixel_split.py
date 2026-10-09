"""
Adaptive Pixel Split Operator for MoziToolKit.

High-performance pixel-density aware polygon subdivision backed strictly by Rust libmtk.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, IntVectorProperty

try:
    from ..bridge.mesh import extract_mesh_data, inject_mesh_data
    from ..bridge.subdivide import adaptive_pixel_split_mesh
    from ..utils.mesh.core import (
        SELECTION_SCOPE_ITEMS,
        poll_edit_mesh,
        poll_mesh_object,
    )
    from ..utils.system.menu_registry import register_menu_item
except (ImportError, ValueError):
    from bridge.mesh import extract_mesh_data, inject_mesh_data
    from bridge.subdivide import adaptive_pixel_split_mesh
    from utils.mesh.core import (
        SELECTION_SCOPE_ITEMS,
        poll_edit_mesh,
        poll_mesh_object,
    )
    from utils.system.menu_registry import register_menu_item

import numpy as np


def _get_material_active_image_size(material: Any) -> Optional[Tuple[int, int]]:
    """Resolves active/primary image texture size from a Material node tree."""
    if not material or not getattr(material, "node_tree", None):
        return None

    nodes = material.node_tree.nodes

    # 1. Active node in node editor (Blender's default active image texture)
    if nodes.active and nodes.active.type == "TEX_IMAGE" and nodes.active.image:
        img = nodes.active.image
        if img.size[0] > 0 and img.size[1] > 0:
            return (img.size[0], img.size[1])

    # 2. Principled BSDF Base Color connection
    for node in nodes:
        if node.type == "BSDF_PRINCIPLED":
            base_col_input = node.inputs.get("Base Color")
            if base_col_input and base_col_input.is_linked:
                for link in base_col_input.links:
                    from_node = link.from_node
                    if from_node.type == "TEX_IMAGE" and from_node.image:
                        img = from_node.image
                        if img.size[0] > 0 and img.size[1] > 0:
                            return (img.size[0], img.size[1])

    # 3. Any image texture node with valid image
    for node in nodes:
        if node.type == "TEX_IMAGE" and node.image:
            img = node.image
            if img.size[0] > 0 and img.size[1] > 0:
                return (img.size[0], img.size[1])

    return None


@register_menu_item(views=["mesh"], label="Adaptive Pixel Split")
class MOZI_OT_adaptive_pixel_split(bpy.types.Operator):
    """Subdivide mesh quad faces according to texture pixel density backed strictly by Rust libmtk"""

    bl_idname = "mozi.adaptive_pixel_split"
    bl_label = "Adaptive Pixel Split"
    bl_options = {"REGISTER", "UNDO"}

    pixels_per_face: FloatProperty(
        name="Pixels Per Face",
        description="Target number of texture pixels per polygon edge (1.0 = 1 face per pixel)",
        default=1.0,
        min=0.1,
        max=64.0,
    )

    max_subdivisions: IntProperty(
        name="Max Subdivisions",
        description="Maximum subdivisions along each axis to prevent vertex explosion",
        default=64,
        min=1,
        max=256,
    )

    auto_resolution: BoolProperty(
        name="Auto Texture Resolution",
        description="Automatically inspect material active image texture sizes",
        default=True,
    )

    manual_resolution: IntVectorProperty(
        name="Manual Resolution",
        description="Fallback texture dimensions (Width, Height)",
        default=(16, 16),
        size=2,
        min=1,
    )

    selection_scope: EnumProperty(
        name="Selection Scope",
        description="Faces to process",
        items=SELECTION_SCOPE_ITEMS,
        default="SELECTED",
    )

    weld_dist: FloatProperty(
        name="Weld Distance",
        description="Distance threshold to weld adjacent subdivided boundary vertices",
        default=1e-4,
        min=0.0,
        max=1e-2,
    )

    @classmethod
    def poll(cls, context):
        return poll_edit_mesh(context) or poll_mesh_object(context)

    def execute(self, context):
        target_objs = [o for o in context.selected_objects if o and o.type == "MESH"]
        if not target_objs and context.active_object and context.active_object.type == "MESH":
            target_objs = [context.active_object]

        if not target_objs:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        was_edit_mode = (context.mode == "EDIT_MESH")
        if was_edit_mode:
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass

        total_in_faces = 0
        total_out_faces = 0
        def_res = (int(self.manual_resolution[0]), int(self.manual_resolution[1]))

        try:
            for obj in target_objs:
                mesh = obj.data
                num_polys = len(mesh.polygons)
                if num_polys == 0:
                    continue

                total_in_faces += num_polys

                # 1. Determine face selection mask
                if was_edit_mode and self.selection_scope in ("SELECTED", "LINKED"):
                    sel_mask = np.empty(num_polys, dtype=bool)
                    mesh.polygons.foreach_get("select", sel_mask)
                    if not np.any(sel_mask):
                        sel_mask.fill(True)
                else:
                    sel_mask = np.ones(num_polys, dtype=bool)

                # 2. Resolve per-material slot image dimensions
                slot_resolutions: List[Optional[Tuple[int, int]]] = []
                for slot in obj.material_slots:
                    res = _get_material_active_image_size(slot.material) if self.auto_resolution else None
                    slot_resolutions.append(res if res is not None else def_res)

                poly_mats = np.empty(num_polys, dtype=np.int32)
                mesh.polygons.foreach_get("material_index", poly_mats)

                face_resolutions: List[Optional[Tuple[int, int]]] = []
                num_slots = len(slot_resolutions)
                for f_idx in range(num_polys):
                    if not sel_mask[f_idx]:
                        face_resolutions.append(None)  # Rust core skips subdivision, keeping original quad
                    else:
                        m_idx = poly_mats[f_idx]
                        if 0 <= m_idx < num_slots:
                            face_resolutions.append(slot_resolutions[m_idx])
                        else:
                            face_resolutions.append(def_res)

                # 3. Extract MeshData via accelerated zero-copy bridge
                mesh_data = extract_mesh_data(mesh)

                # 4. End-to-end adaptive subdivision and attribute interpolation in Rust
                subdivided = adaptive_pixel_split_mesh(
                    mesh_data,
                    face_resolutions=face_resolutions,
                    default_resolution=def_res,
                    pixels_per_face=float(self.pixels_per_face),
                    max_subdivisions=int(self.max_subdivisions),
                    weld_dist=float(self.weld_dist),
                )

                # 5. Inject back into Blender mesh with vectorized batch buffers
                inject_mesh_data(mesh, subdivided, update_topology=True, update_normals=True)
                mesh.update()
                total_out_faces += getattr(subdivided, "face_count", len(mesh.polygons))

        finally:
            if was_edit_mode:
                try:
                    bpy.ops.object.mode_set(mode="EDIT")
                except Exception:
                    pass

        self.report(
            {"INFO"},
            f"Adaptive Pixel Split: {total_in_faces} face(s) -> {total_out_faces} subdivided face(s) across {len(target_objs)} object(s).",
        )
        return {"FINISHED"}


OPERATOR_CLASSES = (MOZI_OT_adaptive_pixel_split,)

