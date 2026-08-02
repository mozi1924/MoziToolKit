import bpy


def calculate_face_uv_area(face, uv_layer) -> float:
    """Calculate 2D signed area of a face in UV space using Shoelace formula."""
    loops = face.loops
    if len(loops) < 3:
        return 0.0
    area = 0.0
    n = len(loops)
    for i in range(n):
        uv1 = loops[i][uv_layer].uv
        uv2 = loops[(i + 1) % n][uv_layer].uv
        area += (uv1.x * uv2.y - uv2.x * uv1.y)
    return 0.5 * abs(area)


def is_face_uv_collapsed(
    face, uv_layer, area_threshold: float = 1e-6, dist_threshold: float = 1e-4
) -> bool:
    """Check if face UVs are collapsed to a point, line segment, or near zero 2D area."""
    if len(face.loops) < 3:
        return True
    if calculate_face_uv_area(face, uv_layer) < area_threshold:
        return True
    uvs = [l[uv_layer].uv for l in face.loops]
    max_dist_sq = 0.0
    for i in range(len(uvs)):
        for j in range(i + 1, len(uvs)):
            dist_sq = (uvs[i] - uvs[j]).length_squared
            if dist_sq > max_dist_sq:
                max_dist_sq = dist_sq
    return max_dist_sq < (dist_threshold * dist_threshold)


def get_active_texture_pixel_step(obj=None) -> float:
    """Retrieve UV step corresponding to 1 pixel based on active object's image texture."""
    p_step = 1.0 / 64.0
    try:
        active_obj = obj or bpy.context.active_object
        if active_obj and active_obj.active_material and active_obj.active_material.use_nodes:
            for node in active_obj.active_material.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image and node.image.size[0] > 0:
                    p_step = 1.0 / float(node.image.size[0])
                    break
    except Exception:
        pass
    return p_step
