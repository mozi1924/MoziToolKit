"""
Atlas Generator for Minecraft Resource Packs / JARs.
Generates size-bounded texture atlas images (Albedo, Normal, Specular) and mapping JSON.
"""

from __future__ import annotations

import sys
import os
import json
import logging
import zipfile
import shutil
import uuid
from pathlib import Path
from typing import Any, Optional, Union

logger = logging.getLogger("MoziToolKit.Atlas.Generator")


from ..constants import (
    FACE_ORDER,
    FALLBACK_TEXTURE_KEY,
    ATLAS_FORMAT_VERSION,
    ATLAS_CATEGORY_PRIORITY,
    RECT_PACKED_CATEGORIES,
    classify_texture_category,
    is_scene_blacklisted,
)
from ..biome import BiomeResolver
from ..pack.pack_stack import ResourcePackStack, get_configured_pack_stack
from ...system.dependencies import has_pillow
from ...mc_baker import StateBaker
from .image_utils import (
    Image,
    HAS_PIL,
    MAX_IMAGE_DIMENSION,
    _safe_open_image,
    _is_power_of_two,
    is_animated_texture,
    analyze_texture_transparency,
)
from .model_resolver import (
    resolve_model_textures as _resolve_model_textures_fn,
    expand_variables as _expand_variables_fn,
    get_6_faces_for_model as _get_6_faces_for_model_fn,
)
from .chunk_packer import (
    pack_rect_category_chunks,
    pack_grid_category_chunks,
    pack_animated_category_chunks,
)
from .definition import (
    AtlasDefinition,
    AtlasDefinitionParser,
    BuiltinAtlasRegistry,
    PalettedPermutationsAtlasSource,
)
from .palette_baker import PalettePermutationEngine

__all__ = [
    "AtlasGenerator",
    "is_animated_texture",
    "analyze_texture_transparency",
    "MAX_IMAGE_DIMENSION",
    "HAS_PIL",
]


