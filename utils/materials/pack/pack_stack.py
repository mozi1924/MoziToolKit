"""
Multi-layer Resource Pack and Base JAR Stack Manager.
Supports cascading fallback lookup across prioritized Resource Packs, Mod JARs, and Minecraft Vanilla JARs.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, Iterator, Callable

from .resource_pack import ZipResourcePack, get_pack_hash
from ...mc_baker.resource_loader import JarResourceLoader
from ...config import get_enabled_pack_entries

logger = logging.getLogger("MoziToolKit.Materials.PackStack")



class ResourcePackStack:
    """
    Manages a prioritized hierarchy of resource packs, mod JARs, and vanilla JARs.
    Lookups for textures, models, and blockstates cascade from top to bottom.
    Supports granular per-channel PBR composition (Albedo, Normal, Specular).
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
            loader = JarResourceLoader(pack.zip_path)
            self._loaders.append(loader)
            return pack
        except Exception as e:
            logger.warning(f"Failed to add pack source '{source}': {e}")
            return None


    def get_texture_info(self, base_name: str, namespace: str = "minecraft") -> Optional[dict]:
        """
        Query texture information across the prioritized pack stack with granular
        per-channel PBR composition (Albedo, Normal _n, Specular _s).
        Cascades from top (pack 0) to bottom (pack N) independently for each channel.
        """
        if not base_name or not self.packs:
            return None

        composite: dict[str, Any] = {
            "namespace": namespace,
            "texture_name": None,
            "texture_key": None,
            "albedo": None,
            "albedo_mcmeta": None,
            "normal": None,
            "normal_mcmeta": None,
            "specular": None,
            "specular_mcmeta": None,
        }

        # Cascade through packs in priority order
        for pack in self.packs:
            info = pack.get_texture_info(base_name, namespace=namespace)
            if not info:
                continue

            if composite["texture_name"] is None:
                composite["namespace"] = info.get("namespace", namespace)
                composite["texture_name"] = info.get("texture_name", base_name)
                composite["texture_key"] = info.get("texture_key", base_name)

            if composite["albedo"] is None and info.get("albedo") and Path(info["albedo"]).exists():
                composite["albedo"] = info["albedo"]
                composite["albedo_mcmeta"] = info.get("albedo_mcmeta")

            if composite["normal"] is None and info.get("normal") and Path(info["normal"]).exists():
                composite["normal"] = info["normal"]
                composite["normal_mcmeta"] = info.get("normal_mcmeta")

            if composite["specular"] is None and info.get("specular") and Path(info["specular"]).exists():
                composite["specular"] = info["specular"]
                composite["specular_mcmeta"] = info.get("specular_mcmeta")

            # If all three channels are resolved, stop early
            if composite["albedo"] is not None and composite["normal"] is not None and composite["specular"] is not None:
                break

        if composite["albedo"] is not None or composite["normal"] is not None or composite["specular"] is not None:
            from ..specialized import is_firefly_bush, handle_firefly_bush_texture_info
            if is_firefly_bush(base_name):
                syn = handle_firefly_bush_texture_info(self, composite, namespace=namespace)
                if syn:
                    return syn
            return composite

        return None

    def get_all_composite_textures(self) -> dict[tuple[str, str], dict]:
        """
        Collect all unique texture entries across all active packs in this stack,
        synthesizing composite per-channel PBR data (Albedo, Normal, Specular) for each.

        A PBR-only overlay is deliberately *not* a texture replacement.  Each
        channel is resolved from the first layer that physically supplies that
        channel, so an ``ore_n``/``ore_s`` file in the top pack is composited
        over an albedo found in a lower PBR pack or the vanilla JAR.  Atlas
        generation consumes this composite directly: it never turns a missing
        albedo into a transparent tile merely because a higher layer has a PBR
        companion map.
        Returns mapping from (namespace, texture_key) -> composite_texture_info_dict.
        """
        all_keys: set[tuple[str, str]] = set()
        for pack in self.packs:
            for (ns, path_key) in pack.texture_path_index.keys():
                all_keys.add((ns, path_key))

        composite_map: dict[tuple[str, str], dict] = {}
        for (ns, path_key) in sorted(all_keys):
            entry: dict[str, Any] = {
                "namespace": ns,
                "texture_name": None,
                "texture_key": path_key,
                "albedo": None,
                "albedo_mcmeta": None,
                "normal": None,
                "normal_mcmeta": None,
                "specular": None,
                "specular_mcmeta": None,
            }

            for pack in self.packs:
                info = pack.texture_path_index.get((ns, path_key))
                if not info:
                    continue

                if entry["texture_name"] is None:
                    entry["texture_name"] = info.get("texture_name")

                if entry["albedo"] is None and info.get("albedo") and Path(info["albedo"]).exists():
                    entry["albedo"] = info["albedo"]
                    entry["albedo_mcmeta"] = info.get("albedo_mcmeta")

                if entry["normal"] is None and info.get("normal") and Path(info["normal"]).exists():
                    entry["normal"] = info["normal"]
                    entry["normal_mcmeta"] = info.get("normal_mcmeta")

                if entry["specular"] is None and info.get("specular") and Path(info["specular"]).exists():
                    entry["specular"] = info["specular"]
                    entry["specular_mcmeta"] = info.get("specular_mcmeta")

                if entry["albedo"] is not None and entry["normal"] is not None and entry["specular"] is not None:
                    break

            if entry["albedo"] is not None or entry["normal"] is not None or entry["specular"] is not None:
                composite_map[(ns, path_key)] = entry

        from ..specialized import handle_firefly_bush_composite_map
        handle_firefly_bush_composite_map(self, composite_map)

        return composite_map

    def get_all_models(self) -> dict[str, dict]:
        """
        Collect and merge all block and item model JSON definitions across the pack stack.
        Cascades from bottom (lowest priority) to top (highest priority),
        ensuring top-layer packs cleanly override lower-layer models.
        """
        merged_models: dict[str, dict] = {}
        for pack in reversed(self.packs):
            if hasattr(pack, "get_all_models"):
                merged_models.update(pack.get_all_models())
        return merged_models

    def get_baked_atlas_dir(self, yefira_only: bool = False) -> Path:
        """Get the persistent cache directory for this stack."""
        from .resource_pack import get_cache_dir
        cache_root = get_cache_dir()
        return cache_root / self.stack_hash / ("yefira_world" if yefira_only else "full_scene")

    def is_stack_baked(self, yefira_only: bool = False) -> bool:
        """
        Check if the persistent atlas and model bake for this stack exists and is complete.
        """
        import json
        from ..constants import ATLAS_FORMAT_VERSION
        atlas_dir = self.get_baked_atlas_dir(yefira_only=yefira_only)
        mapping_path = atlas_dir / "atlas_mapping.json"
        if not mapping_path.exists():
            return False

        try:
            with open(mapping_path, "r", encoding="utf-8") as fp:
                mapping = json.load(fp)
                if (
                    mapping.get("format_version") != ATLAS_FORMAT_VERSION
                    or not mapping.get("chunks")
                    or not mapping.get("textures")
                ):
                    return False
                for chunk in mapping["chunks"]:
                    files = chunk.get("files") if isinstance(chunk, dict) else None
                    albedo = files.get("albedo") if isinstance(files, dict) else None
                    if not isinstance(albedo, str) or not (atlas_dir / albedo).is_file():
                        return False
                    for channel in ("normal", "specular", "overlay"):
                        filename = files.get(channel)
                        if filename and not (atlas_dir / filename).is_file():
                            return False
                return True
        except (OSError, json.JSONDecodeError):
            return False

    def get_baked_standalone_dir(self) -> Path:
        """Get the persistent standalone asset library cache directory for this stack."""
        from .resource_pack import get_cache_dir
        cache_root = get_cache_dir()
        return cache_root / self.stack_hash / "standalone"

    def is_standalone_baked(self) -> bool:
        """
        Check if the persistent standalone asset library for this stack exists and is complete.
        """
        import json
        from ..standalone.generator import STANDALONE_FORMAT_VERSION
        standalone_dir = self.get_baked_standalone_dir()
        mapping_path = standalone_dir / "standalone_mapping.json"
        if not mapping_path.exists():
            return False

        try:
            with open(mapping_path, "r", encoding="utf-8") as fp:
                mapping = json.load(fp)
                if (
                    mapping.get("format_version") != STANDALONE_FORMAT_VERSION
                    or mapping.get("stack_hash") != self.stack_hash
                    or not mapping.get("textures")
                ):
                    return False
                for rec in mapping["textures"].values():
                    files = rec.get("files") if isinstance(rec, dict) else None
                    if not files:
                        continue
                    albedo = files.get("albedo")
                    if albedo and not (standalone_dir / albedo).is_file():
                        return False
                    for channel in ("normal", "specular", "overlay"):
                        filename = files.get(channel)
                        if filename and not (standalone_dir / filename).is_file():
                            return False
                return True
        except (OSError, json.JSONDecodeError):
            return False

    def precompile_standalone_iter(
        self, output_dir: Optional[Union[str, Path]] = None
    ) -> Iterator[Tuple[float, str, Optional[dict]]]:
        """Iteratively precompile and build the standalone asset library for this pack stack."""
        from ..standalone.generator import StandaloneGenerator
        target_dir = Path(output_dir) if output_dir else self.get_baked_standalone_dir()
        gen = StandaloneGenerator(fallback_stack=self)
        yield from gen.build_iter(target_dir)

    def precompile_standalone(
        self, output_dir: Optional[Union[str, Path]] = None, progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> dict:
        """Precompile and build the standalone asset library for this pack stack."""
        final_res = {}
        for frac, msg, outputs in self.precompile_standalone_iter(output_dir=output_dir):
            if progress_callback:
                try:
                    progress_callback(frac, msg)
                except Exception:
                    pass
            if outputs:
                final_res = outputs
        return final_res

    def precompile_atlas_iter(
        self,
        output_dir: Optional[Union[str, Path]] = None,
        yefira_only: bool = False,
    ) -> Iterator[Tuple[float, str, Optional[dict]]]:
        """Iteratively precompile and build the atlas cache for this pack stack."""
        from ..atlas.generator import AtlasGenerator
        from ..constants import (
            ATLAS_CATEGORY_BLOCKS,
            ATLAS_CATEGORY_ITEMS,
            ATLAS_CATEGORY_ENTITIES,
            ATLAS_CATEGORY_CHEST,
            ATLAS_CATEGORY_SHULKER_BOXES,
            ATLAS_CATEGORY_BANNER_PATTERNS,
            ATLAS_CATEGORY_DECORATED_POT,
        )
        target_dir = Path(output_dir) if output_dir else self.get_baked_atlas_dir(yefira_only=yefira_only)
        yefira_categories = {
            ATLAS_CATEGORY_BLOCKS,
            ATLAS_CATEGORY_ITEMS,
            ATLAS_CATEGORY_ENTITIES,
            ATLAS_CATEGORY_CHEST,
            ATLAS_CATEGORY_SHULKER_BOXES,
            ATLAS_CATEGORY_BANNER_PATTERNS,
            ATLAS_CATEGORY_DECORATED_POT,
        } if yefira_only else None
        gen = AtlasGenerator(fallback_stack=self, included_categories=yefira_categories)
        yield from gen.build_iter(target_dir)

    def precompile_atlas(
        self,
        output_dir: Optional[Union[str, Path]] = None,
        yefira_only: bool = False,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> dict:
        """Precompile and build the atlas cache for this pack stack."""
        final_res = {}
        for frac, msg, outputs in self.precompile_atlas_iter(output_dir=output_dir, yefira_only=yefira_only):
            if progress_callback:
                try:
                    progress_callback(frac, msg)
                except Exception:
                    pass
            if outputs:
                final_res = outputs
        return final_res

    def get_baked_models_dir(self) -> Path:
        """Get the persistent baked models cache directory for this stack."""
        from .resource_pack import get_cache_dir
        cache_root = get_cache_dir()
        return cache_root / self.stack_hash / "models"

    def is_models_baked(self) -> bool:
        """Check if precompiled baked models manifest exists for this stack."""
        manifest_path = self.get_baked_models_dir() / "models_manifest.json"
        return manifest_path.is_file() and manifest_path.stat().st_size > 10

    def precompile_models_iter(
        self,
        output_dir: Optional[Union[str, Path]] = None,
    ) -> Iterator[Tuple[float, str, Optional[dict]]]:
        """Iteratively precompile and bake all blockstate models for this pack stack."""
        from ...mc_baker import StateBaker
        target_dir = Path(output_dir) if output_dir else self.get_baked_models_dir()
        target_file = target_dir / "models_manifest.json"

        yield (0.02, "Initializing model baker across pack stack...", None)

        composite_loader = self.get_composite_loader()
        baker = StateBaker(jar_path=None)
        baker.resource_loader = composite_loader
        if composite_loader:
            baker.model_parser.model_loader_fn = composite_loader.load_model
            baker.state_resolver.blockstate_loader_fn = composite_loader.load_blockstate

        count = 0
        for frac, msg, res_count in baker.save_precompiled_manifest_iter(target_file):
            if res_count is not None:
                count = res_count
            yield (0.02 + 0.98 * frac, msg, None)

        results = {
            "models_count": count,
            "manifest_file": target_file,
        }
        yield (1.0, f"Precompiled {count} blockstate models.", results)

    def precompile_models(
        self,
        output_dir: Optional[Union[str, Path]] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> dict:
        """Precompile and bake all blockstate models for this pack stack."""
        final_results = {}
        for frac, msg, res in self.precompile_models_iter(output_dir=output_dir):
            if progress_callback:
                try:
                    progress_callback(frac, msg)
                except Exception:
                    pass
            if res is not None:
                final_results = res
        return final_results

    def load_precompiled_models(self, target_dir: Optional[Union[str, Path]] = None) -> dict:
        """Load all precompiled BakedModel objects for this stack into memory."""
        from ...mc_baker import StateBaker
        manifest_path = (Path(target_dir) if target_dir else self.get_baked_models_dir()) / "models_manifest.json"
        baker = StateBaker(jar_path=None)
        if manifest_path.is_file():
            baker.load_precompiled_manifest(manifest_path)
            return baker._bake_cache
        return {}

    def get_baked_colormaps_dir(self) -> Path:
        """Get the persistent colormaps cache directory for this stack."""
        from .resource_pack import get_cache_dir
        cache_root = get_cache_dir()
        return cache_root / self.stack_hash / "colormaps"

    def is_colormaps_baked(self) -> bool:
        """Check if precompiled colormaps exist for this stack."""
        cm_dir = self.get_baked_colormaps_dir()
        return cm_dir.is_dir() and any(cm_dir.glob("*.png"))

    def get_colormap_path(self, name: str = "grass", namespace: str = "minecraft") -> Optional[Path]:
        """Cascading lookup for colormap path (grass, foliage, dry_foliage) across pack stack."""
        clean_name = name.lower().removesuffix(".png")
        for pack in self.packs:
            p = pack.get_colormap_path(name=clean_name, namespace=namespace)
            if p and p.is_file():
                return p
        return None

    def get_all_colormaps(self) -> dict[str, Path]:
        """Get all composite colormaps across the pack stack with cascading priority."""
        colormaps = {}
        for cm_name in ("grass", "foliage", "dry_foliage"):
            p = self.get_colormap_path(cm_name)
            if p:
                colormaps[cm_name] = p
        return colormaps

    def extract_colormaps(self, output_dir: Optional[Union[str, Path]] = None) -> dict[str, Path]:
        """Extract and cache all active colormaps for this stack into target directory."""
        import shutil
        target_dir = Path(output_dir) if output_dir else self.get_baked_colormaps_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        colormaps = self.get_all_colormaps()
        extracted = {}
        for name, src_path in colormaps.items():
            dst = target_dir / f"{name}.png"
            if src_path.resolve() != dst.resolve():
                shutil.copy2(src_path, dst)
            extracted[name] = dst
        return extracted

    def precompile_colormaps_iter(
        self, output_dir: Optional[Union[str, Path]] = None
    ) -> Iterator[Tuple[float, str, Optional[dict]]]:
        """Iteratively extract and precompile colormaps for this pack stack."""
        yield (0.1, "Searching and extracting active colormaps...", None)
        extracted = self.extract_colormaps(output_dir)
        results = {
            "colormaps": {k: str(v) for k, v in extracted.items()},
            "colormaps_count": len(extracted),
        }
        yield (1.0, f"Extracted {len(extracted)} active colormaps (grass, foliage, dry_foliage).", results)

    def get_biome_data(self, biome_id: str, namespace: str = "minecraft") -> Optional[dict]:
        """
        Query biome metadata across the stack, sampling from active stack colormaps.
        Falls back to canonical 26.2 biome presets if not fully specified in the pack.
        """
        clean_id = biome_id.lower().removeprefix("minecraft:")
        biome_json = None
        for pack in self.packs:
            bj = pack.get_biome_json(clean_id, namespace=namespace)
            if bj:
                biome_json = bj
                break

        from ..biome import sample_colormap_pixel, hex_to_linear_rgba, BIOME_PALETTES
        canonical = BIOME_PALETTES.get(clean_id.upper(), {})
        temp = float(biome_json.get("temperature", canonical.get("temperature", 0.8))) if biome_json else float(canonical.get("temperature", 0.8))
        downfall = float(biome_json.get("downfall", canonical.get("humidity", 0.4))) if biome_json else float(canonical.get("humidity", 0.4))
        effects = biome_json.get("effects", {}) if biome_json else {}

        # Resolve active stack colormaps
        cms = self.get_all_colormaps()
        grass_img = None
        foliage_img = None
        dry_foliage_img = None

        try:
            from PIL import Image
            if "grass" in cms and cms["grass"].is_file():
                grass_img = Image.open(cms["grass"]).convert("RGB")
            if "foliage" in cms and cms["foliage"].is_file():
                foliage_img = Image.open(cms["foliage"]).convert("RGB")
            if "dry_foliage" in cms and cms["dry_foliage"].is_file():
                dry_foliage_img = Image.open(cms["dry_foliage"]).convert("RGB")
        except Exception:
            pass

        # Grass Color
        if "grass_color" in effects:
            grass_hex = effects["grass_color"].upper()
        elif grass_img:
            r, g, b = sample_colormap_pixel(grass_img, temp, downfall)
            mod = effects.get("grass_color_modifier", canonical.get("modifier", "none"))
            c_int = (int(r * 255) << 16) | (int(g * 255) << 8) | int(b * 255)
            if mod == "dark_forest":
                mod_int = ((c_int & 0xFEFEFE) + 0x28340A) >> 1
                grass_hex = f"#{mod_int:06X}"
            elif mod == "swamp":
                grass_hex = "#6A7039"
            else:
                grass_hex = f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"
        else:
            grass_hex = canonical.get("grass", "#91BD59")

        # Foliage Color
        if "foliage_color" in effects:
            foliage_hex = effects["foliage_color"].upper()
        elif foliage_img:
            r, g, b = sample_colormap_pixel(foliage_img, temp, downfall)
            foliage_hex = f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"
        else:
            foliage_hex = canonical.get("foliage", "#77AB2F")

        # Dry Foliage Color
        if "dry_foliage_color" in effects:
            dry_foliage_hex = effects["dry_foliage_color"].upper()
        elif dry_foliage_img:
            r, g, b = sample_colormap_pixel(dry_foliage_img, temp, downfall)
            dry_foliage_hex = f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"
        else:
            dry_foliage_hex = canonical.get("dry_foliage", "#A37546")

        # Water Color
        water_hex = effects.get("water_color", canonical.get("water", "#3F76E4")).upper()
        display_name = canonical.get("name", clean_id.replace("_", " ").title())

        return {
            "id": clean_id,
            "name": display_name,
            "grass_hex": grass_hex,
            "grass_linear": hex_to_linear_rgba(grass_hex),
            "foliage_hex": foliage_hex,
            "foliage_linear": hex_to_linear_rgba(foliage_hex),
            "dry_foliage_hex": dry_foliage_hex,
            "dry_foliage_linear": hex_to_linear_rgba(dry_foliage_hex),
            "water_hex": water_hex,
            "water_linear": hex_to_linear_rgba(water_hex),
            "temperature": temp,
            "humidity": downfall,
            "modifier": effects.get("grass_color_modifier", canonical.get("modifier", "none")),
        }

    def precompile_iter(
        self,
        material_mode: Optional[str] = None,
        yefira_only: bool = False,
    ) -> Iterator[Tuple[float, str, Optional[dict]]]:
        """
        Iteratively precompile all caches (Colormaps, Atlas, Models, and Standalone)
        with progress streaming.
        Yields (fraction: float, message: str, outputs: Optional[dict]).
        """
        results = {}
        # 0. Colormaps Cache (0.0 -> 0.05)
        for frac, msg, out in self.precompile_colormaps_iter():
            if out:
                results["colormaps"] = out
            yield (0.05 * frac, f"Colormaps: {msg}", None)

        if material_mode == "ATLAS":
            # Backward-compatibility branch if explicitly requested only ATLAS
            for frac, msg, out in self.precompile_atlas_iter(yefira_only=yefira_only):
                if out:
                    results["atlas"] = out
                yield (0.05 + 0.55 * frac, f"Atlas: {msg}", None)

            for frac, msg, out in self.precompile_models_iter():
                if out:
                    results["models"] = out
                yield (0.60 + 0.40 * frac, f"Models: {msg}", None)
        else:
            # Default unified bake: Both Atlas and Standalone caches (Colormaps -> Atlas -> Models -> Standalone)
            # 1. Atlas Cache (0.05 -> 0.40)
            for frac, msg, out in self.precompile_atlas_iter(yefira_only=yefira_only):
                if out:
                    results["atlas"] = out
                yield (0.05 + 0.35 * frac, f"Atlas: {msg}", None)

            # 2. Models Cache (0.40 -> 0.70)
            for frac, msg, out in self.precompile_models_iter():
                if out:
                    results["models"] = out
                yield (0.40 + 0.30 * frac, f"Models: {msg}", None)

            # 3. Standalone Cache (0.70 -> 1.00)
            for frac, msg, out in self.precompile_standalone_iter():
                if out:
                    results["standalone"] = out
                yield (0.70 + 0.30 * frac, f"Standalone: {msg}", None)

        yield (1.0, "Precompilation completed.", results)

    def precompile(
        self,
        material_mode: Optional[str] = None,
        yefira_only: bool = False,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> dict:
        """
        Precompile caches:
        By default (or if material_mode is not 'ATLAS'), precompiles both Atlas, Standalone, and Models caches.
        """
        final_results = {}
        for frac, msg, out in self.precompile_iter(material_mode=material_mode, yefira_only=yefira_only):
            if progress_callback:
                try:
                    progress_callback(frac, msg)
                except Exception:
                    pass
            if out:
                final_results = out
        return final_results

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

