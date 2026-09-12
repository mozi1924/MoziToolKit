"""
Headless Minecraft BlockState Baker.
Powered by LibMTK high-performance pure-Rust backend.
"""

from __future__ import annotations
from typing import Optional, Any, Union, Iterator, Tuple, Callable
from pathlib import Path
import json

import libmtk_py as mtk

from .types import (
    BakedModel, BakedElement, BakedFace,
    MC_DIRECTIONS, DIR_TO_INDEX
)
from ..materials.constants import EMISSIVE_BLOCKS


def is_block_emissive(block_name: str, props: Optional[dict[str, str]] = None) -> bool:
    """Return True if block/state is emissive (light emitting), else False."""
    p = props or {}
    short_name = block_name.split(":", 1)[-1].removeprefix("block/")
    if short_name in EMISSIVE_BLOCKS or short_name.endswith("_froglight"):
        return True
    return mtk.is_block_emissive(block_name)


_GLOBAL_STATE_BAKER: Optional[StateBaker] = None
_last_pack_fingerprint: Optional[tuple[str, ...]] = None


def get_shared_state_baker() -> StateBaker:
    """Return the shared global StateBaker singleton instance."""
    global _GLOBAL_STATE_BAKER
    if _GLOBAL_STATE_BAKER is None:
        _GLOBAL_STATE_BAKER = StateBaker()
    return _GLOBAL_STATE_BAKER


def refresh_shared_baker_sources(force_precompile_if_missing: bool = False) -> StateBaker:
    """Synchronize shared StateBaker with the active Resource Pack Stack."""
    global _last_pack_fingerprint
    baker = get_shared_state_baker()
    try:
        from ..materials.pack import get_configured_pack_stack, get_pack_stack_fingerprint
        current_fingerprint = get_pack_stack_fingerprint()
        if current_fingerprint != _last_pack_fingerprint or (force_precompile_if_missing and not baker._bake_cache):
            _last_pack_fingerprint = current_fingerprint
            stack = get_configured_pack_stack()
            baker.clear_cache()
            if stack.is_models_baked():
                manifest_path = stack.get_baked_models_dir() / "models_manifest.json"
                baker.load_precompiled_manifest(manifest_path)
            elif force_precompile_if_missing and stack.packs:
                stack.precompile_models()
                if stack.is_models_baked():
                    manifest_path = stack.get_baked_models_dir() / "models_manifest.json"
                    baker.load_precompiled_manifest(manifest_path)
    except Exception:
        pass
    return baker


def clear_shared_baker_cache() -> None:
    """Clear shared StateBaker cache and reset cached resource pack fingerprints."""
    global _GLOBAL_STATE_BAKER, _last_pack_fingerprint
    if _GLOBAL_STATE_BAKER is not None:
        _GLOBAL_STATE_BAKER.clear_cache()
    _last_pack_fingerprint = None


class DummyModelParser:
    def __init__(self, model_loader_fn=None):
        self.model_loader_fn = model_loader_fn
        self._model_cache = {}

    def register_model(self, model_id: str, data: Any):
        self._model_cache[model_id] = data

    def resolve_model(self, model_id: str) -> Optional[dict]:
        from .model_parser import ModelParser
        parser = ModelParser(model_loader_fn=self.model_loader_fn)
        for k, v in self._model_cache.items():
            parser.register_model(k, v)
        return parser.resolve_model(model_id)


class DummyStateResolver:
    def __init__(self, blockstate_loader_fn=None):
        self.blockstate_loader_fn = blockstate_loader_fn
        self._state_cache = {}

    def register_blockstate(self, state_id: str, data: Any):
        self._state_cache[state_id] = data