class AtlasGenerator:
    """
    Parses Minecraft block models and textures from a JAR archive, ZIP file, or directory.
    Constructs deduplicated, size-bounded atlas chunks:
    - Static textures are packed once each and referenced by every matching face.
    - Each animation owns independent vertical frame-strip chunk(s).
    - Different namespaces are strictly isolated into separate chunks.
    - Native resolution is determined per-namespace via statistical mode.
    """

    def __init__(
        self,
        resource_path: Optional[Union[str, Path, ResourcePackStack]] = None,
        default_tile_size: int = 16,
        max_chunk_size: int = 4096,
        fallback_stack: Optional[ResourcePackStack] = None,
        included_categories: Optional[set[str]] = None,
        filter_scene_blacklist: bool = False,
    ):
        if isinstance(resource_path, ResourcePackStack):
            self.pack_stack = resource_path
            self.resource_path = self.pack_stack.packs[0].zip_path if (self.pack_stack.packs and self.pack_stack.packs[0].zip_path) else (self.pack_stack.packs[0].extract_dir if self.pack_stack.packs else Path("."))
        elif fallback_stack is not None:
            self.pack_stack = fallback_stack
            self.resource_path = Path(resource_path) if resource_path else (self.pack_stack.packs[0].zip_path if (self.pack_stack.packs and self.pack_stack.packs[0].zip_path) else (self.pack_stack.packs[0].extract_dir if self.pack_stack.packs else Path(".")))
        elif resource_path:
            self.resource_path = Path(resource_path)
            self.pack_stack = ResourcePackStack([self.resource_path])
        else:
            self.pack_stack = get_configured_pack_stack()
            self.resource_path = self.pack_stack.packs[0].zip_path if (self.pack_stack.packs and self.pack_stack.packs[0].zip_path) else (self.pack_stack.packs[0].extract_dir if self.pack_stack.packs else Path("."))

        self.default_tile_size = default_tile_size
        self.max_chunk_size = max_chunk_size
        self.fallback_stack = self.pack_stack
        self.included_categories = frozenset(included_categories) if included_categories else None
        self.filter_scene_blacklist = filter_scene_blacklist

        self.static_textures = {}    # clean_stem -> Image
        self.animated_textures = {}  # clean_stem -> {image: Image, mcmeta: dict}
        self.normal_textures = {}    # clean_stem -> Image
        self.specular_textures = {}  # clean_stem -> Image
        self.models = {}             # model_name -> dict JSON

        # Grouped by namespace: namespace -> {stem: data}
        self.static_by_namespace = {}
        self.animated_by_namespace = {}
        self.normal_by_namespace = {}
        self.specular_by_namespace = {}

        # Multi-category partitioned mappings: namespace -> category -> {rel_path: data}
        self.static_by_ns_cat = {}
        self.animated_by_ns_cat = {}
        self.normal_by_ns_cat = {}
        self.specular_by_ns_cat = {}

        self.block_mappings = {}     # block_id -> 6 face texture names
        self.static_materials = []   # list of static material metadata
        self.animated_materials = [] # list of animated material metadata
        self.biome_resolver = BiomeResolver()
        self.atlas_definitions: dict[str, AtlasDefinition] = {}
        self.palette_baker = PalettePermutationEngine(image_finder_fn=self._find_static_image)

        self.baker: Optional[StateBaker] = None
        try:
            composite_loader = self.pack_stack.get_composite_loader() if self.pack_stack else None
            self.baker = StateBaker(jar_path=None)
            self.baker.resource_loader = composite_loader
            if composite_loader:
                self.baker.model_parser.model_loader_fn = composite_loader.load_model
                self.baker.state_resolver.blockstate_loader_fn = composite_loader.load_blockstate
        except Exception:
            self.baker = None

    def _includes_category(self, category: str) -> bool:
        return self.included_categories is None or category in self.included_categories

    def classify_texture(self, path_or_key: str, namespace: str = "minecraft") -> tuple[str, str]:
        """Classify a texture using loaded atlas definitions with fallback heuristics.

        Returns:
            (category_name, sprite_name) e.g. ('blocks', 'block/stone') or ('armor_trims', 'trims/...')
        """
        clean = (path_or_key or "").replace("\\", "/").strip("/").lower()
        if ":" in clean:
            ns_part, clean = clean.split(":", 1)
            if not namespace or namespace == "minecraft":
                namespace = ns_part
        if "textures/" in clean:
            clean = clean.split("textures/", 1)[1].strip("/")

        # Check atlas definitions in priority order
        if self.atlas_definitions:
            for cat_key in ATLAS_CATEGORY_PRIORITY:
                for atlas_id, atlas_def in self.atlas_definitions.items():
                    if atlas_def.name == cat_key or atlas_def.atlas_id == cat_key or atlas_def.atlas_id == f"{namespace}:{cat_key}":
                        matched = atlas_def.match_texture(clean, namespace)
                        if matched is not None:
                            return atlas_def.name, matched
            for atlas_id, atlas_def in self.atlas_definitions.items():
                matched = atlas_def.match_texture(clean, namespace)
                if matched is not None:
                    return atlas_def.name, matched

        cat = classify_texture_category(clean)
        return cat, clean

    @staticmethod
    def _texture_name(namespace: str, stem: str) -> str:
        """Keep legacy vanilla names while making non-vanilla names unique."""
        stem = stem.strip("/").lower()
        namespace = namespace.lower()
        return stem if namespace == "minecraft" else f"{namespace}:{stem}"

    @staticmethod
    def _source_texture_key(texture_name: str) -> str:
        """Return the canonical resource key represented by an atlas entry."""
        if ":" in texture_name:
            namespace, stem = texture_name.split(":", 1)
        else:
            namespace, stem = "minecraft", texture_name
        if "/" in stem:
            return f"{namespace}:{stem}"
        return f"{namespace}:block/{stem}"

    def load_resources(self):
        """Load composite PNG images, mcmeta animation data, and models across all packs in the stack."""
        if Image:
            Image.init()
        if not self.pack_stack or not self.pack_stack.packs:
            return

        # 0. Load or synthesize data-driven Atlas definitions across the pack stack
        self.atlas_definitions = AtlasDefinitionParser.load_from_pack_stack(self.pack_stack)

        # 1. Load models from all packs in the stack (bottom to top, so top overrides bottom)
        self.models = self.pack_stack.get_all_models()

        # 2. Load composite textures across the entire pack stack
        composite_textures = self.pack_stack.get_all_composite_textures()
        for (ns, path_key), info in composite_textures.items():
            base_rel = path_key.strip("/")
            category, sprite_name = self.classify_texture(base_rel, ns)
            if not self._includes_category(category):
                continue
            if self.filter_scene_blacklist and is_scene_blacklisted(base_rel):
                if not (self.included_categories and category in self.included_categories):
                    continue

            if base_rel.startswith("block/"):
                clean_name = self._texture_name(ns, base_rel.removeprefix("block/"))
                base_stem = base_rel.removeprefix("block/")
            else:
                clean_name = self._texture_name(ns, base_rel)
                base_stem = base_rel

            albedo_file = info.get("albedo")
            if albedo_file and Path(albedo_file).exists():
                try:
                    img = _safe_open_image(albedo_file)
                    mcmeta = info.get("albedo_mcmeta")
                    if is_animated_texture(img, mcmeta):
                        anim_data = {"image": img, "mcmeta": mcmeta or {}}
                        self.animated_textures[clean_name] = anim_data
                        self.animated_by_namespace.setdefault(ns, {})[base_stem] = anim_data
                        self.animated_by_ns_cat.setdefault(ns, {}).setdefault(category, {})[base_rel] = anim_data
                    else:
                        self.static_textures[clean_name] = img
                        self.static_by_namespace.setdefault(ns, {})[base_stem] = img
                        self.static_by_ns_cat.setdefault(ns, {}).setdefault(category, {})[base_rel] = img
                except Exception as e:
                    logger.warning(f"Failed to load albedo {albedo_file}: {e}")

            normal_file = info.get("normal")
            if normal_file and Path(normal_file).exists():
                try:
                    n_img = _safe_open_image(normal_file)
                    self.normal_textures[clean_name] = n_img
                    self.normal_by_namespace.setdefault(ns, {})[base_stem] = n_img
                    self.normal_by_ns_cat.setdefault(ns, {}).setdefault(category, {})[base_rel] = n_img
                except Exception as e:
                    logger.warning(f"Failed to load normal {normal_file}: {e}")

            specular_file = info.get("specular")
            if specular_file and Path(specular_file).exists():
                try:
                    s_img = _safe_open_image(specular_file)
                    self.specular_textures[clean_name] = s_img
                    self.specular_by_namespace.setdefault(ns, {})[base_stem] = s_img
                    self.specular_by_ns_cat.setdefault(ns, {}).setdefault(category, {})[base_rel] = s_img
                except Exception as e:
                    logger.warning(f"Failed to load specular {specular_file}: {e}")

        # 3. Bake paletted permutations (e.g. armor trims) if declared in any atlas definition
        if HAS_PIL and self.atlas_definitions:
            def _get_texture_for_bake(res_key: str):
                res_ns = "minecraft"
                clean_k = res_key
                if ":" in res_key:
                    res_ns, clean_k = res_key.split(":", 1)
                clean_k = clean_k.strip("/")
                # Search directly in static textures
                img_found = self.static_by_namespace.get(res_ns, {}).get(clean_k)
                if img_found is not None:
                    return img_found
                return self._find_static_image(clean_k, namespace=res_ns)

            for atlas_id, atlas_def in self.atlas_definitions.items():
                for src in atlas_def.sources:
                    if isinstance(src, PalettedPermutationsAtlasSource):
                        baked_map = self.palette_baker.bake_source(
                            src.palette_key,
                            src.permutations,
                            src.textures,
                            get_texture_fn=_get_texture_for_bake,
                        )
                        for sprite_key, baked_img in baked_map.items():
                            ns = "minecraft"
                            rel_sprite = sprite_key
                            if ":" in sprite_key:
                                ns, rel_sprite = sprite_key.split(":", 1)
                            cat = atlas_def.name
                            if not self._includes_category(cat):
                                continue
                            clean_name = self._texture_name(ns, rel_sprite)
                            self.static_textures[clean_name] = baked_img
                            self.static_by_namespace.setdefault(ns, {})[rel_sprite] = baked_img
                            self.static_by_ns_cat.setdefault(ns, {}).setdefault(cat, {})[rel_sprite] = baked_img

        # 4. Setup biome resolver across all packs
        self.biome_resolver.load_from_pack_stack(self.pack_stack)
        self.biome_resolver.set_models(self.models)

    def resolve_model_textures(self, model_name: str, depth: int = 0) -> dict:
        """Recursively resolve texture variables from block model JSONs."""
        return _resolve_model_textures_fn(self.models, model_name, depth)

    @staticmethod
    def expand_variables(tex_dict: dict) -> dict:
        """Resolve #variable references in texture dictionary."""
        return _expand_variables_fn(tex_dict)

    def get_6_faces_for_model(self, model_name: str) -> dict:
        """
        Map block model to 6 face sub-textures:
        +X (East), -X (West), +Y (Up), -Y (Down), +Z (South), -Z (North).
        """
        return _get_6_faces_for_model_fn(self.models, model_name)

    def _find_static_image(self, key_or_stem: str, namespace: str = "minecraft", category: str = None) -> Optional[Any]:
        """Lookup a static texture image across ns/category dicts and fallback indexes."""
        if not key_or_stem:
            return None
        clean = key_or_stem.strip().lower()
        if ":" in clean:
            ns_part, clean = clean.split(":", 1)
            if not namespace or namespace == "minecraft":
                namespace = ns_part
        clean = clean.removesuffix(".png").strip("/")
        stem = clean.split("/")[-1]

        candidates = [
            clean,
            stem,
            f"block/{stem}",
            f"item/{stem}",
            f"entity/{stem}",
            f"particle/{stem}",
        ]
        if category:
            cat_clean = category.strip("/").lower()
            candidates.insert(0, f"{cat_clean}/{stem}")
            if cat_clean.endswith("s") and len(cat_clean) > 1:
                candidates.insert(1, f"{cat_clean[:-1]}/{stem}")

        # 1. Search in category map if provided
        if category and namespace in self.static_by_ns_cat:
            cat_map = self.static_by_ns_cat[namespace].get(category, {})
            for c in candidates:
                if c in cat_map:
                    return cat_map[c]

        # 2. Search in all categories of this namespace
        if namespace in self.static_by_ns_cat:
            for cat_k, cat_map in self.static_by_ns_cat[namespace].items():
                for c in candidates:
                    if c in cat_map:
                        return cat_map[c]

        # 3. Search in static_by_namespace
        if namespace in self.static_by_namespace:
            ns_map = self.static_by_namespace[namespace]
            for c in (stem, clean):
                if c in ns_map:
                    return ns_map[c]

        # 4. Search in global static_textures
        clean_name = self._texture_name(namespace, stem)
        if clean_name in self.static_textures:
            return self.static_textures[clean_name]

        return None

    def cleanup(self) -> None:
        """Explicitly release all loaded image objects and model caches to reclaim RAM."""
        for mapping in (
            getattr(self, "static_textures", {}),
            getattr(self, "normal_textures", {}),
            getattr(self, "specular_textures", {}),
        ):
            if isinstance(mapping, dict):
                for img in mapping.values():
                    if hasattr(img, "close"):
                        try:
                            img.close()
                        except Exception:
                            pass
                mapping.clear()

        for d_name in ("static_by_namespace", "normal_by_namespace", "specular_by_namespace",
                       "static_by_ns_cat", "normal_by_ns_cat", "specular_by_ns_cat",
                       "animated_textures", "animated_by_namespace", "animated_by_ns_cat",
                       "models", "block_mappings"):
            d = getattr(self, d_name, None)
            if isinstance(d, dict):
                d.clear()

        import gc
        gc.collect()

    def build_iter(self, output_dir: str | Path) -> Iterator[Tuple[float, str, Optional[dict]]]:
        """
        Iteratively construct and save atlas chunks, yielding progress fraction and message.
        Outputs atlas images and atlas_mapping.json to output_dir atomically.
        """
        try:
            yield from self._build_iter_impl(output_dir)
        finally:
            self.cleanup()

    def _build_iter_impl(self, output_dir: str | Path) -> Iterator[Tuple[float, str, Optional[dict]]]:
        if not HAS_PIL:
            raise ImportError("Pillow library is required for AtlasGenerator. Please install it using 'pip install pillow'.")
        Image.init()

        yield (0.05, "Reading textures and models from resource pack...", None)
        self.load_resources()
        yield (0.15, f"Loaded {len(self.static_textures)} static & {len(self.animated_textures)} animated textures", None)

        output_path = Path(output_dir).resolve()
        parent_dir = output_path.parent
        parent_dir.mkdir(parents=True, exist_ok=True)
        unique_id = uuid.uuid4().hex[:8]
        staging_dir = parent_dir / f"{output_path.name}_staging_{os.getpid()}_{unique_id}"
        staging_dir.mkdir(parents=True, exist_ok=True)

        fallback_rel_path = "__mtk_fallback__"
        fallback = Image.new("RGBA", (16, 16), (24, 24, 24, 255))
        for y in range(16):
            for x in range(16):
                if ((x // 4) + (y // 4)) % 2 == 0:
                    fallback.putpixel((x, y), (255, 0, 255, 255))
        self.static_by_ns_cat.setdefault("minecraft", {}).setdefault("blocks", {})[fallback_rel_path] = fallback

        all_namespaces = sorted(set(list(self.static_by_ns_cat.keys()) + list(self.animated_by_ns_cat.keys()) + list(self.static_by_namespace.keys()) + list(self.animated_by_namespace.keys())))
        if "minecraft" in all_namespaces:
            all_namespaces.remove("minecraft")
            all_namespaces.insert(0, "minecraft")

        chunks = []
        category_chunk_counts: dict[str, int] = {}
        texture_locations = {}
        animations = []
        outputs = {"chunks": []}
        total_ns = max(1, len(all_namespaces))
        for ns_idx, ns in enumerate(all_namespaces):
            ns_progress_base = 0.20 + 0.60 * (ns_idx / total_ns)

            # Discover all active categories for this namespace in priority order
            active_categories = []
            for cat in ATLAS_CATEGORY_PRIORITY:
                if (ns in self.static_by_ns_cat and cat in self.static_by_ns_cat[ns] and self.static_by_ns_cat[ns][cat]) or                    (ns in self.animated_by_ns_cat and cat in self.animated_by_ns_cat[ns] and self.animated_by_ns_cat[ns][cat]):
                    active_categories.append(cat)

            extra_cats = sorted(set(
                list(self.static_by_ns_cat.get(ns, {}).keys()) + list(self.animated_by_ns_cat.get(ns, {}).keys())
            ) - set(ATLAS_CATEGORY_PRIORITY))
            active_categories.extend(extra_cats)

            for cat in active_categories:
                if not self._includes_category(cat):
                    continue
                static_map = self.static_by_ns_cat.get(ns, {}).get(cat, {})
                irregular_static_map = {}
                if static_map:
                    yield (ns_progress_base, f"Packing static atlas chunks for namespace '{ns}' [{cat}]...", None)
                    is_rect_packed = (cat in RECT_PACKED_CATEGORIES)

                    if is_rect_packed:
                        pack_rect_category_chunks(
                            cat=cat,
                            ns=ns,
                            static_map=static_map,
                            normal_by_ns_cat=self.normal_by_ns_cat,
                            specular_by_ns_cat=self.specular_by_ns_cat,
                            max_chunk_size=self.max_chunk_size,
                            chunks=chunks,
                            category_chunk_counts=category_chunk_counts,
                            texture_locations=texture_locations,
                            staging_dir=staging_dir,
                            output_path=output_path,
                            outputs=outputs,
                            biome_resolver=self.biome_resolver,
                            fallback_rel_path=fallback_rel_path,
                            find_static_image_fn=self._find_static_image,
                            texture_name_fn=self._texture_name,
                        )
                    else:
                        irregular_static_map = pack_grid_category_chunks(
                            cat=cat,
                            ns=ns,
                            static_map=static_map,
                            normal_by_ns_cat=self.normal_by_ns_cat,
                            specular_by_ns_cat=self.specular_by_ns_cat,
                            normal_textures=self.normal_textures,
                            specular_textures=self.specular_textures,
                            default_tile_size=self.default_tile_size,
                            max_chunk_size=self.max_chunk_size,
                            chunks=chunks,
                            category_chunk_counts=category_chunk_counts,
                            texture_locations=texture_locations,
                            staging_dir=staging_dir,
                            output_path=output_path,
                            outputs=outputs,
                            biome_resolver=self.biome_resolver,
                            fallback_rel_path=fallback_rel_path,
                            find_static_image_fn=self._find_static_image,
                            texture_name_fn=self._texture_name,
                        ) or {}

                # Animated textures for (ns, cat) -> chunk 002
                anim_map = self.animated_by_ns_cat.get(ns, {}).get(cat, {})
                if anim_map:
                    yield (ns_progress_base + 0.05, f"Packing animated strip chunks for namespace '{ns}' [{cat}]...", None)
                    pack_animated_category_chunks(
                        cat=cat,
                        ns=ns,
                        anim_map=anim_map,
                        normal_by_ns_cat=self.normal_by_ns_cat,
                        specular_by_ns_cat=self.specular_by_ns_cat,
                        max_chunk_size=self.max_chunk_size,
                        chunks=chunks,
                        category_chunk_counts=category_chunk_counts,
                        texture_locations=texture_locations,
                        animations=animations,
                        staging_dir=staging_dir,
                        output_path=output_path,
                        outputs=outputs,
                        biome_resolver=self.biome_resolver,
                        find_static_image_fn=self._find_static_image,
                        texture_name_fn=self._texture_name,
                    )

                # Irregular / multi-size block textures (e.g. 32x32 signs, hanging signs, shelves) -> chunk 003
                if irregular_static_map:
                    yield (ns_progress_base + 0.08, f"Packing multi-size / sign atlas chunks for namespace '{ns}' [{cat}]...", None)
                    pack_rect_category_chunks(
                        cat=cat,
                        ns=ns,
                        static_map=irregular_static_map,
                        normal_by_ns_cat=self.normal_by_ns_cat,
                        specular_by_ns_cat=self.specular_by_ns_cat,
                        max_chunk_size=self.max_chunk_size,
                        chunks=chunks,
                        category_chunk_counts=category_chunk_counts,
                        texture_locations=texture_locations,
                        staging_dir=staging_dir,
                        output_path=output_path,
                        outputs=outputs,
                        biome_resolver=self.biome_resolver,
                        fallback_rel_path=fallback_rel_path,
                        find_static_image_fn=self._find_static_image,
                        texture_name_fn=self._texture_name,
                    )

        yield (0.82, "Baking block models and custom UV definitions...", None)
        baked_states = {}
        if hasattr(self, "baker") and self.baker:
            try:
                for frac, msg, cur_states in self.baker.bake_all_pack_states_iter():
                    baked_states = cur_states
                    yield (0.82 + 0.10 * frac, f"Atlas: {msg}", None)
            except Exception as e:
                logger.warning(f"StateBaker bake_all_pack_states: {e}")


        dir_to_face_order = {"east": "+X", "west": "-X", "up": "+Y", "down": "-Y", "south": "+Z", "north": "-Z"}
        block_states_data = {}
        for state_key, baked_model in baked_states.items():
            faces_data = {}
            for dir_name, face_key in dir_to_face_order.items():
                baked_face = baked_model.get_face(dir_name)
                if not baked_face:
                    continue
                tex_full = baked_face.texture
                tex_stem = tex_full.split("/")[-1]
                loc = texture_locations.get(tex_full) or texture_locations.get(tex_stem) or texture_locations.get(f"minecraft:{tex_stem}") or texture_locations.get(f"minecraft:block/{tex_stem}")
                if isinstance(loc, dict):
                    entry = dict(loc)
                    entry["uv_rotation"] = float(baked_face.uv_rot)
                    entry["u_min"] = float(baked_face.uv_bounds[0])
                    entry["v_min"] = float(baked_face.uv_bounds[1])
                    entry["u_max"] = float(baked_face.uv_bounds[2])
                    entry["v_max"] = float(baked_face.uv_bounds[3])
                    entry["tint_index"] = int(baked_face.tint_index)
                    faces_data[face_key] = entry
            if faces_data:
                block_states_data[state_key] = {
                    "is_cube": baked_model.is_cube,
                    "is_opaque": baked_model.is_opaque,
                    "is_emissive": baked_model.is_emissive,
                    "faces": faces_data,
                }

        materials = []
        all_material_names = sorted(set(self.models) | set(self.static_textures) | set(self.animated_textures))
        total_mats = max(1, len(all_material_names))
        for material_id, name in enumerate(all_material_names):
            if material_id % 50 == 0 or material_id == total_mats - 1:
                mat_pct = 0.92 + 0.06 * ((material_id + 1) / total_mats)
                yield (mat_pct, f"Atlas: Resolving material definitions ({material_id + 1}/{total_mats})...", None)

            baked_model = None
            if hasattr(self, "baker") and self.baker:
                try:
                    baked_model = self.baker.bake_block_state(name)
                except Exception:
                    pass

            faces_data = {}
            if baked_model:
                for dir_name, face_key in dir_to_face_order.items():
                    baked_face = baked_model.get_face(dir_name)
                    if baked_face:
                        tex_full = baked_face.texture
                        tex_stem = tex_full.split("/")[-1]
                        loc = texture_locations.get(tex_full) or texture_locations.get(tex_stem) or texture_locations.get(f"minecraft:{tex_stem}") or texture_locations.get(f"minecraft:block/{tex_stem}")
                        if isinstance(loc, dict):
                            entry = dict(loc)
                            entry["uv_rotation"] = float(baked_face.uv_rot)
                            entry["u_min"] = float(baked_face.uv_bounds[0])
                            entry["v_min"] = float(baked_face.uv_bounds[1])
                            entry["u_max"] = float(baked_face.uv_bounds[2])
                            entry["v_max"] = float(baked_face.uv_bounds[3])
                            entry["tint_index"] = int(baked_face.tint_index)
                            faces_data[face_key] = entry

            if not faces_data:
                faces = self.get_6_faces_for_model(name) if name in self.models else {face: name for face in FACE_ORDER}
                for face, texture_name in faces.items():
                    loc = texture_locations.get(texture_name)
                    if isinstance(loc, dict):
                        entry = dict(loc)
                        entry.setdefault("uv_rotation", 0.0)
                        entry.setdefault("u_min", 0.0)
                        entry.setdefault("v_min", 0.0)
                        entry.setdefault("u_max", 1.0)
                        entry.setdefault("v_max", 1.0)
                        faces_data[face] = entry
                    else:
                        faces_data[face] = None

            mat_is_opaque = all(
                entry.get("is_opaque", True) for entry in faces_data.values() if isinstance(entry, dict)
            ) if faces_data else True

            materials.append({
                "material_id": material_id,
                "name": name,
                "is_opaque": mat_is_opaque,
                "faces": faces_data,
            })

        # Determine base tile_size for mapping summary (preference to minecraft)
        mc_chunk = next((c for c in chunks if c.get("namespace") == "minecraft" and "tile_size" in c), None)
        base_tile_sz = mc_chunk["tile_size"] if mc_chunk else self.default_tile_size
        mapping_data = {
            "format_version": ATLAS_FORMAT_VERSION,
            "pack_hash": self.pack_stack.stack_hash if self.pack_stack else "",
            "tile_size": base_tile_sz,
            "max_chunk_size": self.max_chunk_size,
            "chunks": chunks,
            "textures": texture_locations,
            "animations": animations,
            "materials": materials,
            "block_states": block_states_data,
        }

        mapping_file = staging_dir / "atlas_mapping.json"
        with open(mapping_file, "w", encoding="utf-8") as f:
            json.dump(mapping_data, f, indent=2)

        # Atomic commit: replace final output directory
        if output_path.exists():
            shutil.rmtree(output_path)
        staging_dir.rename(output_path)

        outputs["mapping"] = output_path / "atlas_mapping.json"
        yield (1.0, f"Successfully built {len(chunks)} Atlas Chunks and mapping for pack stack.", outputs)

    def build(self, output_dir: str | Path, progress_callback: Optional[Any] = None) -> dict:
        """Synchronous runner for build_iter."""
        final_outputs = None
        for pct, msg, outputs in self.build_iter(output_dir):
            if progress_callback is not None:
                try:
                    progress_callback(pct, msg)
                except Exception:
                    pass
            if outputs is not None:
                final_outputs = outputs
        return final_outputs or {}
