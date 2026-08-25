"""
Data Models and Normalization for MoziToolKit Configuration Management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


def normalize_operator_id(op_id: str) -> str:
    """
    Normalize legacy or category-prefixed operator IDs (e.g. 'object.mozi_adaptive_pixel_split')
    to canonical registered operator bl_idnames (e.g. 'mozi.adaptive_pixel_split').
    """
    if not op_id or not isinstance(op_id, str):
        return ""
    if op_id.startswith("mozi."):
        return op_id
    if "." in op_id:
        prefix, name = op_id.split(".", 1)
        if name.startswith("mozi_"):
            return f"mozi.{name[5:]}"
    return op_id


def is_valid_operator_id(op_id: str) -> bool:
    """Validate that an operator ID belongs to the MoziToolKit namespace or known whitelist."""
    if not op_id or not isinstance(op_id, str):
        return False
    norm = normalize_operator_id(op_id)
    if norm.startswith("mozi.") or norm.startswith("mozi_"):
        return True
    return False


@dataclass
class PackEntry:
    """Represents a single Resource Pack, Mod JAR, or Vanilla JAR entry in the fallback stack."""

    name: str = "Resource Pack"
    path: str = ""
    enabled: bool = True
    pack_type: str = "RESOURCE_PACK"  # RESOURCE_PACK | MOD_JAR | VANILLA

    @property
    def tier_priority(self) -> int:
        """Strict 3-tier hierarchy: RESOURCE_PACK (0) -> MOD_JAR (1) -> VANILLA (2)."""
        pt = self.pack_type.upper() if self.pack_type else "RESOURCE_PACK"
        if pt == "RESOURCE_PACK":
            return 0
        elif pt == "MOD_JAR":
            return 1
        elif pt == "VANILLA":
            return 2
        return 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "enabled": self.enabled,
            "pack_type": self.pack_type,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PackEntry:
        if not isinstance(data, dict):
            return cls()
        pt = data.get("pack_type", "RESOURCE_PACK")
        if pt not in {"RESOURCE_PACK", "MOD_JAR", "VANILLA"}:
            pt = "RESOURCE_PACK"
        return cls(
            name=str(data.get("name", "Resource Pack")),
            path=str(data.get("path", "")),
            enabled=bool(data.get("enabled", True)),
            pack_type=pt,
        )


@dataclass
class MaterialSettings:
    """Global material generation and replacement options."""

    material_mode: str = "ATLAS"  # ATLAS | STANDALONE
    biome_preset: str = "PLAINS"
    pack_textures: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "material_mode": self.material_mode,
            "biome_preset": self.biome_preset,
            "pack_textures": self.pack_textures,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MaterialSettings:
        if not isinstance(data, dict):
            return cls()
        mode = data.get("material_mode", "ATLAS")
        if mode not in {"ATLAS", "STANDALONE"}:
            mode = "ATLAS"
        return cls(
            material_mode=mode,
            biome_preset=str(data.get("biome_preset", "PLAINS")),
            pack_textures=bool(data.get("pack_textures", True)),
        )


@dataclass
class MenuItem:
    """Represents a configured context menu item entry."""

    operator: str = ""
    label: str = ""
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operator": self.operator,
            "label": self.label,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MenuItem:
        if not isinstance(data, dict):
            return cls()
        op = normalize_operator_id(str(data.get("operator", "")))
        return cls(
            operator=op,
            label=str(data.get("label", "")),
            enabled=bool(data.get("enabled", True)),
        )


CANONICAL_DEFAULT_PRESETS: Dict[str, List[Dict[str, Any]]] = {
    "mesh": [
        {"operator": "mozi.adaptive_pixel_split", "label": "Adaptive Pixel Split", "enabled": True},
        {"operator": "mozi.select_hard_edges", "label": "Select Hard & Sharp Edges", "enabled": True},
        {"operator": "mozi.select_transparent_faces", "label": "Select Transparent Faces", "enabled": True},
        {"operator": "mozi.repair_fluid_uv", "label": "Repair Fluid UV", "enabled": True},
        {"operator": "mozi.random_extrude", "label": "Random Extrude", "enabled": True},
        {"operator": "mozi.auto_extrude_repair", "label": "Auto Extrude Repair", "enabled": True},
        {"operator": "mozi.clear_custom_normals", "label": "Clear Custom Normals", "enabled": True},
    ],
    "object": [
        {"operator": "mozi.replace_material", "label": "Replace Material", "enabled": True},
        {"operator": "mozi.adaptive_pixel_split", "label": "Adaptive Pixel Split", "enabled": True},
        {"operator": "mozi.set_texture_interpolation_closest", "label": "Set Image Interpolation to Closest", "enabled": True},
        {"operator": "mozi.clear_custom_normals", "label": "Clear Custom Normals", "enabled": True},
    ],
    "uv": [
        {"operator": "mozi.adaptive_pixel_split", "label": "Adaptive Pixel Split", "enabled": True},
        {"operator": "mozi.scale_uv", "label": "Scale UV Faces", "enabled": True},
        {"operator": "mozi.select_transparent_faces", "label": "Select Transparent Faces", "enabled": True},
        {"operator": "mozi.repair_fluid_uv", "label": "Repair Fluid UV", "enabled": True},
    ],
}


def get_default_menu_views() -> Dict[str, List[MenuItem]]:
    """Build default MenuItem instances from dynamically registered operator presets or static fallback."""
    presets = {}
    try:
        from ..system.menu_registry import get_default_presets
        presets = get_default_presets()
    except Exception:
        try:
            from utils.system.menu_registry import get_default_presets
            presets = get_default_presets()
        except Exception:
            presets = {}

    views: Dict[str, List[MenuItem]] = {}
    for view_name in ["mesh", "object", "uv"]:
        items = presets.get(view_name) if presets else None
        if not items:
            items = CANONICAL_DEFAULT_PRESETS.get(view_name, [])
        views[view_name] = [
            it if isinstance(it, MenuItem) else MenuItem.from_dict(it)
            for it in items
            if isinstance(it, (dict, MenuItem))
        ]
    return views


@dataclass
class ConfigData:
    """Full MoziToolKit root configuration data model."""

    version: int = 1
    backend_type: str = "JSON"  # JSON | BLENDER_PREFS | MEMORY
    views: Dict[str, List[MenuItem]] = field(default_factory=get_default_menu_views)
    resource_packs: List[PackEntry] = field(default_factory=list)
    material_settings: MaterialSettings = field(default_factory=MaterialSettings)

    def normalize(self) -> None:
        """
        Normalize views and enforce 3-tier ordering on resource_packs in place.
        Preserves relative order within each tier using stable sort.
        """
        # 1. Normalize and filter views
        norm_views = {}
        for view_name in ["mesh", "object", "uv"]:
            items = self.views.get(view_name, [])
            norm_items = []
            if isinstance(items, list):
                for item in items:
                    m_item = item if isinstance(item, MenuItem) else MenuItem.from_dict(item)
                    if m_item.operator and is_valid_operator_id(m_item.operator):
                        m_item.operator = normalize_operator_id(m_item.operator)
                        norm_items.append(m_item)
            norm_views[view_name] = norm_items
        self.views = norm_views

        # 2. Enforce 3-tier ordering on resource_packs
        norm_packs = []
        for p in self.resource_packs:
            norm_packs.append(p if isinstance(p, PackEntry) else PackEntry.from_dict(p))
        self.resource_packs = sorted(norm_packs, key=lambda x: x.tier_priority)

    def to_dict(self) -> Dict[str, Any]:
        self.normalize()
        views_dict = {
            view: [item.to_dict() for item in items]
            for view, items in self.views.items()
        }
        packs_list = [pack.to_dict() for pack in self.resource_packs]
        return {
            "version": self.version,
            "backend_type": self.backend_type,
            "views": views_dict,
            "resource_packs": packs_list,
            "material_settings": self.material_settings.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ConfigData:
        if not isinstance(data, dict):
            return cls()

        version = int(data.get("version", 1))
        backend_type = str(data.get("backend_type", "JSON"))

        # Views: Extract if present, otherwise populate from default presets
        if "views" in data and isinstance(data["views"], dict):
            raw_views = data["views"]
            has_any_item = any(isinstance(raw_views.get(v), list) and len(raw_views.get(v)) > 0 for v in ["mesh", "object", "uv"])
            if has_any_item:
                views = {"mesh": [], "object": [], "uv": []}
                for v_name in ["mesh", "object", "uv"]:
                    v_list = raw_views.get(v_name, [])
                    if isinstance(v_list, list):
                        views[v_name] = [MenuItem.from_dict(it) for it in v_list if isinstance(it, dict)]
            else:
                views = get_default_menu_views()
        elif any(k in data for k in ["mesh", "object", "uv"]):
            has_any_item = any(isinstance(data.get(v), list) and len(data.get(v)) > 0 for v in ["mesh", "object", "uv"])
            if has_any_item:
                views = {"mesh": [], "object": [], "uv": []}
                for v_name in ["mesh", "object", "uv"]:
                    v_list = data.get(v_name, [])
                    if isinstance(v_list, list):
                        views[v_name] = [MenuItem.from_dict(it) for it in v_list if isinstance(it, dict)]
            else:
                views = get_default_menu_views()
        else:
            views = get_default_menu_views()

        # Resource Packs
        raw_packs = data.get("resource_packs", [])
        resource_packs = []
        if isinstance(raw_packs, list):
            resource_packs = [PackEntry.from_dict(p) for p in raw_packs if isinstance(p, dict)]

        # Material Settings
        raw_mat = data.get("material_settings", {})
        material_settings = MaterialSettings.from_dict(raw_mat) if isinstance(raw_mat, dict) else MaterialSettings()

        cfg = cls(
            version=version,
            backend_type=backend_type,
            views=views,
            resource_packs=resource_packs,
            material_settings=material_settings,
        )
        cfg.normalize()
        return cfg
