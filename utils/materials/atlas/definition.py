"""
Data-Driven Atlas Definition & Builtin Fallback Registry.
Parses Minecraft 1.20+ `assets/<namespace>/atlases/*.json` definitions, and provides
an authoritative built-in fallback registry for legacy client JARs (1.12 - 1.19.2) and custom packs.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

logger = logging.getLogger("MoziToolKit.Atlas.Definition")


class AtlasSource:
    """Base class for sources inside an atlas JSON definition."""
    def __init__(self, source_type: str):
        self.source_type = source_type

    def matches(self, texture_path: str, namespace: str = "minecraft") -> Optional[str]:
        """
        Check if a relative texture path (relative to `assets/<ns>/textures/`, e.g. 'block/stone.png')
        matches this source.
        Returns:
            canonical sprite name (e.g. 'block/stone' or 'entity/conduit/conduit') if matched, else None.
        """
        return None


class DirectoryAtlasSource(AtlasSource):
    """minecraft:directory - includes all textures in a folder with an optional sprite prefix."""
    def __init__(self, source: str, prefix: str = ""):
        super().__init__("minecraft:directory")
        self.source = source.strip("/").lower()
        self.prefix = prefix.lower()

    def matches(self, texture_path: str, namespace: str = "minecraft") -> Optional[str]:
        clean = texture_path.replace("\\", "/").strip("/").lower()
        if "textures/" in clean:
            clean = clean.split("textures/", 1)[1].strip("/")
        if clean.endswith((".png", ".png.mcmeta")):
            clean = clean.removesuffix(".png.mcmeta").removesuffix(".png")
        if clean.endswith(("_n", "_s")):
            clean = clean[:-2]

        if not self.source:
            # Matches root textures
            return f"{self.prefix}{clean}"

        if clean == self.source or clean.startswith(f"{self.source}/"):
            rel_sub = clean[len(self.source):].lstrip("/")
            if rel_sub:
                return f"{self.prefix}{rel_sub}"
            else:
                stem = self.source.split("/")[-1]
                return f"{self.prefix}{stem}"
        return None


class SingleAtlasSource(AtlasSource):
    """minecraft:single - includes a single specific texture resource."""
    def __init__(self, resource: str, sprite: Optional[str] = None):
        super().__init__("minecraft:single")
        self.resource = resource.strip("/").lower()
        self.sprite = sprite.lower() if sprite else None

    def matches(self, texture_path: str, namespace: str = "minecraft") -> Optional[str]:
        clean = texture_path.replace("\\", "/").strip("/").lower()
        if "textures/" in clean:
            clean = clean.split("textures/", 1)[1].strip("/")
        if clean.endswith((".png", ".png.mcmeta")):
            clean = clean.removesuffix(".png.mcmeta").removesuffix(".png")
        if clean.endswith(("_n", "_s")):
            clean = clean[:-2]

        res_clean = self.resource
        res_ns = "minecraft"
        if ":" in res_clean:
            res_ns, res_clean = res_clean.split(":", 1)
        if "textures/" in res_clean:
            res_clean = res_clean.split("textures/", 1)[1].strip("/")

        if namespace == res_ns and (clean == res_clean or clean.removeprefix("textures/") == res_clean):
            return self.sprite if self.sprite else res_clean
        return None


class FilterAtlasSource(AtlasSource):
    """minecraft:filter - excludes textures matching a pattern."""
    def __init__(self, namespace_pattern: Optional[str] = None, path_pattern: Optional[str] = None):
        super().__init__("minecraft:filter")
        self.namespace_pattern = re.compile(namespace_pattern) if namespace_pattern else None
        self.path_pattern = re.compile(path_pattern) if path_pattern else None

    def is_filtered(self, texture_path: str, namespace: str = "minecraft") -> bool:
        clean = texture_path.replace("\\", "/").strip("/").lower()
        if self.namespace_pattern and self.namespace_pattern.search(namespace):
            return True
        if self.path_pattern and self.path_pattern.search(clean):
            return True
        return False


class PalettedPermutationsAtlasSource(AtlasSource):
    """minecraft:paletted_permutations - generates palette permutations dynamically."""
    def __init__(
        self,
        palette_key: str,
        permutations: dict[str, str],
        textures: list[str],
    ):
        super().__init__("minecraft:paletted_permutations")
        self.palette_key = palette_key
        self.permutations = permutations
        self.textures = textures


class AtlasDefinition:
    """Encapsulates a named Atlas (e.g. 'minecraft:blocks') and its sources."""
    def __init__(self, atlas_id: str, sources: Optional[List[AtlasSource]] = None, is_builtin: bool = False):
        self.atlas_id = atlas_id.lower()
        if ":" not in self.atlas_id:
            self.namespace = "minecraft"
            self.name = self.atlas_id
            self.canonical_id = f"minecraft:{self.atlas_id}"
        else:
            self.namespace, self.name = self.atlas_id.split(":", 1)
            self.canonical_id = self.atlas_id
        self.sources: List[AtlasSource] = sources or []
        self.is_builtin = is_builtin

    def add_source(self, source: AtlasSource) -> None:
        self.sources.append(source)

    def match_texture(self, texture_path: str, namespace: str = "minecraft") -> Optional[str]:
        """
        Check if a texture matches any source in this Atlas definition.
        Returns:
            sprite name (e.g. 'block/stone') if matched and not filtered, else None.
        """
        matched_sprite = None
        # Evaluate sources in order
        for src in self.sources:
            if isinstance(src, FilterAtlasSource):
                if src.is_filtered(texture_path, namespace):
                    return None
            elif isinstance(src, (DirectoryAtlasSource, SingleAtlasSource)):
                res = src.matches(texture_path, namespace)
                if res is not None:
                    matched_sprite = res

        return matched_sprite


class BuiltinAtlasRegistry:
    """Authoritative built-in fallback definitions for all 14 standard Minecraft atlases."""

    @staticmethod
    def get_default_atlases() -> dict[str, AtlasDefinition]:
        """Build and return the complete set of default standard Minecraft atlas definitions."""
        atlases: dict[str, AtlasDefinition] = {}

        # 1. blocks
        blocks = AtlasDefinition("minecraft:blocks", is_builtin=True)
        blocks.add_source(DirectoryAtlasSource(source="block", prefix="block/"))
        blocks.add_source(DirectoryAtlasSource(source="entity/conduit", prefix="entity/conduit/"))
        blocks.add_source(SingleAtlasSource("minecraft:entity/bell/bell_body", "entity/bell/bell_body"))
        blocks.add_source(SingleAtlasSource("minecraft:entity/enchantment/enchanting_table_book", "entity/enchantment/enchanting_table_book"))
        atlases["minecraft:blocks"] = blocks

        # 2. items
        items = AtlasDefinition("minecraft:items", is_builtin=True)
        items.add_source(DirectoryAtlasSource(source="item", prefix="item/"))
        atlases["minecraft:items"] = items

        # 3. armor_trims
        trims = AtlasDefinition("minecraft:armor_trims", is_builtin=True)
        trims.add_source(DirectoryAtlasSource(source="trims", prefix="trims/"))
        trims.add_source(DirectoryAtlasSource(source="entity/trims", prefix="trims/"))
        atlases["minecraft:armor_trims"] = trims

        # 4. chests
        chests = AtlasDefinition("minecraft:chests", is_builtin=True)
        chests.add_source(DirectoryAtlasSource(source="entity/chest", prefix="entity/chest/"))
        atlases["minecraft:chests"] = chests

        # 5. shulker_boxes
        shulker = AtlasDefinition("minecraft:shulker_boxes", is_builtin=True)
        shulker.add_source(DirectoryAtlasSource(source="entity/shulker", prefix="entity/shulker/"))
        atlases["minecraft:shulker_boxes"] = shulker

        # 6. banner_patterns
        banner = AtlasDefinition("minecraft:banner_patterns", is_builtin=True)
        banner.add_source(DirectoryAtlasSource(source="entity/banner", prefix="entity/banner/"))
        atlases["minecraft:banner_patterns"] = banner

        # 7. shield_patterns
        shield = AtlasDefinition("minecraft:shield_patterns", is_builtin=True)
        shield.add_source(DirectoryAtlasSource(source="entity/shield", prefix="entity/shield/"))
        atlases["minecraft:shield_patterns"] = shield

        # 8. decorated_pot
        pot = AtlasDefinition("minecraft:decorated_pot", is_builtin=True)
        pot.add_source(DirectoryAtlasSource(source="entity/decorated_pot", prefix="entity/decorated_pot/"))
        atlases["minecraft:decorated_pot"] = pot

        # 9. paintings
        paintings = AtlasDefinition("minecraft:paintings", is_builtin=True)
        paintings.add_source(DirectoryAtlasSource(source="painting", prefix=""))
        atlases["minecraft:paintings"] = paintings

        # 10. particles
        particles = AtlasDefinition("minecraft:particles", is_builtin=True)
        particles.add_source(DirectoryAtlasSource(source="particle", prefix=""))
        atlases["minecraft:particles"] = particles

        # 11. celestials
        celestials = AtlasDefinition("minecraft:celestials", is_builtin=True)
        celestials.add_source(DirectoryAtlasSource(source="environment/celestial", prefix=""))
        atlases["minecraft:celestials"] = celestials

        # 12. gui
        gui = AtlasDefinition("minecraft:gui", is_builtin=True)
        gui.add_source(DirectoryAtlasSource(source="gui/sprites", prefix=""))
        gui.add_source(DirectoryAtlasSource(source="mob_effect", prefix="mob_effect/"))
        atlases["minecraft:gui"] = gui

        # 13. map_decorations
        map_dec = AtlasDefinition("minecraft:map_decorations", is_builtin=True)
        map_dec.add_source(DirectoryAtlasSource(source="map/decorations", prefix=""))
        atlases["minecraft:map_decorations"] = map_dec

        # 14. entities (catch-all for remaining entities and armor models)
        entities = AtlasDefinition("minecraft:entities", is_builtin=True)
        entities.add_source(DirectoryAtlasSource(source="entity", prefix="entity/"))
        entities.add_source(DirectoryAtlasSource(source="models/armor", prefix="models/armor/"))
        atlases["minecraft:entities"] = entities

        return atlases


class AtlasDefinitionParser:
    """Parses atlas JSON definitions from a ResourcePackStack with automatic fallback to BuiltinAtlasRegistry."""

    @staticmethod
    def parse_source_dict(source_data: dict[str, Any]) -> Optional[AtlasSource]:
        stype = source_data.get("type", "")
        if stype in ("minecraft:directory", "directory"):
            return DirectoryAtlasSource(
                source=source_data.get("source", ""),
                prefix=source_data.get("prefix", ""),
            )
        elif stype in ("minecraft:single", "single"):
            return SingleAtlasSource(
                resource=source_data.get("resource", ""),
                sprite=source_data.get("sprite"),
            )
        elif stype in ("minecraft:filter", "filter"):
            return FilterAtlasSource(
                namespace_pattern=source_data.get("namespace"),
                path_pattern=source_data.get("path"),
            )
        elif stype in ("minecraft:paletted_permutations", "paletted_permutations"):
            return PalettedPermutationsAtlasSource(
                palette_key=source_data.get("palette_key", ""),
                permutations=source_data.get("permutations", {}),
                textures=source_data.get("textures", []),
            )
        return None

    @classmethod
    def load_from_pack_stack(cls, pack_stack: Any) -> dict[str, AtlasDefinition]:
        """
        Scan all packs in pack_stack (bottom to top, so top can override or augment).
        If no atlas JSONs are found across all packs, return BuiltinAtlasRegistry.get_default_atlases().
        """
        atlases: dict[str, AtlasDefinition] = {}
        found_any_atlas = False

        if pack_stack and hasattr(pack_stack, "packs"):
            # Traverse bottom to top so top packs override / append sources
            for pack in reversed(pack_stack.packs):
                if not pack or not pack.extract_dir:
                    continue
                assets_dir = pack.extract_dir / "assets"
                if not assets_dir.exists():
                    continue

                for ns_dir in assets_dir.iterdir():
                    if not ns_dir.is_dir():
                        continue
                    ns = ns_dir.name.lower().strip()
                    atlases_dir = ns_dir / "atlases"
                    if not atlases_dir.exists() or not atlases_dir.is_dir():
                        continue

                    for atlas_file in atlases_dir.glob("*.json"):
                        atlas_name = atlas_file.stem.lower()
                        atlas_id = f"{ns}:{atlas_name}"
                        found_any_atlas = True

                        try:
                            with open(atlas_file, "r", encoding="utf-8") as fp:
                                data = json.load(fp)
                            sources_list = data.get("sources", [])
                            if atlas_id not in atlases:
                                atlases[atlas_id] = AtlasDefinition(atlas_id, is_builtin=False)
                            for s_data in sources_list:
                                parsed_s = cls.parse_source_dict(s_data)
                                if parsed_s:
                                    atlases[atlas_id].add_source(parsed_s)
                        except Exception as e:
                            logger.warning(f"Failed to parse atlas definition '{atlas_file}': {e}")

        if not found_any_atlas:
            logger.debug("No atlases/*.json discovered in pack stack. Falling back to BuiltinAtlasRegistry.")
            return BuiltinAtlasRegistry.get_default_atlases()

        # Ensure that if custom atlases exist, standard missing entries can still fall back if needed
        default_atlases = BuiltinAtlasRegistry.get_default_atlases()
        for def_id, def_atlas in default_atlases.items():
            if def_id not in atlases:
                atlases[def_id] = def_atlas

        return atlases
