"""
Specialized material and geometry handler for Minecraft's Firefly Bush (萤火虫灌木).

Minecraft 26.2 client defines firefly_bush via `cross_emissive.json`, which overlaps
two identical cross elements (base plant + emissive animated fireflies). In Blender,
this creates duplicate coplanar faces (叠面), Z-fighting, and texture sorting bugs.

This module provides an isolated, dedicated solution:
1. Geometry de-duplication: strips the duplicate emissive cross elements, keeping only
   a single clean cross geometry layer.
2. Precompiled texture synthesis: combines the static base plant (16x16) and the animated
   emissive firefly strip (16x160, 10 frames) into a unified animated Albedo strip and
   a companion LabPBR emissive Specular (_s) strip with synchronized `.mcmeta`.
3. Biome tint exemption: ensures the bush is not incorrectly tinted as grass.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional, Union

from ...system.dependencies import has_pillow

logger = logging.getLogger("MoziToolKit.Materials.Specialized.FireflyBush")

FIREFLY_BUSH_IDENTIFIERS = frozenset({
    "firefly_bush",
    "block/firefly_bush",
    "minecraft:firefly_bush",
    "minecraft:block/firefly_bush",
})

FIREFLY_BUSH_EMISSIVE_IDENTIFIERS = frozenset({
    "firefly_bush_emissive",
    "block/firefly_bush_emissive",
    "minecraft:firefly_bush_emissive",
    "minecraft:block/firefly_bush_emissive",
})


def is_firefly_bush(identifier: str) -> bool:
    """Return True if identifier refers to the base firefly bush block or texture."""
    if not identifier:
        return False
    norm = identifier.strip().lower()
    short = norm.split(":", 1)[-1].removeprefix("block/")
    return norm in FIREFLY_BUSH_IDENTIFIERS or short == "firefly_bush"


def is_firefly_bush_emissive(identifier: str) -> bool:
    """Return True if identifier refers to the emissive firefly overlay texture."""
    if not identifier:
        return False
    norm = identifier.strip().lower()
    short = norm.split(":", 1)[-1].removeprefix("block/")
    return norm in FIREFLY_BUSH_EMISSIVE_IDENTIFIERS or short == "firefly_bush_emissive"


def is_firefly_bush_tint_exempt(identifier: str) -> bool:
    """Firefly bush has hardcoded dark olive/green foliage in vanilla and must NOT be grass-tinted."""
    return is_firefly_bush(identifier) or is_firefly_bush_emissive(identifier)


def sanitize_firefly_bush_elements(
    block_or_model_name: str,
    raw_elements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Sanitize model elements for firefly bush:
    Removes duplicate overlapping emissive cross elements (the second pair of cross faces),
    retaining only the single base cross element pair mapped to the synthesized texture.
    """
    if not is_firefly_bush(block_or_model_name) or not raw_elements:
        return raw_elements

    # In cross_emissive.json, elements 0 & 1 are #cross, elements 2 & 3 are #cross_emissive
    filtered_elements: list[dict[str, Any]] = []
    for elem in raw_elements:
        faces = elem.get("faces", {})
        # Check if any face references the emissive layer
        has_emissive_face = False
        for f_data in faces.values():
            tex = str(f_data.get("texture", "")).lower()
            if "emissive" in tex or tex == "#cross_emissive":
                has_emissive_face = True
                break

        if has_emissive_face:
            # Drop this duplicate face layer to prevent Blender coplanar Z-fighting
            continue

        # Clean the textures in the retained element to canonical firefly_bush
        clean_elem = dict(elem)
        clean_faces = {}
        for d, f_data in faces.items():
            fd_copy = dict(f_data)
            fd_copy["texture"] = "minecraft:block/firefly_bush"
            fd_copy["tintindex"] = -1  # Explicitly remove tint index
            clean_faces[d] = fd_copy
        clean_elem["faces"] = clean_faces
        filtered_elements.append(clean_elem)

    # Fallback guard: if filtering removed everything, keep the first half
    if not filtered_elements and raw_elements:
        return raw_elements[:max(1, len(raw_elements) // 2)]

    return filtered_elements


def synthesize_firefly_bush_textures(
    base_albedo_path: Union[str, Path],
    emissive_path: Union[str, Path],
    emissive_mcmeta: Optional[dict[str, Any]] = None,
    output_dir: Optional[Union[str, Path]] = None,
) -> Optional[dict[str, Any]]:
    """
    Synthesize base static firefly_bush.png (16x16) and animated firefly_bush_emissive.png (16x160)
    into a unified 10-frame animated Albedo texture with a synchronized LabPBR Specular (_s) emission strip.

    Returns texture_info dictionary with 'albedo', 'albedo_mcmeta', and 'specular' paths.
    """
    base_path = Path(base_albedo_path)
    em_path = Path(emissive_path)

    if not base_path.is_file() or not em_path.is_file():
        logger.warning(
            "Cannot synthesize firefly_bush: base_path=%s (exists=%s), em_path=%s (exists=%s)",
            base_path, base_path.is_file(), em_path, em_path.is_file()
        )
        return None

    if not has_pillow():
        logger.warning("Pillow not available; cannot synthesize firefly bush textures.")
        return None

    from PIL import Image

    try:
        base_img = Image.open(base_path).convert("RGBA")
        em_img = Image.open(em_path).convert("RGBA")
    except Exception as e:
        logger.error("Failed to load firefly bush source images: %s", e)
        return None

    w_base, h_base = base_img.size
    w_em, h_em = em_img.size

    frame_width = w_base
    frame_height = h_base

    # Compute total frames from height ratio
    total_frames = max(1, h_em // frame_height) if frame_height > 0 else 1
    frametime = 3
    interpolate = False
    if emissive_mcmeta and isinstance(emissive_mcmeta, dict):
        anim_info = emissive_mcmeta.get("animation", emissive_mcmeta)
        if isinstance(anim_info, dict):
            frametime = int(anim_info.get("frametime", 3))
            interpolate = bool(anim_info.get("interpolate", False))

    # 1. Synthesize Composite Albedo Strip
    composite_albedo = Image.new("RGBA", (frame_width, frame_height * total_frames), (0, 0, 0, 0))

    # 2. Synthesize LabPBR Specular / Emission Strip
    # In LabPBR 1.3:
    # R = Perceptual Smoothness (Roughness = (1-R)^2)
    # G = F0 Reflectance (Dielectric / Metal)
    # B = Porosity / SSS
    # A = Emission (0 = no emission, 255 = 100% full emission)
    composite_specular = Image.new("RGBA", (frame_width, frame_height * total_frames), (0, 0, 0, 0))

    for frame_idx in range(total_frames):
        y_offset = frame_idx * frame_height

        # Base plant layer for this frame
        frame_canvas = base_img.copy()

        # Crop emissive firefly overlay for this frame
        em_crop = em_img.crop((0, y_offset, frame_width, y_offset + frame_height))

        # Alpha composite overlay onto base
        composed_frame = Image.alpha_composite(frame_canvas, em_crop)
        composite_albedo.paste(composed_frame, (0, y_offset))

        # Build LabPBR Specular for this frame:
        # Firefly pixels emit light; non-firefly pixels do not emit
        spec_crop = Image.new("RGBA", (frame_width, frame_height), (0, 0, 0, 0))
        em_pixels = em_crop.load()
        spec_pixels = spec_crop.load()

        for py in range(frame_height):
            for px in range(frame_width):
                r, g, b, a = em_pixels[px, py]
                if a > 10:
                    # Emissive firefly spot: High emission in Alpha channel (254 is LabPBR maximum standard)
                    spec_pixels[px, py] = (255, 10, 0, 254)
                else:
                    # Foliage body: Default roughness, 0 emission
                    spec_pixels[px, py] = (75, 10, 0, 0)

        composite_specular.paste(spec_crop, (0, y_offset))

    # Determine destination directory
    out_dir = Path(output_dir) if output_dir else base_path.parent / "_synthesized"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_albedo_path = out_dir / "firefly_bush.png"
    out_mcmeta_path = out_dir / "firefly_bush.png.mcmeta"
    out_specular_path = out_dir / "firefly_bush_s.png"

    composite_albedo.save(out_albedo_path, format="PNG")
    composite_specular.save(out_specular_path, format="PNG")

    mcmeta_payload = {
        "animation": {
            "frametime": frametime,
            "interpolate": interpolate,
            "frames": list(range(total_frames)),
        }
    }
    with open(out_mcmeta_path, "w", encoding="utf-8") as fp:
        json.dump(mcmeta_payload, fp, indent=2)

    logger.info(
        "Synthesized firefly_bush animation: %d frames, %dx%d -> %s",
        total_frames, frame_width, frame_height * total_frames, out_albedo_path
    )

    return {
        "namespace": "minecraft",
        "texture_name": "firefly_bush",
        "texture_key": "block/firefly_bush",
        "albedo": out_albedo_path,
        "albedo_mcmeta": mcmeta_payload["animation"],
        "normal": None,
        "normal_mcmeta": None,
        "specular": out_specular_path,
        "specular_mcmeta": mcmeta_payload["animation"],
        "is_precompiled": True,
        "tint_info": {
            "tint_type": 0,
            "is_hardcoded": False,
            "has_overlay": False,
            "default_tint_weight": 0.0,
            "default_base_tint_weight": 0.0,
            "default_overlay_tint_weight": 0.0,
        },
    }


def handle_firefly_bush_texture_info(pack_stack: Any, composite: dict[str, Any], namespace: str = "minecraft") -> Optional[dict[str, Any]]:
    """Hook invoked by ResourcePackStack.get_texture_info() for firefly_bush."""
    base_albedo = composite.get("albedo")
    if not base_albedo or not Path(base_albedo).is_file():
        return None

    # Retrieve firefly_bush_emissive from the pack stack
    em_info = None
    for pack in getattr(pack_stack, "packs", []):
        info = pack.get_texture_info("firefly_bush_emissive", namespace=namespace)
        if info and info.get("albedo") and Path(info["albedo"]).is_file():
            em_info = info
            break

    if not em_info:
        return None

    return synthesize_firefly_bush_textures(
        base_albedo_path=base_albedo,
        emissive_path=em_info["albedo"],
        emissive_mcmeta=em_info.get("albedo_mcmeta"),
    )


def handle_firefly_bush_composite_map(pack_stack: Any, composite_map: dict[tuple[str, str], dict[str, Any]]) -> None:
    """Hook invoked by ResourcePackStack.get_all_composite_textures() to synthesize firefly_bush."""
    key = ("minecraft", "block/firefly_bush")
    em_key = ("minecraft", "block/firefly_bush_emissive")

    if key not in composite_map or em_key not in composite_map:
        return

    base_entry = composite_map[key]
    em_entry = composite_map[em_key]

    base_albedo = base_entry.get("albedo")
    em_albedo = em_entry.get("albedo")

    if not base_albedo or not em_albedo:
        return

    syn = synthesize_firefly_bush_textures(
        base_albedo_path=base_albedo,
        emissive_path=em_albedo,
        emissive_mcmeta=em_entry.get("albedo_mcmeta"),
    )
    if syn:
        composite_map[key] = syn

