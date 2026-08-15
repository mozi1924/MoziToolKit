"""
Select Transparent Faces Pipeline Step
"""

import bpy
import numpy as np
from ..context import PipelineContext
from ..step import PipelineStep, StepResult

try:
    from ...utils.mesh import (
        apply_selection,
        bmesh_context,
        get_target_faces,
        poll_edit_mesh,
        set_select_mode,
        get_image_from_face,
    )
except (ImportError, ValueError):
    from utils.mesh import (
        apply_selection,
        bmesh_context,
        get_target_faces,
        poll_edit_mesh,
        set_select_mode,
        get_image_from_face,
    )


class SelectTransparentFacesStep(PipelineStep):
    name = "Select Transparent Faces"
    description = "Select mesh faces mapped to transparent texture pixels"

    def execute(self, ctx: PipelineContext) -> StepResult:
        if not poll_edit_mesh(ctx.context):
            return StepResult.cancelled("Must be in Edit Mode with a Mesh object active.")

        alpha_threshold = self.get_param(ctx, "alpha_threshold", 0.01)
        sample_mode = self.get_param(ctx, "sample_mode", "CENTER")
        selection_mode = self.get_param(ctx, "selection_mode", "SET")
        selection_scope = self.get_param(ctx, "selection_scope", "ALL")

        set_select_mode(ctx.context, "FACE")

        transparent_faces_count = 0
        with bmesh_context(ctx.context, flush_selection=True) as (obj, bm):
            uv_layer = bm.loops.layers.uv.verify()
            image_pixels_cache = {}

            def sample_alpha(image, u, v):
                if image not in image_pixels_cache:
                    w, h = image.size[0], image.size[1]
                    ch = image.channels
                    if w <= 0 or h <= 0 or ch < 4:
                        image_pixels_cache[image] = None
                    else:
                        arr = np.array(image.pixels, dtype=np.float32).reshape((h, w, ch))
                        image_pixels_cache[image] = (arr, w, h, ch)

                cached = image_pixels_cache[image]
                if cached is None:
                    return 1.0

                arr, w, h, ch = cached
                x = int(u * w) % w
                y = int(v * h) % h
                return float(arr[y, x, 3])

            transparent_faces = []
            faces_to_check = get_target_faces(bm, selection_scope)

            for face in faces_to_check:
                img = get_image_from_face(face, obj, ctx.context)
                if not img:
                    continue

                uvs = [loop[uv_layer].uv for loop in face.loops]
                if not uvs:
                    continue

                u_center = sum(uv.x for uv in uvs) / len(uvs)
                v_center = sum(uv.y for uv in uvs) / len(uvs)

                is_transparent = False

                if sample_mode == "CENTER":
                    alpha = sample_alpha(img, u_center, v_center)
                    is_transparent = alpha <= alpha_threshold
                elif sample_mode == "ALL_CORNERS":
                    alphas = [sample_alpha(img, uv.x, uv.y) for uv in uvs]
                    alphas.append(sample_alpha(img, u_center, v_center))
                    is_transparent = all(a <= alpha_threshold for a in alphas)
                elif sample_mode == "AVERAGE":
                    alphas = [sample_alpha(img, uv.x, uv.y) for uv in uvs]
                    alphas.append(sample_alpha(img, u_center, v_center))
                    avg_alpha = sum(alphas) / len(alphas)
                    is_transparent = avg_alpha <= alpha_threshold

                if is_transparent:
                    transparent_faces.append(face)

            transparent_faces_count = len(transparent_faces)
            apply_selection(bm.faces, transparent_faces, selection_mode)

        msg = f"Selected {transparent_faces_count} transparent face(s)"
        ctx.set_data("transparent_faces_count", transparent_faces_count)
        return StepResult.success(msg, {"transparent_faces_count": transparent_faces_count})
