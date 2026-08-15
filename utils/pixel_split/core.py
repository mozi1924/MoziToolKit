import bmesh
from typing import Dict, List, Optional
from .types import SplitConfig
from .uv_analyzer import get_texture_resolution_for_face, calculate_face_target_grid
from .subdivider import subdivide_quad_face
from ..mesh import bmesh_context, get_target_faces, cleanup_mesh_topology


def process_adaptive_pixel_split(context, config: Optional[SplitConfig] = None, target_obj=None) -> Dict[str, int]:
    """Orchestrate adaptive pixel split pipeline on active or specified edit mesh object.

    :param context: Blender context
    :param config: SplitConfig dataclass instance
    :param target_obj: Optional target mesh object
    :return: Dictionary containing stats: {'initial_faces': int, 'final_faces': int}
    """
    config = config or SplitConfig()

    with bmesh_context(context, target_obj=target_obj, auto_update=True, flush_selection=True) as (obj, bm):

        # Ensure deform weights layer exists if object has vertex groups
        if len(obj.vertex_groups) > 0:
            bm.verts.layers.deform.verify()

        uv_layer = bm.loops.layers.uv.verify()

        # Step 1: Select target faces according to selection scope ('ALL', 'SELECTED', 'LINKED')
        target_faces = get_target_faces(bm, config.selection_scope)

        if not target_faces:
            return {"initial_faces": 0, "final_faces": len(bm.faces)}

        initial_count = len(target_faces)

        # Step 2: Subdivide base quad faces according to texture pixel density
        new_faces: List[bmesh.types.BMFace] = []
        for face in target_faces:
            if not face.is_valid:
                continue

            # Determine texture resolution
            if config.auto_resolution:
                tex_w, tex_h = get_texture_resolution_for_face(face, obj, context, config.manual_resolution, uv_layer=uv_layer)
            else:
                tex_w, tex_h = config.manual_resolution

            # Calculate target grid dimensions
            grid = calculate_face_target_grid(
                face,
                uv_layer,
                tex_w=tex_w,
                tex_h=tex_h,
                pixels_per_face=config.pixels_per_face,
                max_subdivisions=config.max_subdivisions,
            )

            # Perform grid subdivision
            created_sub_faces = subdivide_quad_face(bm, face, uv_layer, grid)
            new_faces.extend(created_sub_faces)

        # Step 3: Clean up topology (weld boundary duplicate vertices, delete loose edges/verts, recalc normals)
        sub_verts = list(set(v for f in new_faces if f.is_valid for v in f.verts if v.is_valid))
        cleanup_mesh_topology(bm, verts=sub_verts, weld_dist=0.0001, recalc_normals=True)

        return {
            "initial_faces": initial_count,
            "final_faces": len(bm.faces),
            "generated_faces": len(new_faces),
        }
