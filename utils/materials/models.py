"""
Core declarative data models and descriptors for MoziToolKit Materials.
Pure Python data structures (NO bpy dependency).
Serves as the boundary contract between PIL-based image generators and Blender shader node builders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


@dataclass
class ChannelDescriptor:
    """
    Represents a single texture channel (e.g. Albedo, Normal, Specular, Overlay).
    """
    path: Optional[Path] = None
    colorspace: str = "sRGB"  # "sRGB" or "Non-Color"
    mcmeta: Optional[Dict[str, Any]] = None
    frame_count: int = 1
    frame_width: int = 16
    frame_height: int = 16
    total_width: int = 16
    total_height: int = 16
    frame_scale_v: float = 1.0  # Sv = FrameHeight / TotalHeight
    frametime: int = 1
    interpolate: bool = False

    @property
    def is_animated(self) -> bool:
        return self.frame_count > 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": str(self.path.resolve()) if self.path else None,
            "colorspace": self.colorspace,
            "mcmeta": self.mcmeta,
            "frame_count": self.frame_count,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "total_width": self.total_width,
            "total_height": self.total_height,
            "frame_scale_v": self.frame_scale_v,
            "frametime": self.frametime,
            "interpolate": self.interpolate,
            "is_animated": self.is_animated,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ChannelDescriptor:
        path_val = data.get("path")
        return cls(
            path=Path(path_val) if path_val else None,
            colorspace=data.get("colorspace", "sRGB"),
            mcmeta=data.get("mcmeta"),
            frame_count=int(data.get("frame_count", 1)),
            frame_width=int(data.get("frame_width", 16)),
            frame_height=int(data.get("frame_height", 16)),
            total_width=int(data.get("total_width", 16)),
            total_height=int(data.get("total_height", 16)),
            frame_scale_v=float(data.get("frame_scale_v", 1.0)),
            frametime=int(data.get("frametime", 1)),
            interpolate=bool(data.get("interpolate", False)),
        )


@dataclass
class StandaloneMaterialDescriptor:
    """
    Declarative specification for constructing a standalone PBR material in Blender.
    All PIL alignments and animations are resolved prior to building this descriptor.
    """
    material_id: str
    canonical_key: str
    channels: Dict[str, ChannelDescriptor] = field(default_factory=dict)
    tint_info: Dict[str, Any] = field(default_factory=dict)
    pack_hash: str = ""
    is_fallback: bool = False
    blend_mode: str = "OPAQUE"  # "OPAQUE", "CLIP", "BLEND"
    is_thin_wall: bool = False
    emission_strength: float = 0.0

    @property
    def albedo(self) -> Optional[ChannelDescriptor]:
        return self.channels.get("albedo")

    @property
    def normal(self) -> Optional[ChannelDescriptor]:
        return self.channels.get("normal")

    @property
    def specular(self) -> Optional[ChannelDescriptor]:
        return self.channels.get("specular")

    @property
    def overlay(self) -> Optional[ChannelDescriptor]:
        return self.channels.get("overlay")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "material_id": self.material_id,
            "canonical_key": self.canonical_key,
            "channels": {k: v.to_dict() for k, v in self.channels.items() if v},
            "tint_info": self.tint_info,
            "pack_hash": self.pack_hash,
            "is_fallback": self.is_fallback,
            "blend_mode": self.blend_mode,
            "is_thin_wall": self.is_thin_wall,
            "emission_strength": self.emission_strength,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StandaloneMaterialDescriptor:
        channels = {}
        for k, v in data.get("channels", {}).items():
            if isinstance(v, dict):
                channels[k] = ChannelDescriptor.from_dict(v)
            elif isinstance(v, ChannelDescriptor):
                channels[k] = v

        return cls(
            material_id=data.get("material_id", ""),
            canonical_key=data.get("canonical_key", ""),
            channels=channels,
            tint_info=data.get("tint_info", {}),
            pack_hash=data.get("pack_hash", ""),
            is_fallback=bool(data.get("is_fallback", False)),
            blend_mode=data.get("blend_mode", "OPAQUE"),
            is_thin_wall=bool(data.get("is_thin_wall", False)),
            emission_strength=float(data.get("emission_strength", 0.0)),
        )

    @classmethod
    def from_texture_info(cls, info: Dict[str, Any]) -> StandaloneMaterialDescriptor:
        """Create a descriptor directly from a texture_info dict (legacy or pipeline format)."""
        channels: Dict[str, ChannelDescriptor] = {}
        for ch in ("albedo", "normal", "specular", "overlay"):
            p = info.get(ch)
            if p:
                path = Path(p)
                mcmeta = info.get(f"{ch}_mcmeta")
                channels[ch] = ChannelDescriptor(
                    path=path,
                    colorspace="Non-Color" if ch in ("normal", "specular") else "sRGB",
                    mcmeta=mcmeta,
                )

        return cls(
            material_id=info.get("material_id", ""),
            canonical_key=info.get("canonical_key", ""),
            channels=channels,
            tint_info=info.get("tint_info", {}),
            pack_hash=info.get("pack_hash", ""),
            is_fallback=bool(info.get("is_fallback", False)),
        )

    def to_texture_info(self) -> Dict[str, Any]:
        """Convert descriptor back to texture_info dict for backwards compatibility."""
        info: Dict[str, Any] = {
            "canonical_key": self.canonical_key,
            "material_id": self.material_id,
            "tint_info": self.tint_info,
            "pack_hash": self.pack_hash,
            "is_fallback": self.is_fallback,
            "is_precompiled": True,
        }
        for ch_name, ch_desc in self.channels.items():
            if ch_desc and ch_desc.path:
                info[ch_name] = str(ch_desc.path)
                if ch_desc.mcmeta:
                    info[f"{ch_name}_mcmeta"] = ch_desc.mcmeta
        return info


@dataclass
class AtlasChunkDescriptor:
    """
    Specification for a single compiled texture atlas chunk.
    """
    chunk_id: int
    category: str
    kind: str  # "rect", "grid", "animated"
    image_paths: Dict[str, Optional[Path]] = field(default_factory=dict)  # "albedo", "normal", "specular"
    width: int = 1024
    height: int = 1024
    tile_size: int = 16
    tiles_per_row: int = 64
    format_version: int = 2

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "category": self.category,
            "kind": self.kind,
            "image_paths": {k: str(v.resolve()) if v else None for k, v in self.image_paths.items()},
            "width": self.width,
            "height": self.height,
            "tile_size": self.tile_size,
            "tiles_per_row": self.tiles_per_row,
            "format_version": self.format_version,
        }
