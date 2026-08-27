"""
Minecraft Model JSON Parser & Resolver.
Handles parent inheritance, recursive #texture variable substitution,
and modern 1.21+ object texture formats ({'sprite': '...', 'force_translucent': True}).
"""

from __future__ import annotations
import copy
from typing import Any, Optional, Union


BUILTIN_MODELS: dict[str, dict[str, Any]] = {
    "minecraft:block/bell_floor": {
        "textures": {
            "particle": "minecraft:block/bell_bottom",
            "bar": "minecraft:block/dark_oak_planks",
            "post": "minecraft:block/stone",
        },
        "elements": [
            {
                "from": [2, 13, 7],
                "to": [14, 15, 9],
                "faces": {
                    "north": {"uv": [2, 2, 14, 4], "texture": "#bar"},
                    "south": {"uv": [2, 3, 14, 5], "texture": "#bar"},
                    "up": {"uv": [2, 3, 14, 5], "texture": "#bar"},
                    "down": {"uv": [2, 3, 14, 5], "texture": "#bar"},
                },
            },
            {
                "from": [14, 0, 6],
                "to": [16, 16, 10],
                "faces": {
                    "north": {"uv": [0, 1, 2, 16], "texture": "#post"},
                    "east": {"uv": [0, 1, 4, 16], "texture": "#post"},
                    "south": {"uv": [0, 1, 2, 16], "texture": "#post"},
                    "west": {"uv": [0, 1, 4, 16], "texture": "#post"},
                    "up": {"uv": [0, 1, 2, 5], "texture": "#post"},
                    "down": {"uv": [0, 1, 2, 5], "texture": "#post"},
                },
            },
            {
                "from": [0, 0, 6],
                "to": [2, 16, 10],
                "faces": {
                    "north": {"uv": [0, 1, 2, 16], "texture": "#post"},
                    "east": {"uv": [0, 1, 4, 16], "texture": "#post"},
                    "south": {"uv": [0, 1, 2, 16], "texture": "#post"},
                    "west": {"uv": [0, 1, 4, 16], "texture": "#post"},
                    "up": {"uv": [0, 1, 2, 5], "texture": "#post"},
                    "down": {"uv": [0, 1, 2, 5], "texture": "#post"},
                },
            },
        ],
    },
    "minecraft:block/bell_ceiling": {
        "textures": {
            "particle": "minecraft:block/bell_bottom",
            "bar": "minecraft:block/dark_oak_planks",
            "post": "minecraft:block/stone",
        },
        "elements": [
            {
                "from": [4, 13, 7],
                "to": [12, 15, 9],
                "faces": {
                    "north": {"uv": [4, 2, 12, 4], "texture": "#bar"},
                    "east": {"uv": [4, 2, 6, 4], "texture": "#bar"},
                    "south": {"uv": [4, 3, 12, 5], "texture": "#bar"},
                    "west": {"uv": [4, 3, 6, 5], "texture": "#bar"},
                    "up": {"uv": [4, 3, 12, 5], "texture": "#bar"},
                    "down": {"uv": [4, 3, 12, 5], "texture": "#bar"},
                },
            },
            {
                "from": [7, 13, 7],
                "to": [9, 16, 9],
                "faces": {
                    "north": {"uv": [0, 0, 2, 3], "texture": "#post"},
                    "east": {"uv": [0, 0, 2, 3], "texture": "#post"},
                    "south": {"uv": [0, 0, 2, 3], "texture": "#post"},
                    "west": {"uv": [0, 0, 2, 3], "texture": "#post"},
                    "up": {"uv": [0, 0, 2, 2], "texture": "#post"},
                    "down": {"uv": [0, 0, 2, 2], "texture": "#post"},
                },
            },
        ],
    },
    "minecraft:block/bell_wall": {
        "textures": {
            "particle": "minecraft:block/bell_bottom",
            "bar": "minecraft:block/dark_oak_planks",
            "post": "minecraft:block/stone",
        },
        "elements": [
            {
                "from": [4, 13, 7],
                "to": [12, 15, 9],
                "faces": {
                    "north": {"uv": [4, 2, 12, 4], "texture": "#bar"},
                    "east": {"uv": [4, 2, 6, 4], "texture": "#bar"},
                    "south": {"uv": [4, 3, 12, 5], "texture": "#bar"},
                    "west": {"uv": [4, 3, 6, 5], "texture": "#bar"},
                    "up": {"uv": [4, 3, 12, 5], "texture": "#bar"},
                    "down": {"uv": [4, 3, 12, 5], "texture": "#bar"},
                },
            },
            {
                "from": [6, 7, 0],
                "to": [10, 16, 8],
                "faces": {
                    "north": {"uv": [0, 7, 4, 16], "texture": "#post"},
                    "east": {"uv": [0, 7, 8, 16], "texture": "#post"},
                    "south": {"uv": [0, 7, 4, 16], "texture": "#post"},
                    "west": {"uv": [0, 7, 8, 16], "texture": "#post"},
                    "up": {"uv": [0, 7, 4, 15], "texture": "#post"},
                    "down": {"uv": [0, 7, 4, 15], "texture": "#post"},
                },
            },
        ],
    },
    "minecraft:block/bell_between_walls": {
        "textures": {
            "particle": "minecraft:block/bell_bottom",
            "bar": "minecraft:block/dark_oak_planks",
        },
        "elements": [
            {
                "from": [0, 13, 7],
                "to": [16, 15, 9],
                "faces": {
                    "north": {"uv": [0, 2, 16, 4], "texture": "#bar"},
                    "south": {"uv": [0, 3, 16, 5], "texture": "#bar"},
                    "up": {"uv": [0, 3, 16, 5], "texture": "#bar"},
                    "down": {"uv": [0, 3, 16, 5], "texture": "#bar"},
                },
            },
        ],
    },
}


