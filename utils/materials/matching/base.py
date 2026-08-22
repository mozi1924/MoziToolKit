"""
Base definitions, protocols, and common extraction routines for Importer Adapters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple
import bpy

from ..constants import DEFAULT_NAMESPACE
from ..provenance import without_blender_suffix


def extract_texture_provenance_from_image(image: bpy.types.Image) -> tuple[str | None, str]:
    """Extract namespace (if identifiable) and clean texture name from an image datablock."""
    if not image:
        return None, ""

    filepath = (image.filepath or "").replace("\\", "/").strip()
    raw_name = Path(filepath).name if filepath else image.name

    detected_namespace = None
    if ":" in raw_name:
        parts = raw_name.split(":", 1)
        detected_namespace = parts[0].strip().lower()
        raw_name = parts[1]

    if filepath and not detected_namespace:
        parts = filepath.strip("/").split("/")
        for i, p in enumerate(parts):
            if p.lower() == "assets" and i + 2 < len(parts) and parts[i + 2].lower() == "textures":
                detected_namespace = parts[i + 1].lower()
                break
            elif p.lower() == "textures" and i > 0 and parts[i - 1].lower() not in (
                "assets", "resourcepacks", "resource_packs", "mcpatcher", "optifine"
            ):
                candidate_ns = parts[i - 1].lower()
                if candidate_ns not in ("minecraft", "assets"):
                    detected_namespace = candidate_ns
                break

    key = without_blender_suffix(raw_name.lower())
    if key.endswith(".png"):
        key = key[:-4]
    if len(key) > 5 and key[-5] == "_" and key[-4:].isdigit():
        key = key[:-5]
    if detected_namespace in ("assets", "library", "ice_cube_asset_library"):
        detected_namespace = None
    return detected_namespace, key


def normalized_image_key(image: bpy.types.Image) -> str:
    """Return an image datablock's basename as a resource-pack texture key."""
    _ns, key = extract_texture_provenance_from_image(image)
    return key


def base_texture_candidates(mat: bpy.types.Material) -> tuple[str, list[str]]:
    """Extract literal image and material-name candidates shared by all adapters."""
    if not mat:
        return "", []
    if mat.get("mtk:source_namespace") and mat.get("mtk:source_texture"):
        source_tex = str(mat["mtk:source_texture"])
        if not source_tex.startswith("atlas_chunk_"):
            return str(mat["mtk:source_namespace"]), [source_tex]

    name = without_blender_suffix(mat.name.strip().lower())
    namespace = DEFAULT_NAMESPACE
    if ":" in name:
        parts = name.split(":")
        if len(parts) >= 3 and parts[0] == "mtk":
            namespace = parts[1]
            name = parts[2]
        else:
            namespace, name = parts[0], parts[1]
    elif "/" in name and not name.startswith("//"):
        parts = name.split("/", 1)
        if parts[0] in ("assets", "textures", "block", "item", "entity"):
            name = parts[1]
        elif (
            parts[0].endswith("_block")
            or parts[0].endswith("_texture")
            or parts[0].endswith("_cross")
            or any(k in parts[0] for k in ("tendril", "lantern", "campfire", "fire", "seagrass", "kelp", "pumpkin"))
        ):
            name = parts[1]
        else:
            if parts[0] not in ("library", "ice_cube_asset_library"):
                namespace = parts[0]
            name = parts[1]

    candidates = []
    detected_namespaces = []
    if mat.use_nodes and mat.node_tree:
        # Check node tree name if it carries informative name (e.g. from an importer)
        tree_name = without_blender_suffix(mat.node_tree.name.strip().lower()).removesuffix(".png")
        if tree_name and not tree_name.startswith(("shader nodetree", "nodetree", "material")):
            candidates.append(tree_name)

        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE":
                if node.image:
                    from ..mineways_atlas import is_mineways_atlas_image
                    img_ns, key = extract_texture_provenance_from_image(node.image)
                    if img_ns and img_ns not in ("assets", "library", "ice_cube_asset_library"):
                        detected_namespaces.append(img_ns)
                    if key and not key.startswith("atlas_chunk_") and not is_mineways_atlas_image(node.image):
                        candidates.append(key)
                # Fallback: if node.image is None or missing, extract from node label or custom node name
                for attr_val in (node.label, node.name):
                    if attr_val:
                        clean_attr = without_blender_suffix(attr_val.strip().lower()).removesuffix(".png")
                        if clean_attr and not clean_attr.startswith(("image texture", "tex_image", "atlas_chunk_")):
                            candidates.append(clean_attr)

    if namespace == DEFAULT_NAMESPACE and detected_namespaces:
        namespace = detected_namespaces[0]

    clean_name = name.removesuffix(".png")
    if not clean_name.startswith("atlas_chunk_"):
        candidates.append(clean_name)
    return namespace, list(dict.fromkeys(candidates))


class ImporterAdapter(ABC):
    """Abstract interface for Minecraft importer format adapters."""

    identifier: str
    description: str

    @abstractmethod
    def detect(self, mat: bpy.types.Material | None) -> bool:
        """Return True if this adapter recognizes the material."""
        raise NotImplementedError

    @abstractmethod
    def extract_keys(self, mat: bpy.types.Material) -> tuple[str, list[str]]:
        """Extract namespace and prioritized list of texture candidate keys."""
        raise NotImplementedError

    def is_internal_or_skipped(self, mat: bpy.types.Material | None) -> bool:
        """Return True if this material slot should be skipped/retained without replacement."""
        return False


@dataclass(frozen=True)
class MaterialMatchPreset:
    """Legacy compatibility bridge dataclass."""

    identifier: str
    description: str
    detects: Callable[[bpy.types.Material], bool]
    extract_keys: Callable[[bpy.types.Material], tuple[str, list[str]]]
