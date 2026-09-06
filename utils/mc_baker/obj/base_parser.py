"""
Lightweight and robust Wavefront OBJ parser for Minecraft model baking.
Parses vertices, texture coordinates, vertex normals, material tags, and polygon faces.
Can parse directly from strings, byte streams, or filesystem paths.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Optional, Union, Sequence, Iterator

Vec3 = Tuple[float, float, float]
Vec2 = Tuple[float, float]


@dataclass
class OBJRawFace:
    """Represents a single parsed face from an OBJ file."""
    verts: list[Vec3]
    uvs: list[Vec2]
    normals: list[Vec3]
    material: str = ""
    tint_index: int = -1
    object_name: str = "default"


class WavefrontOBJParser:
    """
    Pure Python parser for Wavefront OBJ files conforming to standard OBJ specifications
    and Minecraft / MiEx extensions (e.g. usemtl [tint_index]texture_name).
    """

    @classmethod
    def parse_text(cls, text: str, object_filter: Optional[Sequence[str]] = None) -> list[OBJRawFace]:
        """
        Parse OBJ text content into a list of OBJRawFace instances.
        If object_filter is provided, only faces belonging to matching 'o' or 'g' groups are included.
        """
        verts: list[Vec3] = []
        uvs: list[Vec2] = []
        normals: list[Vec3] = []

        curr_obj = "default"
        curr_mtl = ""
        curr_tint = -1

        faces: list[OBJRawFace] = []
        filter_set = set(object_filter) if object_filter else None

        for line in text.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue

            parts = line_str.split()
            if not parts:
                continue
            tag = parts[0]

            if tag in ("o", "g"):
                curr_obj = parts[1] if len(parts) > 1 else "default"

            elif tag == "v":
                # v x y z [w]
                if len(parts) >= 4:
                    try:
                        verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
                    except ValueError:
                        pass

            elif tag == "vt":
                # vt u [v] [w]
                if len(parts) >= 3:
                    try:
                        uvs.append((float(parts[1]), float(parts[2])))
                    except ValueError:
                        pass
                elif len(parts) == 2:
                    try:
                        uvs.append((float(parts[1]), 0.0))
                    except ValueError:
                        pass

            elif tag == "vn":
                # vn i j k
                if len(parts) >= 4:
                    try:
                        normals.append((float(parts[1]), float(parts[2]), float(parts[3])))
                    except ValueError:
                        pass

            elif tag == "usemtl":
                # usemtl [tint_index]texture_name (MiEx / Forge extension)
                raw_mtl = parts[1] if len(parts) > 1 else ""
                curr_tint = -1
                if raw_mtl.startswith("["):
                    end_idx = raw_mtl.find("]")
                    if end_idx >= 0:
                        tint_str = raw_mtl[1:end_idx]
                        if tint_str.isdigit() or (tint_str.startswith("-") and tint_str[1:].isdigit()):
                            try:
                                curr_tint = int(tint_str)
                            except ValueError:
                                pass
                        raw_mtl = raw_mtl[end_idx + 1:]
                curr_mtl = raw_mtl

            elif tag == "f":
                if filter_set and curr_obj not in filter_set:
                    continue

                f_verts: list[Vec3] = []
                f_uvs: list[Vec2] = []
                f_norms: list[Vec3] = []

                num_verts = len(verts)
                num_uvs = len(uvs)
                num_norms = len(normals)

                for tok in parts[1:]:
                    sub = tok.split("/")
                    # Vertex index (1-based, can be negative in OBJ)
                    try:
                        raw_vi = int(sub[0])
                        vi = raw_vi - 1 if raw_vi > 0 else num_verts + raw_vi
                    except (ValueError, IndexError):
                        continue

                    if not (0 <= vi < num_verts):
                        continue

                    # Texture UV index
                    ui = -1
                    if len(sub) > 1 and sub[1]:
                        try:
                            raw_ui = int(sub[1])
                            ui = raw_ui - 1 if raw_ui > 0 else num_uvs + raw_ui
                        except ValueError:
                            pass

                    # Normal index
                    ni = -1
                    if len(sub) > 2 and sub[2]:
                        try:
                            raw_ni = int(sub[2])
                            ni = raw_ni - 1 if raw_ni > 0 else num_norms + raw_ni
                        except ValueError:
                            pass

                    f_verts.append(verts[vi])
                    f_uvs.append(uvs[ui] if (0 <= ui < num_uvs) else (0.0, 0.0))
                    if 0 <= ni < num_norms:
                        f_norms.append(normals[ni])

                if len(f_verts) < 3:
                    continue

                # Triangulate / fan out polygons with > 4 vertices into quads / triangles
                if len(f_verts) == 3 or len(f_verts) == 4:
                    faces.append(OBJRawFace(
                        verts=f_verts,
                        uvs=f_uvs,
                        normals=f_norms,
                        material=curr_mtl,
                        tint_index=curr_tint,
                        object_name=curr_obj,
                    ))
                else:
                    # Convex polygon triangle fan (0, i, i+1)
                    for i in range(1, len(f_verts) - 1):
                        tri_v = [f_verts[0], f_verts[i], f_verts[i + 1]]
                        tri_u = [f_uvs[0], f_uvs[i], f_uvs[i + 1]]
                        tri_n = [f_norms[0], f_norms[i], f_norms[i + 1]] if len(f_norms) == len(f_verts) else []
                        faces.append(OBJRawFace(
                            verts=tri_v,
                            uvs=tri_u,
                            normals=tri_n,
                            material=curr_mtl,
                            tint_index=curr_tint,
                            object_name=curr_obj,
                        ))

        return faces

    @classmethod
    def parse_file(cls, filepath: Union[str, Path], object_filter: Optional[Sequence[str]] = None) -> list[OBJRawFace]:
        """Parse OBJ directly from filesystem path."""
        p = Path(filepath)
        if not p.is_file():
            return []
        return cls.parse_text(p.read_text(encoding="utf-8", errors="replace"), object_filter=object_filter)
