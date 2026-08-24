"""
Multi-layer Resource Pack and Base JAR Stack Manager.
Supports cascading fallback lookup across prioritized Resource Packs, Mod JARs, and Minecraft Vanilla JARs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .resource_pack import ZipResourcePack, get_pack_hash
from ..mc_baker.resource_loader import JarResourceLoader
from ..system.menu_config import get_enabled_pack_entries


class ResourcePackStack:
    """
    Manages a prioritized hierarchy of resource packs, mod JARs, and vanilla JARs.
    Lookups for textures, models, and blockstates cascade from top to bottom.
    """

    def __init__(self, pack_sources: Optional[List[Union[str, Path, ZipResourcePack]]] = None):
        self.packs: List[ZipResourcePack] = []
        self._loaders: List[JarResourceLoader] = []

        if pack_sources:
            for src in pack_sources:
                self.add_source(src)

    @property
    def stack_hash(self) -> str:
        """Return combined hash representing all packs and their order in this stack."""
        import hashlib
        combined = ":".join(p.pack_hash for p in self.packs if p and p.pack_hash)
        return hashlib.md5(combined.encode("utf-8")).hexdigest() if combined else "empty_stack"


    def add_source(self, source: Union[str, Path, ZipResourcePack]) -> Optional[ZipResourcePack]:
        """Add a resource pack or JAR archive/directory to the bottom of this stack."""
        try:
            if isinstance(source, ZipResourcePack):
                pack = source
            else:
                p = Path(source)
                if not p.exists():
                    return None
                pack = ZipResourcePack(str(p), use_cache=True)

            self.packs.append(pack)
            loader = JarResourceLoader(pack.extract_dir or pack.zip_path)
            self._loaders.append(loader)
            return pack
        except Exception as e:
            print(f"[MoziToolKit] Warning: Failed to add pack source '{source}': {e}")
            return None

    def get_texture_info(self, base_name: str, namespace: str = "minecraft") -> Optional[dict]:
        """
        Query texture information across the prioritized pack stack.
        Returns the first matching texture info dict, or None if missing from all packs.
        """
        if not base_name:
            return None

        # Cascade through packs in priority order
        for pack in self.packs:
            info = pack.get_texture_info(base_name, namespace=namespace)
            if info and info.get("albedo") and Path(info["albedo"]).exists():
                return info

        return None

    def get_composite_loader(self) -> Optional[JarResourceLoader]:
        """
        Build a chained JarResourceLoader linked through `fallback_loader` attributes
        reflecting the exact priority order of this stack.
        """
        if not self._loaders:
            return None

        # Build fallback chain from bottom to top
        current_fallback: Optional[JarResourceLoader] = None
        for loader in reversed(self._loaders):
            chained = JarResourceLoader(loader.pack_path, fallback_loader=current_fallback)
            current_fallback = chained

        return current_fallback

    def list_all_namespaces(self) -> List[str]:
        """List all unique resource namespaces found across all active packs in the stack."""
        namespaces = set()
        for pack in self.packs:
            for (ns, _key) in pack.texture_path_index.keys():
                namespaces.add(ns)
            for (ns, _key) in pack.texture_index.keys():
                namespaces.add(ns)
        ns_list = sorted(namespaces)
        if "minecraft" in ns_list:
            ns_list.remove("minecraft")
            ns_list.insert(0, "minecraft")
        return ns_list

    def list_all_blockstates(self) -> List[str]:
        """Aggregate all available blockstate identifiers across all packs in stack."""
        states = set()
        for loader in self._loaders:
            states.update(loader.list_all_blockstates())
        return sorted(states)


def get_configured_pack_stack(primary_source: Optional[Union[str, Path, ZipResourcePack]] = None) -> ResourcePackStack:
    """
    Build a complete ResourcePackStack starting with the primary source (if provided)
    followed by all active/enabled packs from user preferences in priority order.
    """
    sources: List[Union[str, Path, ZipResourcePack]] = []

    if primary_source:
        sources.append(primary_source)

    # Read enabled fallback packs configured in user preferences
    entries = get_enabled_pack_entries()
    for entry in entries:
        p_str = entry.get("path", "").strip()
        if p_str and Path(p_str).exists():
            # Avoid duplicate if primary_source points to the exact same file
            if primary_source:
                prim_path = Path(primary_source.zip_path if isinstance(primary_source, ZipResourcePack) else primary_source)
                try:
                    if Path(p_str).resolve() == prim_path.resolve():
                        continue
                except Exception:
                    pass
            sources.append(p_str)

    return ResourcePackStack(sources)


def get_pack_stack_fingerprint(primary_source: Optional[Union[str, Path, ZipResourcePack]] = None) -> tuple[str, ...]:
    """
    Return a hashable tuple representing the current configured pack stack sources.
    Used for efficient cache invalidation without rebuilding loader hierarchies.
    """
    sources: List[str] = []
    if primary_source:
        prim_path = Path(primary_source.zip_path if isinstance(primary_source, ZipResourcePack) else primary_source)
        try:
            sources.append(str(prim_path.resolve()))
        except Exception:
            sources.append(str(prim_path))

    entries = get_enabled_pack_entries()
    for entry in entries:
        p_str = entry.get("path", "").strip()
        if p_str:
            p = Path(p_str)
            if p.exists():
                try:
                    res_path = str(p.resolve())
                except Exception:
                    res_path = str(p)
                if sources and res_path == sources[0]:
                    continue
                sources.append(res_path)

    return tuple(sources)