class ModelParser:
    def __init__(self, model_loader_fn=None):
        self.model_loader_fn = model_loader_fn
        self._model_cache: dict[str, dict[str, Any]] = {}

    def register_model(self, model_id: str, data: dict[str, Any]):
        self._model_cache[self._normalize_id(model_id)] = data

    def _normalize_id(self, model_id: str) -> str:
        if not model_id:
            return ""
        if ":" in model_id:
            namespace, path = model_id.split(":", 1)
        else:
            namespace, path = "minecraft", model_id
        if not path.startswith("block/") and not path.startswith("item/"):
            path = f"block/{path}"
        return f"{namespace}:{path}"

    def load_raw_model(self, model_id: str) -> Optional[dict[str, Any]]:
        norm_id = self._normalize_id(model_id)
        if norm_id in self._model_cache:
            return copy.deepcopy(self._model_cache[norm_id])

        if self.model_loader_fn:
            data = self.model_loader_fn(norm_id)
            if data:
                self._model_cache[norm_id] = data
                return copy.deepcopy(data)

        if norm_id in BUILTIN_MODELS:
            return copy.deepcopy(BUILTIN_MODELS[norm_id])

        return None

    def resolve_model(self, model_id: str) -> dict[str, Any]:
        hierarchy: list[dict[str, Any]] = []
        visited = set()
        current_id = self._normalize_id(model_id)

        while current_id:
            if current_id in visited:
                raise ValueError(f"Circular parent reference in model {current_id}")
            visited.add(current_id)

            raw = self.load_raw_model(current_id)
            if not raw:
                break
            hierarchy.append(raw)
            parent = raw.get("parent")
            if parent:
                current_id = self._normalize_id(parent)
            else:
                current_id = None

        merged_textures: dict[str, Any] = {}
        elements: Optional[list[dict[str, Any]]] = None
        ambientocclusion = True

        for m in reversed(hierarchy):
            if "textures" in m:
                merged_textures.update(m["textures"])
            if "elements" in m:
                elements = copy.deepcopy(m["elements"])
            if "ambientocclusion" in m:
                ambientocclusion = m["ambientocclusion"]

        resolved_textures = self._resolve_texture_map(merged_textures)

        resolved_elements = []
        if elements:
            for elem in elements:
                elem_copy = copy.deepcopy(elem)
                faces = elem_copy.get("faces", {})
                for face_dir, face_data in faces.items():
                    tex_ref = face_data.get("texture", "")
                    if isinstance(tex_ref, dict):
                        tex_ref = tex_ref.get("sprite", "")
                    tex_ref = str(tex_ref)

                    if tex_ref.startswith("#"):
                        var_name = tex_ref[1:]
                        face_data["texture"] = resolved_textures.get(var_name, tex_ref)
                    else:
                        face_data["texture"] = self._normalize_texture(tex_ref)
                resolved_elements.append(elem_copy)

        return {
            "model_id": self._normalize_id(model_id),
            "textures": resolved_textures,
            "elements": resolved_elements,
            "ambientocclusion": ambientocclusion,
        }

    def _resolve_texture_map(self, raw_textures: dict[str, Any]) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for k, v in raw_textures.items():
            curr = v
            visited = set()
            while isinstance(curr, dict) or (isinstance(curr, str) and curr.startswith("#")):
                if isinstance(curr, dict):
                    curr = curr.get("sprite", curr.get("texture", ""))
                elif isinstance(curr, str) and curr.startswith("#"):
                    var_name = curr[1:]
                    if var_name in visited:
                        break
                    visited.add(var_name)
                    curr = raw_textures.get(var_name, curr)
                else:
                    break
            resolved[k] = self._normalize_texture(str(curr) if curr else "")
        return resolved

    def _normalize_texture(self, tex: str) -> str:
        if not tex or tex.startswith("#"):
            return tex
        if ":" in tex:
            ns, path = tex.split(":", 1)
        else:
            ns, path = "minecraft", tex
        if "/" not in path:
            path = f"block/{path}"
        return f"{ns}:{path}"
