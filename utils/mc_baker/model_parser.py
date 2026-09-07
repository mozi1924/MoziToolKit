"""
Minecraft Model JSON Parser & Resolver.
Handles parent inheritance, recursive #texture variable substitution,
and modern 1.21+ object texture formats ({'sprite': '...', 'force_translucent': True}).
"""

from __future__ import annotations
import copy
from typing import Any, Optional, Union

from .obj.mod_obj_loader import ModOBJLoader


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

    def _normalize_id(self, model_id: str, default_namespace: str = "minecraft") -> str:
        if not model_id:
            return ""
        if ":" in model_id:
            namespace, path = model_id.split(":", 1)
        else:
            namespace, path = default_namespace, model_id
        if "/" not in path:
            path = f"block/{path}"
        return f"{namespace}:{path}"

    def load_raw_model(self, model_id: str, default_namespace: str = "minecraft") -> Optional[dict[str, Any]]:
        norm_id = self._normalize_id(model_id, default_namespace=default_namespace)
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

    def resolve_model(
        self,
        model_or_id: Union[str, dict[str, Any]],
        extra_textures: Optional[dict[str, Any]] = None,
        visited_models: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        hierarchy: list[dict[str, Any]] = []
        visited = set(visited_models) if visited_models else set()

        if isinstance(model_or_id, dict):
            hierarchy.append(copy.deepcopy(model_or_id))
            parent = model_or_id.get("parent")
            root_model_id = model_or_id.get("model_id", "")
            default_namespace = root_model_id.split(":", 1)[0] if ":" in root_model_id else "minecraft"
            current_id = self._normalize_id(parent, default_namespace=default_namespace) if parent else None
            synth_id = root_model_id or f"dict_{id(model_or_id)}"
            if synth_id in visited:
                raise ValueError(f"Circular parent reference in model {synth_id}")
            visited.add(synth_id)
        else:
            root_model_id = self._normalize_id(model_or_id)
            default_namespace = root_model_id.split(":", 1)[0] if ":" in root_model_id else "minecraft"
            current_id = root_model_id

        while current_id:
            if current_id in visited:
                raise ValueError(f"Circular parent reference in model {current_id}")
            visited.add(current_id)

            raw = self.load_raw_model(current_id, default_namespace=default_namespace)
            if not raw:
                break
            hierarchy.append(raw)
            parent = raw.get("parent")
            if parent:
                current_id = self._normalize_id(parent, default_namespace=default_namespace)
            else:
                current_id = None

        merged_textures: dict[str, Any] = {}
        if extra_textures:
            merged_textures.update(extra_textures)
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

        # 1. Check for separate-transforms loader (e.g. "loader": "forge:separate-transforms")
        for m in hierarchy:
            if m.get("loader") in ("forge:separate-transforms", "neoforge:separate-transforms") and "base" in m:
                base_spec = m["base"]
                if isinstance(base_spec, str):
                    base_id = self._normalize_id(base_spec, default_namespace=default_namespace)
                    res = self.resolve_model(base_id, extra_textures=resolved_textures, visited_models=visited)
                elif isinstance(base_spec, dict):
                    res = self.resolve_model(base_spec, extra_textures=resolved_textures, visited_models=visited)
                else:
                    break
                res["model_id"] = root_model_id or res.get("model_id", "")
                return res

        # 2. Check for composite loader (e.g. "loader": "forge:composite" / "neoforge:composite" or "children" present)
        is_composite = any(
            m.get("loader") in ("forge:composite", "neoforge:composite") or "children" in m
            for m in hierarchy
        )
        if is_composite:
            return self._resolve_composite_model(
                hierarchy=hierarchy,
                root_model_id=root_model_id,
                default_namespace=default_namespace,
                resolved_textures=resolved_textures,
                ambientocclusion=ambientocclusion,
                visited=visited,
            )

        # 3. Check if this model is backed by an OBJ mesh (direct .obj or Forge/NeoForge OBJ loader)
        raw_obj = None
        for m in hierarchy:
            if m.get("_is_obj"):
                raw_obj = m.get("_raw_obj")
                break
            elif m.get("loader") in ("forge:obj", "neoforge:obj") or (isinstance(m.get("model"), str) and m.get("model", "").endswith(".obj")):
                if "_raw_obj" in m:
                    raw_obj = m["_raw_obj"]
                    break
                obj_ref = m.get("model", "")
                if obj_ref:
                    raw_model_data = self.load_raw_model(obj_ref, default_namespace=default_namespace)
                    if raw_model_data and raw_model_data.get("_raw_obj"):
                        raw_obj = raw_model_data.get("_raw_obj")
                        break

        if raw_obj:
            fallback_tex = resolved_textures.get("particle") or next(iter(resolved_textures.values()), "minecraft:block/dirt")
            baked_obj = ModOBJLoader.bake_from_text(
                raw_obj,
                textures_map=resolved_textures,
                fallback_texture=fallback_tex,
            )
            if baked_obj and baked_obj.elements:
                resolved_elements = []
                for elem in baked_obj.elements:
                    elem_faces_dict = {}
                    for d, bf in elem.faces.items():
                        elem_faces_dict[d] = {
                            "texture": bf.texture,
                            "uv": [bf.uv_bounds[0] * 16, bf.uv_bounds[1] * 16, bf.uv_bounds[2] * 16, bf.uv_bounds[3] * 16],
                            "cullface": bf.cullface,
                            "tintindex": bf.tint_index,
                            "_baked_face": bf,
                        }
                    resolved_elements.append({
                        "from": list(elem.from_pos),
                        "to": list(elem.to_pos),
                        "faces": elem_faces_dict,
                        "_is_obj_element": True,
                    })
                return {
                    "model_id": root_model_id or self._normalize_id(model_or_id if isinstance(model_or_id, str) else ""),
                    "textures": resolved_textures,
                    "elements": resolved_elements,
                    "ambientocclusion": ambientocclusion,
                }

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
            "model_id": root_model_id or (self._normalize_id(model_or_id) if isinstance(model_or_id, str) else ""),
            "textures": resolved_textures,
            "elements": resolved_elements,
            "ambientocclusion": ambientocclusion,
        }

    def _resolve_composite_model(
        self,
        hierarchy: list[dict[str, Any]],
        root_model_id: str,
        default_namespace: str,
        resolved_textures: dict[str, Any],
        ambientocclusion: bool,
        visited: set[str],
    ) -> dict[str, Any]:
        merged_visibility: dict[str, bool] = {}
        for m in reversed(hierarchy):
            if "visibility" in m and isinstance(m["visibility"], dict):
                for k, v in m["visibility"].items():
                    if isinstance(v, str):
                        merged_visibility[k] = v.lower() not in ("false", "0")
                    else:
                        merged_visibility[k] = bool(v)

        merged_children: dict[str, Any] = {}
        for m in reversed(hierarchy):
            if "children" in m:
                raw_ch = m["children"]
                if isinstance(raw_ch, dict):
                    merged_children.update(raw_ch)
                elif isinstance(raw_ch, list):
                    for idx, item in enumerate(raw_ch):
                        merged_children[f"part_{idx}"] = item

        parts_order: Optional[list[str]] = None
        for m in reversed(hierarchy):
            if "parts" in m and isinstance(m["parts"], list):
                parts_order = [p for p in m["parts"] if isinstance(p, str)]

        if parts_order:
            ordered_keys = [k for k in parts_order if k in merged_children]
            ordered_keys.extend([k for k in merged_children if k not in ordered_keys])
        else:
            ordered_keys = list(merged_children.keys())

        composite_elements: list[dict[str, Any]] = []
        composite_textures: dict[str, str] = dict(resolved_textures)

        for part_name in ordered_keys:
            if not merged_visibility.get(part_name, True):
                continue
            child_spec = merged_children[part_name]
            child_res = self._resolve_composite_child(
                child_spec,
                default_namespace=default_namespace,
                extra_textures=resolved_textures,
                visited_models=visited,
            )
            if child_res:
                if "textures" in child_res and isinstance(child_res["textures"], dict):
                    composite_textures.update(child_res["textures"])
                if "elements" in child_res and isinstance(child_res["elements"], list):
                    composite_elements.extend(child_res["elements"])

        return {
            "model_id": root_model_id,
            "textures": composite_textures,
            "elements": composite_elements,
            "ambientocclusion": ambientocclusion,
        }

    def _resolve_composite_child(
        self,
        child_spec: Union[str, dict[str, Any]],
        default_namespace: str = "minecraft",
        extra_textures: Optional[dict[str, Any]] = None,
        visited_models: Optional[set[str]] = None,
    ) -> Optional[dict[str, Any]]:
        if isinstance(child_spec, str):
            child_id = self._normalize_id(child_spec, default_namespace=default_namespace)
            return self.resolve_model(child_id, extra_textures=extra_textures, visited_models=visited_models)

        if not isinstance(child_spec, dict):
            return None

        child_copy = copy.deepcopy(child_spec)
        if "parent" in child_copy and isinstance(child_copy["parent"], str):
            parent_ref = child_copy["parent"]
            if ":" not in parent_ref:
                child_copy["parent"] = f"{default_namespace}:{parent_ref}"

        return self.resolve_model(child_copy, extra_textures=extra_textures, visited_models=visited_models)

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
