"""
Blender Mesh Generator for BakedModel instances.
Constructs exact polygon meshes and loop UV layers for arbitrary non-full and complex blocks.
"""

from __future__ import annotations
from typing import Optional, Tuple
import bpy
import bmesh
from mathutils import Vector

from .types import BakedModel, BakedFace, BakedElement


_DIRECTION_NORMALS = {
    "east": (1.0, 0.0, 0.0), "west": (-1.0, 0.0, 0.0),
    "up": (0.0, 1.0, 0.0), "down": (0.0, -1.0, 0.0),
    "south": (0.0, 0.0, 1.0), "north": (0.0, 0.0, -1.0),
}
_EPSILON = 1e-6


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _subtract_rect(rect, cut):
    """Subtract an axis-aligned 2D rectangle, returning up to four rectangles."""
    a0, a1, b0, b1 = rect
    ca0, ca1, cb0, cb1 = cut
    ia0, ia1 = max(a0, ca0), min(a1, ca1)
    ib0, ib1 = max(b0, cb0), min(b1, cb1)
    if ia1 - ia0 <= _EPSILON or ib1 - ib0 <= _EPSILON:
        return [rect]
    candidates = [
        (a0, ia0, b0, b1), (ia1, a1, b0, b1),
        (ia0, ia1, b0, ib0), (ia0, ia1, ib1, b1),
    ]
    return [r for r in candidates if r[1] - r[0] > _EPSILON and r[3] - r[2] > _EPSILON]


def _face_pieces_excluding_hidden_volume(face: BakedFace, bounds):
    """Split an axis-aligned face around solid cuboids covering its outside.

    Block-model JSON commonly composes a shape from overlapping cuboids.  The
    source files can therefore contain a face that lies *inside* a neighbouring
    cuboid (stairs are the canonical example).  Minecraft's baked renderer
    discards that covered region.  Blender needs the equivalent operation to
    avoid internal, apparently doubled faces in the extracted white model.
    """
    vertices = face.vertices
    if len(vertices) != 4 or face.direction not in _DIRECTION_NORMALS:
        return [(vertices, face.uvs)]

    spans = [max(v[i] for v in vertices) - min(v[i] for v in vertices) for i in range(3)]
    fixed_axes = [i for i, span in enumerate(spans) if span <= _EPSILON]
    if len(fixed_axes) != 1:
        # Diagonal / locally rotated elements need their original quad; their
        # AABB would be too coarse to cull safely.
        return [(vertices, face.uvs)]

    fixed = fixed_axes[0]
    axes = [i for i in range(3) if i != fixed]
    a_axis, b_axis = axes
    plane = vertices[0][fixed]
    a0, a1 = min(v[a_axis] for v in vertices), max(v[a_axis] for v in vertices)
    b0, b1 = min(v[b_axis] for v in vertices), max(v[b_axis] for v in vertices)
    if a1 - a0 <= _EPSILON or b1 - b0 <= _EPSILON:
        return [(vertices, face.uvs)]

    normal = _DIRECTION_NORMALS[face.direction]
    outside = plane + normal[fixed] * _EPSILON
    pieces = [(a0, a1, b0, b1)]
    for mins, maxs in bounds:
        # Only subtract where the face's outward side enters another cuboid.
        if not (mins[fixed] <= outside and outside < maxs[fixed] - _EPSILON):
            continue
        cut = (mins[a_axis], maxs[a_axis], mins[b_axis], maxs[b_axis])
        pieces = [remainder for piece in pieces for remainder in _subtract_rect(piece, cut)]
        if not pieces:
            return []

    # Map source UVs to the physical face rectangle, then interpolate exact UV
    # values for each clipped piece.  This preserves rotations and partial UVs.
    corner_uvs = {}
    for vertex, uv in zip(vertices, face.uvs):
        sa = round((vertex[a_axis] - a0) / (a1 - a0))
        sb = round((vertex[b_axis] - b0) / (b1 - b0))
        corner_uvs[(sa, sb)] = uv
    if len(corner_uvs) != 4:
        return [(vertices, face.uvs)]

    original_normal = _cross(
        tuple(vertices[1][i] - vertices[0][i] for i in range(3)),
        tuple(vertices[2][i] - vertices[0][i] for i in range(3)),
    )

    def make_vertex(a, b):
        values = [0.0, 0.0, 0.0]
        values[fixed], values[a_axis], values[b_axis] = plane, a, b
        return tuple(values)

    def interpolate_uv(a, b):
        sa = (a - a0) / (a1 - a0)
        sb = (b - b0) / (b1 - b0)
        weights = ((0, 0, (1 - sa) * (1 - sb)), (1, 0, sa * (1 - sb)),
                   (1, 1, sa * sb), (0, 1, (1 - sa) * sb))
        return tuple(
            sum(corner_uvs[(key_a, key_b)][index] * weight for key_a, key_b, weight in weights)
            for index in range(2)
        )

    result = []
    for pa0, pa1, pb0, pb1 in pieces:
        corners = [(pa0, pb0), (pa1, pb0), (pa1, pb1), (pa0, pb1)]
        piece_vertices = [make_vertex(a, b) for a, b in corners]
        piece_uvs = [interpolate_uv(a, b) for a, b in corners]
        piece_normal = _cross(
            tuple(piece_vertices[1][i] - piece_vertices[0][i] for i in range(3)),
            tuple(piece_vertices[2][i] - piece_vertices[0][i] for i in range(3)),
        )
        if _dot(piece_normal, original_normal) < 0:
            piece_vertices.reverse()
            piece_uvs.reverse()
        result.append((tuple(piece_vertices), tuple(piece_uvs)))
    return result


