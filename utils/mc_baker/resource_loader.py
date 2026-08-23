"""
Resource Loader for Minecraft JAR files, ZIP resource packs, and directories.
Provides fast in-memory extraction and caching of blockstates and model JSONs.
"""

from __future__ import annotations
import os
import json
import zipfile
from pathlib import Path
from typing import Optional, Any, Union


class JarResourceLoader:
    def __init__(
        self,
        pack_path: Optional[Union[str, Path]] = None,
        fallback_loader: Optional[JarResourceLoader] = None
    ):
        self.pack_path: Optional[Path] = Path(pack_path) if pack_path else None
        self.fallback_loader: Optional[JarResourceLoader] = fallback_loader
        self._zip_file: Optional[zipfile.ZipFile] = None
        self._blockstate_cache: dict[str, dict[str, Any]] = {}
        self._model_cache: dict[str, dict[str, Any]] = {}
        self._file_index: set[str] = set()

        if self.pack_path and self.pack_path.exists():
            self._init_source()

    def set_source(self, pack_path: Union[str, Path]):
        if self._zip_file:
            try:
                self._zip_file.close()
            except Exception:
                pass
            self._zip_file = None

        self.pack_path = Path(pack_path)
        self._blockstate_cache.clear()
        self._model_cache.clear()
        self._file_index.clear()
        self._init_source()

    def _init_source(self):
        if not self.pack_path or not self.pack_path.exists():
            return

        if self.pack_path.is_file() and (self.pack_path.suffix.lower() in ('.jar', '.zip')):
            self._zip_file = zipfile.ZipFile(self.pack_path, 'r')
            self._file_index = set(self._zip_file.namelist())
        elif self.pack_path.is_dir():
            for p in self.pack_path.rglob("*.json"):
                rel = p.relative_to(self.pack_path).as_posix()
                self._file_index.add(rel)

    def load_blockstate(self, block_id: str) -> Optional[dict[str, Any]]:
        """
        Load blockstate JSON by identifier, e.g. 'minecraft:oak_stairs' or 'oak_stairs'.
        """
        if ":" in block_id:
            namespace, name = block_id.split(":", 1)
        else:
            namespace, name = "minecraft", block_id

        cache_key = f"{namespace}:{name}"
        if cache_key in self._blockstate_cache:
            return self._blockstate_cache[cache_key]

        rel_path = f"assets/{namespace}/blockstates/{name}.json"
        data = self._read_json(rel_path)
        if data is None and self.fallback_loader is not None:
            data = self.fallback_loader.load_blockstate(block_id)

        if data is not None:
            self._blockstate_cache[cache_key] = data
        return data

    def load_model(self, model_id: str) -> Optional[dict[str, Any]]:
        """
        Load model JSON by identifier, e.g. 'minecraft:block/oak_stairs' or 'block/stairs'.
        """
        if ":" in model_id:
            namespace, path = model_id.split(":", 1)
        else:
            namespace, path = "minecraft", model_id

        cache_key = f"{namespace}:{path}"
        if cache_key in self._model_cache:
            return self._model_cache[cache_key]

        # Normalise path: block/stairs -> assets/minecraft/models/block/stairs.json
        if not path.startswith("models/"):
            rel_path = f"assets/{namespace}/models/{path}.json"
        else:
            rel_path = f"assets/{namespace}/{path}.json"

        data = self._read_json(rel_path)
        if data is None and self.fallback_loader is not None:
            data = self.fallback_loader.load_model(model_id)

        if data is not None:
            self._model_cache[cache_key] = data
        return data

    def list_all_blockstates(self) -> list[str]:
        """List all available blockstate identifiers in the resource pack and fallback."""
        states = set()
        for path in self._file_index:
            parts = Path(path).parts
            if len(parts) >= 4 and parts[0] == "assets" and parts[2] == "blockstates" and path.endswith(".json"):
                ns = parts[1]
                stem = "/".join(parts[3:])[:-5]
                states.add(f"{ns}:{stem}")
        if self.fallback_loader:
            states.update(self.fallback_loader.list_all_blockstates())
        return sorted(states)

    def list_all_models(self) -> list[str]:
        """List all available model identifiers in the resource pack and fallback."""
        models = set()
        for path in self._file_index:
            parts = Path(path).parts
            if len(parts) >= 4 and parts[0] == "assets" and parts[2] == "models" and path.endswith(".json"):
                ns = parts[1]
                subpath = "/".join(parts[3:])[:-5]
                models.add(f"{ns}:{subpath}")
        if self.fallback_loader:
            models.update(self.fallback_loader.list_all_models())
        return sorted(models)

    def _read_json(self, rel_path: str) -> Optional[dict[str, Any]]:
        if self._zip_file:
            if rel_path in self._file_index:
                try:
                    raw_bytes = self._zip_file.read(rel_path)
                    return json.loads(raw_bytes.decode('utf-8'))
                except Exception:
                    return None
            return None
        elif self.pack_path and self.pack_path.is_dir():
            full_path = self.pack_path / rel_path
            if full_path.exists() and full_path.is_file():
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception:
                    return None
        return None

    def close(self):
        if self._zip_file:
            try:
                self._zip_file.close()
            except Exception:
                pass
            self._zip_file = None
        if self.fallback_loader:
            self.fallback_loader.close()
