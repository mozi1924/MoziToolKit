"""
Generic Mod OBJ Model Loader and Baker for Minecraft Mods (e.g. Create, Immersive Engineering).
Conforms to MiEx ModelHandlerObj and Forge / NeoForge OBJ model specifications:
- Direct parsing of mod OBJ models from Zip streams or files
- Auto-normalization of coordinate systems (16-pixel Blockbench units vs 1.0-voxel Forge units)
- Auto-centering for origin-centered [-0.5..0.5] models into standard [0..1] Minecraft block space
- Material variable mapping and substitution (MTL names, #var texture tokens)
- MiEx [tint_index]texture syntax support
- Polygon triangulation / quad conversion and authoritative 6-direction normal projection
"""

from __future__ import annotations
import math
from pathlib import Path
from typing import Optional, Any, Tuple, Union, Sequence, Dict, List

from ..types import BakedModel, BakedElement, BakedFace, MC_DIRECTIONS
from ..primitives import (
    Vec3, Vec2,
    calculate_normal,
    normal_to_mc_direction,
)
from .base_parser import WavefrontOBJParser, OBJRawFace


def _calculate_polygon_normal(verts: Sequence[Vec3]) -> Vec3:
    """Calculate normalized geometric normal for a polygon."""
    if len(verts) < 3:
        return (0.0, 1.0, 0.0)
    return calculate_normal(verts[0], verts[1], verts[2])