def _element_bounds(elements):
    """Return world-space AABBs for axis-aligned baked elements only."""
    result = []
    for element in elements:
        vertices = [vertex for face in element.faces.values() for vertex in face.vertices]
        if not vertices:
            continue
        mins = tuple(min(v[axis] for v in vertices) for axis in range(3))
        maxs = tuple(max(v[axis] for v in vertices) for axis in range(3))
        if all(maxs[axis] - mins[axis] > _EPSILON for axis in range(3)):
            result.append((mins, maxs))
    return result


def mc_pos_to_blender(mc_pos: Tuple[float, float, float], origin_centered: bool = True) -> Tuple[float, float, float]:
    """
    Convert Minecraft local coordinate [0..1] to Blender space.
    MC: +X = East, +Y = Up, +Z = South.
    Blender: +X = East, +Y = North (MC -Z), +Z = Up (MC +Y).
    """
    x, y, z = mc_pos
    if origin_centered:
        # Center in [-0.5, 0.5]
        bx = x - 0.5
        by = -(z - 0.5)  # MC North (-Z) is Blender +Y
        bz = y - 0.5
    else:
        bx = x
        by = 1.0 - z
        bz = y
    return (bx, by, bz)


def build_blender_mesh_from_baked_model(
    baked_model: BakedModel,
    mesh_name: str = "MC_Baked_Block",
    origin_centered: bool = True,
    material_map: Optional[dict[str, bpy.types.Material]] = None
) -> bpy.types.Mesh:
    """
    Creates a new Blender Mesh datablock from a BakedModel.
    Populates all element quads and accurate loop UVs.
    """
    mesh = bpy.data.meshes.new(mesh_name)
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    element_bounds = _element_bounds(baked_model.elements)

    mat_slot_indices: dict[str, int] = {}
    if material_map:
        for tex_name, mat in material_map.items():
            if mat.name not in mesh.materials:
                mat_slot_indices[tex_name] = len(mesh.materials)
                mesh.materials.append(mat)

    for element in baked_model.elements:
        for face_dir, baked_face in element.faces.items():
            if not baked_face.vertices or len(baked_face.vertices) < 4:
                continue

            for mc_vertices, face_uvs in _face_pieces_excluding_hidden_volume(baked_face, element_bounds):
                bl_verts_coords = [mc_pos_to_blender(v, origin_centered) for v in mc_vertices]
                bm_verts = [bm.verts.new(v) for v in bl_verts_coords]
                try:
                    bm_face = bm.faces.new(bm_verts)
                except ValueError:
                    continue

                if len(face_uvs) == 4:
                    for i, loop in enumerate(bm_face.loops):
                        u, v = face_uvs[i]
                        loop[uv_layer].uv = Vector((u, 1.0 - v))

                if baked_face.texture in mat_slot_indices:
                    bm_face.material_index = mat_slot_indices[baked_face.texture]

    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=_EPSILON)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def create_block_object(
    baked_model: BakedModel,
    object_name: str = "MC_Block",
    location: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    collection: Optional[bpy.types.Collection] = None,
    material_map: Optional[dict[str, bpy.types.Material]] = None
) -> bpy.types.Object:
    """
    Creates a Blender Object from a BakedModel and links it into the active or specified Collection.
    """
    mesh = build_blender_mesh_from_baked_model(
        baked_model=baked_model,
        mesh_name=f"Mesh_{object_name}",
        origin_centered=True,
        material_map=material_map
    )
    obj = bpy.data.objects.new(object_name, mesh)
    obj.location = location

    target_coll = collection or bpy.context.collection
    target_coll.objects.link(obj)
    return obj
