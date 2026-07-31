import bmesh
from typing import Dict, List, Optional
from .types import SplitConfig
from .uv_analyzer import get_texture_resolution_for_face, calculate_face_target_grid
from .dissolver import dissolve_pre_split_edges
from .subdivider import subdivide_quad_face
from ..mesh import bmesh_context


def process_adaptive_pixel_split(context, config: Optional[SplitConfig] = None) -> Dict[str, int]:
    """Orchestrate adaptive pixel split pipeline on active edit mesh.

    :param context: Blender context
    :param config: SplitConfig dataclass instance
    :return: Dictionary containing stats: {'initial_faces': int, 'final_faces': int}
    """
    config = config or SplitConfig()

    with bmesh_context(context, auto_update=True, flush_selection=True) as (obj, bm):
        # Ensure deform weights layer exists if object has vertex groups
        if len(obj.vertex_groups) > 0:
            bm.verts.layers.deform.verify()

        uv_layer = bm.loops.layers.uv.verify()


        # Step 1: Select target faces
        if config.only_selected:
            target_faces = [f for f in bm.faces if f.select]
        else:
            target_faces = list(bm.faces)

        if not target_faces:
            return {"initial_faces": 0, "final_faces": len(bm.faces)}

        initial_count = len(target_faces)

        # Step 2: Dissolve pre-split edges if configured
        if config.dissolve_pre_split:
            dissolve_pre_split_edges(bm, target_faces)
            bm.faces.ensure_lookup_table()
            if config.only_selected:
                target_faces = [f for f in bm.faces if f.select and f.is_valid]
            else:
                target_faces = [f for f in bm.faces if f.is_valid]

        uv_layer = bm.loops.layers.uv.verify()



        # Step 3: Subdivide base quad faces according to texture pixel density
        new_faces: List[bmesh.types.BMFace] = []
        for face in target_faces:
            if not face.is_valid:
                continue

            # Determine texture resolution
            if config.auto_resolution:
                tex_w, tex_h = get_texture_resolution_for_face(face, obj, context, config.manual_resolution)
            else:
                tex_w, tex_h = config.manual_resolution

            # Calculate target grid dimensions
            grid = calculate_face_target_grid(
                face,
                uv_layer,
                tex_w=tex_w,
                tex_h=tex_h,
                pixels_per_face=config.pixels_per_face,
            )

            # Perform grid subdivision
            created_sub_faces = subdivide_quad_face(bm, face, uv_layer, grid)
            new_faces.extend(created_sub_faces)

        # Step 4: Recalculate face normals and update BMesh lookup tables
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.faces.ensure_lookup_table()

        return {
            "initial_faces": initial_count,
            "final_faces": len(bm.faces),
            "generated_faces": len(new_faces),
        }
