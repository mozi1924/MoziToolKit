import bpy
import numpy as np
from ...utils.mesh import (
    SELECTION_ACTION_ITEMS,
    SELECTION_SCOPE_ITEMS,
    apply_selection,
    bmesh_context,
    get_target_faces,
    poll_edit_mesh,
    set_select_mode,
)
from ...utils.uv import get_image_from_face
from ...utils.menu_config import register_menu_item


@register_menu_item(views=["mesh", "uv"])
class MOZI_OT_select_transparent_faces(bpy.types.Operator):
    """Select mesh faces mapped to transparent texture pixels"""

    bl_idname = "mozi.select_transparent_faces"
    bl_label = "Select Transparent Faces"
    bl_options = {"REGISTER", "UNDO"}

    alpha_threshold: bpy.props.FloatProperty(
        name="Alpha Threshold",
        description="Alpha threshold to consider transparent (<= threshold)",
        default=0.01,
        min=0.0,
        max=1.0,
        precision=3,
    )

    sample_mode: bpy.props.EnumProperty(
        name="Sample Mode",
        description="Sampling strategy for face transparency",
        items=[
            ("CENTER", "Center", "Sample alpha at the UV geometric center of the face"),
            ("ALL_CORNERS", "All Corners & Center", "Check corners and center (all must be transparent)"),
            ("AVERAGE", "Average", "Average alpha of face UV bounds/corners"),
        ],
        default="CENTER",
    )

    selection_mode: bpy.props.EnumProperty(
        name="Selection Action",
        description="How to modify the current face selection",
        items=SELECTION_ACTION_ITEMS,
        default="SET",
    )

    selection_scope: bpy.props.EnumProperty(
        name="Selection Scope",
        description="Filter which faces to check for transparency",
        items=SELECTION_SCOPE_ITEMS,
        default="ALL",
    )

    @classmethod
    def poll(cls, context):
        return poll_edit_mesh(context)

    def execute(self, context):
        # Switch to Face Select Mode to prevent accidental vertex/edge selection artifacts
        set_select_mode(context, "FACE")

        with bmesh_context(context, flush_selection=True) as (obj, bm):
            uv_layer = bm.loops.layers.uv.verify()

            # Cache pixel buffers for images to optimize sampling speed
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
                    return 1.0  # Opaque fallback if no alpha channel

                arr, w, h, ch = cached
                x = int(u * w) % w
                y = int(v * h) % h
                return float(arr[y, x, 3])

            transparent_faces = []
            faces_to_check = get_target_faces(bm, self.selection_scope)

            for face in faces_to_check:
                img = get_image_from_face(face, obj, context)
                if not img:
                    continue

                uvs = [loop[uv_layer].uv for loop in face.loops]
                if not uvs:
                    continue

                u_center = sum(uv.x for uv in uvs) / len(uvs)
                v_center = sum(uv.y for uv in uvs) / len(uvs)

                is_transparent = False

                if self.sample_mode == "CENTER":
                    alpha = sample_alpha(img, u_center, v_center)
                    is_transparent = alpha <= self.alpha_threshold
                elif self.sample_mode == "ALL_CORNERS":
                    alphas = [sample_alpha(img, uv.x, uv.y) for uv in uvs]
                    alphas.append(sample_alpha(img, u_center, v_center))
                    is_transparent = all(a <= self.alpha_threshold for a in alphas)
                elif self.sample_mode == "AVERAGE":
                    alphas = [sample_alpha(img, uv.x, uv.y) for uv in uvs]
                    alphas.append(sample_alpha(img, u_center, v_center))
                    avg_alpha = sum(alphas) / len(alphas)
                    is_transparent = avg_alpha <= self.alpha_threshold

                if is_transparent:
                    transparent_faces.append(face)

            # Apply selection modification (SET, ADD, SUBTRACT)
            apply_selection(bm.faces, transparent_faces, self.selection_mode)

        self.report({"INFO"}, f"Selected {len(transparent_faces)} transparent face(s)")
        return {"FINISHED"}