class ModOBJLoader:
    """
    Generic OBJ model baker for modded Minecraft blocks.
    Transforms arbitrary OBJ meshes into fully baked Minecraft BakedModel instances.
    """

    @classmethod
    def bake_from_text(
        cls,
        obj_text: str,
        block_state: str = "",
        textures_map: Optional[dict[str, str]] = None,
        fallback_texture: str = "minecraft:block/dirt",
        rot_x: float = 0.0,
        rot_y: float = 0.0,
        rot_z: float = 0.0,
        offset: Vec3 = (0.0, 0.0, 0.0),
        object_filter: Optional[Sequence[str]] = None,
    ) -> Optional[BakedModel]:
        """Bake an OBJ model from raw text content."""
        raw_faces = WavefrontOBJParser.parse_text(obj_text, object_filter=object_filter)
        return cls._build_baked_model(
            raw_faces,
            block_state=block_state,
            textures_map=textures_map,
            fallback_texture=fallback_texture,
            rot_x=rot_x,
            rot_y=rot_y,
            rot_z=rot_z,
            offset=offset,
        )

    @classmethod
    def bake_from_file(
        cls,
        filepath: Union[str, Path],
        block_state: str = "",
        textures_map: Optional[dict[str, str]] = None,
        fallback_texture: str = "minecraft:block/dirt",
        rot_x: float = 0.0,
        rot_y: float = 0.0,
        rot_z: float = 0.0,
        offset: Vec3 = (0.0, 0.0, 0.0),
        object_filter: Optional[Sequence[str]] = None,
    ) -> Optional[BakedModel]:
        """Bake an OBJ model from filesystem path."""
        p = Path(filepath)
        if not p.is_file():
            return None
        return cls.bake_from_text(
            p.read_text(encoding="utf-8", errors="replace"),
            block_state=block_state,
            textures_map=textures_map,
            fallback_texture=fallback_texture,
            rot_x=rot_x,
            rot_y=rot_y,
            rot_z=rot_z,
            offset=offset,
            object_filter=object_filter,
        )

    @classmethod
    def _build_baked_model(
        cls,
        raw_faces: list[OBJRawFace],
        block_state: str,
        textures_map: Optional[dict[str, str]],
        fallback_texture: str,
        rot_x: float,
        rot_y: float,
        rot_z: float,
        offset: Vec3,
    ) -> Optional[BakedModel]:
        if not raw_faces:
            return None

        textures_map = textures_map or {}

        # 1. Inspect coordinate extents to auto-detect coordinate unit
        all_verts = [v for f in raw_faces for v in f.verts]
        if not all_verts:
            return None

        min_x = min(v[0] for v in all_verts)
        max_x = max(v[0] for v in all_verts)
        min_y = min(v[1] for v in all_verts)
        max_y = max(v[1] for v in all_verts)
        min_z = min(v[2] for v in all_verts)
        max_z = max(v[2] for v in all_verts)

        span_x = max_x - min_x
        span_y = max_y - min_y
        span_z = max_z - min_z
        max_span = max(span_x, span_y, span_z)

        # Scale detection: if coordinates are in pixel space (~16 units, Blockbench style)
        auto_scale = 1.0 / 16.0 if max_span > 2.0 else 1.0

        # Center detection: if coordinates are centered around origin [-0.5..0.5] or [-8..8]
        is_centered = (min_x * auto_scale < -0.1 or min_y * auto_scale < -0.1 or min_z * auto_scale < -0.1)
        shift_x = 0.5 if is_centered else 0.0
        shift_y = 0.5 if is_centered else 0.0
        shift_z = 0.5 if is_centered else 0.0

        # UV scale detection: check if UVs are [0..16] instead of [0..1]
        all_uvs = [u for f in raw_faces for u in f.uvs]
        max_uv = max(max(abs(u[0]), abs(u[1])) for u in all_uvs) if all_uvs else 1.0
        uv_scale = 1.0 / 16.0 if max_uv > 2.0 else 1.0

        elements: list[BakedElement] = []
        face_objects: list[BakedFace] = []

        for f_data in raw_faces:
            raw_verts = f_data.verts
            raw_uvs = f_data.uvs
            mtl = f_data.material

            # Resolve texture ID
            tex_id = None
            if mtl:
                clean_mtl = mtl.lstrip("#")
                if mtl in textures_map:
                    tex_id = textures_map[mtl]
                elif clean_mtl in textures_map:
                    tex_id = textures_map[clean_mtl]
                elif f"#{clean_mtl}" in textures_map:
                    tex_id = textures_map[f"#{clean_mtl}"]
                elif ":" in mtl:
                    tex_id = mtl

            if not tex_id:
                tex_id = fallback_texture

            # Transform Vertices into [0..1] block space
            transformed_verts: list[Vec3] = []
            for v in raw_verts:
                x = v[0] * auto_scale + shift_x + offset[0]
                y = v[1] * auto_scale + shift_y + offset[1]
                z = v[2] * auto_scale + shift_z + offset[2]

                # Apply blockstate rotations if requested
                if rot_x != 0.0 or rot_y != 0.0 or rot_z != 0.0:
                    x, y, z = cls._rotate_point((x, y, z), rot_x, rot_y, rot_z, center=(0.5, 0.5, 0.5))

                transformed_verts.append((x, y, z))

            # Transform UVs: Flip V axis (Minecraft top=0, bottom=1 vs OBJ bottom=0, top=1)
            transformed_uvs: list[Vec2] = []
            for u, v in raw_uvs:
                scaled_u = u * uv_scale
                scaled_v = v * uv_scale
                transformed_uvs.append((scaled_u, 1.0 - scaled_v))

            # Turn triangle into quad (MiEx degeneration technique: 4th vertex is midpoint of v0 and v2)
            if len(transformed_verts) == 3:
                v0 = transformed_verts[0]
                v2 = transformed_verts[2]
                v3 = ((v0[0] + v2[0]) * 0.5, (v0[1] + v2[1]) * 0.5, (v0[2] + v2[2]) * 0.5)
                transformed_verts.append(v3)

                u0 = transformed_uvs[0] if transformed_uvs else (0.0, 0.0)
                u2 = transformed_uvs[2] if len(transformed_uvs) > 2 else (1.0, 1.0)
                u3 = ((u0[0] + u2[0]) * 0.5, (u0[1] + u2[1]) * 0.5)
                transformed_uvs.append(u3)

            # Ensure 4 UV entries
            while len(transformed_uvs) < len(transformed_verts):
                transformed_uvs.append((0.0, 0.0))

            # Calculate normal & Minecraft 6-direction classification
            norm = _calculate_polygon_normal(transformed_verts)
            face_dir = normal_to_mc_direction(norm)

            min_u = min(u for u, _ in transformed_uvs) if transformed_uvs else 0.0
            max_u = max(u for u, _ in transformed_uvs) if transformed_uvs else 1.0
            min_v = min(v for _, v in transformed_uvs) if transformed_uvs else 0.0
            max_v = max(v for _, v in transformed_uvs) if transformed_uvs else 1.0

            baked_face = BakedFace(
                direction=face_dir,
                texture=tex_id,
                uv_bounds=(min_u, min_v, max_u, max_v),
                tint_index=f_data.tint_index,
                vertices=tuple(transformed_verts[:4]),
                uvs=tuple(transformed_uvs[:4]),
            )
            face_objects.append(baked_face)

            # Build element bounding box
            xs = [v[0] for v in transformed_verts]
            ys = [v[1] for v in transformed_verts]
            zs = [v[2] for v in transformed_verts]
            from_pos = (min(xs) * 16.0, min(ys) * 16.0, min(zs) * 16.0)
            to_pos = (max(xs) * 16.0, max(ys) * 16.0, max(zs) * 16.0)

            elements.append(BakedElement(
                from_pos=from_pos,
                to_pos=to_pos,
                faces={face_dir: baked_face},
            ))

        # Standard 6-face summary
        six_faces = []
        for d in MC_DIRECTIONS:
            match = next((f for f in face_objects if f.direction == d), None)
            if match:
                six_faces.append(match)
            elif face_objects:
                six_faces.append(face_objects[0])
            else:
                six_faces.append(BakedFace(direction=d, texture=fallback_texture))

        return BakedModel(
            block_state=block_state,
            elements=elements,
            faces=six_faces,
            is_cube=False,
            is_opaque=False,
        )

    @staticmethod
    def _rotate_point(p: Vec3, rx: float, ry: float, rz: float, center: Vec3 = (0.5, 0.5, 0.5)) -> Vec3:
        """Rotate point around center by Euler angles in degrees."""
        cx, cy, cz = center
        x, y, z = p[0] - cx, p[1] - cy, p[2] - cz

        # Rotate around X
        if rx != 0.0:
            rad = math.radians(rx)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            y, z = y * cos_a - z * sin_a, y * sin_a + z * cos_a

        # Rotate around Y
        if ry != 0.0:
            rad = math.radians(ry)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            x, z = x * cos_a + z * sin_a, -x * sin_a + z * cos_a

        # Rotate around Z
        if rz != 0.0:
            rad = math.radians(rz)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            x, y = x * cos_a - y * sin_a, x * sin_a + y * cos_a

        return (x + cx, y + cy, z + cz)
