"""
Adaptive Pixel Split Operator for MoziToolKit.

High-performance pixel-density aware polygon subdivision backed strictly by Rust libmtk.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, IntVectorProperty

try:
    from ..bridge.subdivide import calculate_face_target_grid, calculate_pixel_grid_cut_factors
    from ..utils.mesh.core import (
        SELECTION_SCOPE_ITEMS,
        bmesh_context,
        poll_edit_mesh,
        poll_mesh_object,
    )
    from ..utils.mesh.subdivide import (
        cleanup_mesh_topology,
        slice_polygon_face_by_pixel_grid,
        subdivide_quad_face,
    )
    from ..utils.system.menu_registry import register_menu_item
except (ImportError, ValueError):
    from bridge.subdivide import calculate_face_target_grid, calculate_pixel_grid_cut_factors
    from utils.mesh.core import (
        SELECTION_SCOPE_ITEMS,
        bmesh_context,
        poll_edit_mesh,
        poll_mesh_object,
    )
    from utils.mesh.subdivide import (
        cleanup_mesh_topology,
        slice_polygon_face_by_pixel_grid,
        subdivide_quad_face,
    )
    from utils.system.menu_registry import register_menu_item


def _get_material_active_image_size(material: Any) -> Optional[Tuple[int, int]]:
    """Resolves active/primary image texture size from a Material node tree."""
    if not material or not getattr(material, "use_nodes", False) or not material.node_tree:
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


def _get_target_faces(bm, selection_scope: str, is_edit_mode: bool) -> List[Any]:
    """Filter target faces based on selection scope and mode."""
    if not is_edit_mode or selection_scope == "ALL":
        return list(bm.faces)

    selected = [f for f in bm.faces if f.select]
    if selection_scope == "SELECTED":
        return selected if selected else list(bm.faces)
    elif selection_scope == "LINKED":
        if not selected:
            return list(bm.faces)
        # Find connected island faces
        visited = set()
        queue = list(selected)
        while queue:
            f = queue.pop()
            if f in visited:
                continue
            visited.add(f)
            for edge in f.edges:
                for neighbor in edge.link_faces:
                    if neighbor not in visited:
                        queue.append(neighbor)
        return list(visited)

    return list(bm.faces)


@register_menu_item(views=["mesh"], label="Adaptive Pixel Split")
class MOZI_OT_adaptive_pixel_split(bpy.types.Operator):
    """Subdivide mesh quad faces according to texture pixel density backed by Rust libmtk"""

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

        is_edit_mode = (context.mode == "EDIT_MESH")
        total_in_faces = 0
        total_out_faces = 0

        for obj in target_objs:
            with bmesh_context(context, target_obj=obj, auto_update=True, flush_selection=True) as (target_obj, bm):
                # Ensure active UV layer exists
                uv_layer = bm.loops.layers.uv.active or (
                    bm.loops.layers.uv[0] if len(bm.loops.layers.uv) > 0 else bm.loops.layers.uv.verify()
                )

                # Ensure deform weights layer exists if object has vertex groups
                if len(target_obj.vertex_groups) > 0:
                    bm.verts.layers.deform.verify()

                target_faces = _get_target_faces(bm, self.selection_scope, is_edit_mode)
                if not target_faces:
                    continue

                total_in_faces += len(target_faces)
                def_res = (self.manual_resolution[0], self.manual_resolution[1])
                new_faces: List[Any] = []

                for face in target_faces:
                    if not face.is_valid or len(face.verts) != 4:
                        continue

                    # Extract face UV corner coordinates
                    uvs = [(loop[uv_layer].uv.x, loop[uv_layer].uv.y) for loop in face.loops]

                    # Resolve texture resolution
                    tex_w, tex_h = def_res
                    if self.auto_resolution and face.material_index < len(target_obj.material_slots):
                        slot = target_obj.material_slots[face.material_index]
                        mat_size = _get_material_active_image_size(slot.material)
                        if mat_size is not None:
                            tex_w, tex_h = mat_size

                    # Slices strictly along the 2D texture pixel grid lines (X = 1, 2... and Y = 1, 2...).
                    # For rotated/slanted UVs, the cuts on the 3D mesh naturally match the slanted orientation of the texture!
                    sub_quads = slice_polygon_face_by_pixel_grid(
                        bm,
                        face,
                        tex_w=tex_w,
                        tex_h=tex_h,
                        pixels_per_face=self.pixels_per_face,
                        max_subdivisions=self.max_subdivisions,
                        uv_layer=uv_layer,
                    )
                    new_faces.extend(sub_quads)

                # Clean up topology
                sub_verts = list(set(v for f in new_faces if f.is_valid for v in f.verts if v.is_valid))
                cleanup_mesh_topology(
                    bm,
                    verts=sub_verts if sub_verts else None,
                    weld_dist=self.weld_dist,
                    recalc_normals=True,
                )
                total_out_faces += len(new_faces)

        self.report(
            {"INFO"},
            f"Adaptive Pixel Split: {total_in_faces} target face(s) -> {total_out_faces} subdivided face(s) across {len(target_objs)} object(s).",
        )
        return {"FINISHED"}


OPERATOR_CLASSES = (MOZI_OT_adaptive_pixel_split,)