def _serialize_model_data_to_json(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: _serialize_model_data_to_json(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_serialize_model_data_to_json(x) for x in data]
    elif hasattr(data, "to_dict"):
        return data.to_dict()
    elif hasattr(data, "texture") and hasattr(data, "direction"):
        res = {"texture": data.texture}
        if hasattr(data, "uv_bounds") and data.uv_bounds:
            res["uv"] = list(data.uv_bounds)
        return res
    elif hasattr(data, "from_pos") and hasattr(data, "to_pos"):
        return {
            "from": list(data.from_pos),
            "to": list(data.to_pos),
            "faces": {k: _serialize_model_data_to_json(v) for k, v in getattr(data, "faces", {}).items()}
        }
    return data


class StateBaker:
    """High-performance BlockState Model Baker wrapping LibMTK."""
    def __init__(
        self,
        jar_path: Optional[Union[str, Path]] = None,
        model_parser: Optional[Any] = None,
        state_resolver: Optional[Any] = None,
    ):
        self._rust_baker = mtk.ModelBaker()
        self._bake_cache: dict[str, Any] = {}
        self.resource_loader = None
        self.model_parser = model_parser or DummyModelParser()
        self.state_resolver = state_resolver or DummyStateResolver()
        self.bake_block_state = self.bake_blockstate

        if jar_path:
            self.set_resource_source(jar_path)

    def set_resource_source(self, jar_path: Union[str, Path]):
        """Set or switch the underlying Minecraft JAR/resource pack source."""
        p = Path(jar_path)
        if p.exists():
            stack = mtk.ResourcePackStack()
            if p.is_dir():
                stack.add_directory_pack(str(p))
            else:
                stack.add_zip_pack(str(p))
            self.resource_loader = stack
        self.clear_cache()

    def is_available(self) -> bool:
        return True

    def clear_cache(self):
        self._rust_baker.clear_cache()
        self._bake_cache.clear()

    def get_model(self, state_str: str) -> Optional[Any]:
        if state_str in self._bake_cache:
            return self._bake_cache[state_str]
        m = self._rust_baker.get_model(state_str)
        if m is not None:
            self._bake_cache[state_str] = m
            return m
        return None

    def _build_memory_stack(self) -> Optional[mtk.ResourcePackStack]:
        model_cache = getattr(self.model_parser, "_model_cache", {})
        state_cache = getattr(self.state_resolver, "_state_cache", {})
        if not model_cache and not state_cache:
            return None
        mem = mtk.MemoryPack("FixtureMemoryPack")
        for k, v in state_cache.items():
            ns, name = k.split(":", 1) if ":" in k else ("minecraft", k)
            path = f"assets/{ns}/blockstates/{name}.json"
            mem.add_file(path, json.dumps(v).encode("utf-8"))
        for k, v in model_cache.items():
            model_data = v
            if hasattr(self.model_parser, "resolve_model"):
                try:
                    resolved = self.model_parser.resolve_model(k)
                    if resolved:
                        model_data = resolved
                except Exception:
                    pass
            serialized = _serialize_model_data_to_json(model_data)
            ns, path_part = k.split(":", 1) if ":" in k else ("minecraft", k)
            path = f"assets/{ns}/models/{path_part.lstrip('/')}.json"
            mem.add_file(path, json.dumps(serialized).encode("utf-8"))

        stack = mtk.ResourcePackStack()
        stack.add_memory_pack(mem)
        return stack

    def bake_blockstate(self, state_str: str, stack: Optional[Any] = None) -> Any:
        """Bake a full Minecraft BlockState string into a BakedModel."""
        clean_state = state_str.strip()
        if clean_state in self._bake_cache:
            return self._bake_cache[clean_state]

        from .blockstate_resolver import parse_block_state_string
        block_id, props = parse_block_state_string(clean_state)

        rust_stack = getattr(stack, "_rust_stack", None)
        if rust_stack is None:
            if isinstance(self.resource_loader, mtk.ResourcePackStack):
                rust_stack = self.resource_loader
            elif hasattr(self.resource_loader, "_rust_stack"):
                rust_stack = self.resource_loader._rust_stack
            elif getattr(self.resource_loader, "pack_path", None):
                curr = self.resource_loader
                paths = []
                while curr:
                    pp = getattr(curr, "pack_path", None)
                    if pp and Path(pp).exists():
                        paths.append(Path(pp))
                    curr = getattr(curr, "fallback_loader", None)
                if paths:
                    rust_stack = mtk.ResourcePackStack()
                    for pp in reversed(paths):
                        if pp.is_dir():
                            rust_stack.add_directory_pack(str(pp))
                        else:
                            rust_stack.add_zip_pack(str(pp))

        if rust_stack is None:
            rust_stack = self._build_memory_stack()

        baked = None
        try:
            baked = self._rust_baker.bake_blockstate(clean_state, rust_stack)
        except Exception:
            try:
                baked = self._rust_baker.bake_blockstate(clean_state, None)
            except Exception:
                baked = None

        if baked is not None and len(baked.elements) > 0:
            if not rust_stack and "hanging_sign" in clean_state:
                from .obj_loader import resolve_obj_model_for_state
                obj_model = resolve_obj_model_for_state(block_id, props)
                if obj_model is not None:
                    self._bake_cache[clean_state] = obj_model
                    return obj_model

            self._bake_cache[clean_state] = baked
            return baked

        # Fallback to OBJ presets (e.g. banners, heads, hanging signs)
        from .obj_loader import resolve_obj_model_for_state
        obj_model = resolve_obj_model_for_state(block_id, props)
        if obj_model is not None:
            self._bake_cache[clean_state] = obj_model
            return obj_model

        if baked is not None:
            self._bake_cache[clean_state] = baked
            return baked

        return BakedModel(block_state=clean_state, elements=[], faces=[], is_cube=False, is_opaque=False)

    def load_precompiled_manifest(self, source: Union[str, Path, dict]) -> int:
        """Load precompiled baked models directly into the internal cache."""
        if isinstance(source, (str, Path)):
            p = Path(source)
            if not p.exists():
                return 0
            count = self._rust_baker.load_manifest(str(p))
            return count
        elif isinstance(source, dict):
            models_map = source.get("models", {})
            for k, v in models_map.items():
                self._bake_cache[k] = v
            return len(models_map)
        return 0

    def save_precompiled_manifest_iter(
        self, output_file: Union[str, Path], pack_stack: Optional[Any] = None
    ) -> Iterator[Tuple[float, str, Optional[int]]]:
        """Bake all pack states and save to a JSON manifest file on disk with progress updates."""
        out_path = Path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        yield (0.05, "Baking blockstates in parallel with LibMTK Rust engine...", None)

        rust_stack = getattr(pack_stack, "_rust_stack", None)
        if rust_stack is None and isinstance(self.resource_loader, mtk.ResourcePackStack):
            rust_stack = self.resource_loader

        if rust_stack is not None:
            count = rust_stack.bake_models_manifest(str(out_path))
            self._rust_baker.load_manifest(str(out_path))
            yield (1.0, f"Successfully baked and cached {count} models.", count)
        else:
            yield (1.0, "No active resource pack stack found.", 0)

    def save_precompiled_manifest(
        self,
        output_file: Union[str, Path],
        progress_callback: Optional[Callable[[float, str], None]] = None,
        pack_stack: Optional[Any] = None,
    ) -> int:
        final_count = 0
        for frac, msg, count in self.save_precompiled_manifest_iter(output_file, pack_stack=pack_stack):
            if progress_callback:
                try:
                    progress_callback(frac, msg)
                except Exception:
                    pass
            if count is not None:
                final_count = count
        return final_count

    def bake_all_pack_states_iter(self) -> Iterator[Tuple[float, str, dict[str, Any]]]:
        """Scan and bake all blockstates in the resource pack / JAR incrementally."""
        baked_dict: dict[str, Any] = {}
        all_block_ids = []
        if self.resource_loader:
            if hasattr(self.resource_loader, "list_all_blockstates"):
                all_block_ids = self.resource_loader.list_all_blockstates()
            elif hasattr(self.resource_loader, "list_blockstates"):
                all_block_ids = self.resource_loader.list_blockstates()

        total_blocks = max(1, len(all_block_ids))
        for idx, block_id in enumerate(all_block_ids):
            state_json = None
            if hasattr(self.resource_loader, "load_blockstate"):
                state_json = self.resource_loader.load_blockstate(block_id)
            elif hasattr(self.resource_loader, "get_blockstate"):
                state_json = self.resource_loader.get_blockstate(block_id)
            if not state_json:
                continue
            if isinstance(state_json, bytes):
                import json
                try:
                    state_json = json.loads(state_json.decode("utf-8"))
                except Exception:
                    continue

            if "variants" in state_json and isinstance(state_json["variants"], dict):
                for variant_key in state_json["variants"].keys():
                    if variant_key == "":
                        full_state = block_id
                    else:
                        full_state = f"{block_id}[{variant_key}]"
                    try:
                        baked = self.bake_block_state(full_state)
                        baked_dict[full_state] = baked
                    except Exception:
                        pass
            if idx % 20 == 0:
                yield ((idx + 1) / total_blocks, f"Baking models: {idx + 1}/{total_blocks}", baked_dict)
        yield (1.0, f"Baked {len(baked_dict)} blockstates.", baked_dict)

    def bake_all_pack_states(self) -> dict[str, Any]:
        res = {}
        for _, _, cur in self.bake_all_pack_states_iter():
            res = cur
        return res
