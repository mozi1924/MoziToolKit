"""
Standalone Material Asset Library Generator for Minecraft Java Resource Packs & Stack.
Precompiles synthesized single-block textures, aligned PBR companion strips, UV scaling metadata,
and standalone_mapping.json with atomic cache publishing for instant viewport replacement.
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple, Union

from ..constants import DEFAULT_NAMESPACE, FALLBACK_TEXTURE_KEY
from ..pipeline.provenance import canonical_texture_key
from ..biome import BiomeResolver
from .aligner import align_standalone_textures, is_channel_animated, _get_channel_image_size
from ...system.dependencies import has_pillow

try:
    from PIL import Image
    HAS_PIL = True
    Image.MAX_IMAGE_PIXELS = 128 * 1024 * 1024
except ImportError:
    Image = None
    HAS_PIL = False

STANDALONE_FORMAT_VERSION = 2


class StandaloneGenerator:
    """
    Synthesizes multi-layer resource pack stacks into a unified standalone asset library.
    - Resolves cascading per-channel overrides (Albedo, Normal _n, Specular _s, Overlay).
    - Pre-tiles animated companion channels vertically to match Albedo frame count.
    - Precomputes Frame 0 UV scaling factor (Sv = FrameHeight / TotalHeight).
    - Produces standalone_mapping.json and precompiled textures with atomic publication.
    """

    def __init__(
        self,
        resource_path: Optional[Union[str, Path, Any]] = None,
        fallback_stack: Optional[Any] = None,
    ):
        from ..pack.pack_stack import ResourcePackStack, get_configured_pack_stack
        from ..pack.resource_pack import ZipResourcePack

        if isinstance(resource_path, ResourcePackStack):
            self.stack = resource_path
        elif fallback_stack is not None:
            self.stack = fallback_stack
        elif isinstance(resource_path, ZipResourcePack):
            self.stack = ResourcePackStack([resource_path])
        elif resource_path is not None:
            self.stack = ResourcePackStack([resource_path])
        else:
            self.stack = get_configured_pack_stack()

    def build_iter(self, output_dir: Union[str, Path]) -> Iterator[Tuple[float, str, Optional[dict]]]:
        """
        Iteratively precompile the standalone asset library.
        Yields (fraction: float, message: str, outputs: Optional[dict]).
        Uses a temporary staging directory and publishes atomically.
        """
        if not HAS_PIL:
            raise ImportError(
                "Pillow library is required for StandaloneGenerator. Please install it using 'pip install pillow'."
            )

        if not self.stack or not self.stack.packs:
            raise ValueError("No active resource packs or base JARs found in stack to precompile.")

        output_path = Path(output_dir).resolve()
        parent_dir = output_path.parent
        parent_dir.mkdir(parents=True, exist_ok=True)

        unique_id = uuid.uuid4().hex[:8]
        staging_dir = parent_dir / f"{output_path.name}_staging_{os.getpid()}_{unique_id}"
        textures_dir = staging_dir / "textures"
        textures_dir.mkdir(parents=True, exist_ok=True)

        yield (0.05, "Scanning resource pack stack for composite textures...", None)

        # 1. Collect all composite texture entries across the stack
        composite_map = self.stack.get_all_composite_textures()

        # 2. Filter to renderable entries that possess an Albedo channel
        valid_entries = {}
        for (ns, path_key), info in composite_map.items():
            albedo_p = info.get("albedo")
            if albedo_p and Path(albedo_p).exists():
                valid_entries[(ns, path_key)] = info

        total_entries = max(1, len(valid_entries))
        yield (0.15, f"Synthesizing {len(valid_entries)} standalone texture entries...", None)

        # 3. Setup Biome Resolver
        biome_resolver = BiomeResolver()
        for pack in self.stack.packs:
            if pack.extract_dir:
                biome_resolver.load_from_pack_root(pack.extract_dir)

        stack_hash = self.stack.stack_hash
        short_hash = stack_hash[:8]
        textures_mapping: Dict[str, dict] = {}
        aliases_mapping: Dict[str, str] = {}

        # Always publish a tiny procedural error texture.  It gives replacement
        # a deterministic material even when a source resource does not exist.
        fallback_file = "textures/mtk_fallback.png"
        fallback_img = Image.new("RGBA", (16, 16), (24, 24, 24, 255))
        for y in range(16):
            for x in range(16):
                if ((x // 4) + (y // 4)) % 2 == 0:
                    fallback_img.putpixel((x, y), (255, 0, 255, 255))
        fallback_img.save(textures_dir / "mtk_fallback.png")
        fallback_record = {
            "namespace": "mozi", "texture_name": "fallback", "texture_key": "fallback",
            "canonical_key": FALLBACK_TEXTURE_KEY, "files": {"albedo": fallback_file, "normal": None, "specular": None, "overlay": None},
            "is_animated": False, "animation": None, "tint_info": {}, "is_fallback": True,
        }
        textures_mapping[FALLBACK_TEXTURE_KEY] = fallback_record

        try:
            for idx, ((ns, path_key), raw_info) in enumerate(valid_entries.items()):
                if idx % 100 == 0 or idx == total_entries - 1:
                    frac = 0.15 + 0.70 * (idx / total_entries)
                    yield (frac, f"Precompiling textures: {ns}:{path_key} ({idx + 1}/{total_entries})", None)

                tex_name = raw_info.get("texture_name") or path_key.split("/")[-1]
                clean_name = path_key.replace("/", "-").replace(":", "-")

                # Resolve overlay texture and tint info from biome resolver
                tex_info = dict(raw_info)
                overlay_stem = biome_resolver.get_overlay_texture(tex_name)
                if overlay_stem:
                    overlay_info = self.stack.get_texture_info(overlay_stem, ns)
                    if overlay_info and overlay_info.get("albedo"):
                        tex_info["overlay"] = overlay_info["albedo"]
                        if overlay_info.get("albedo_mcmeta"):
                            tex_info["overlay_mcmeta"] = overlay_info["albedo_mcmeta"]

                tint_info = biome_resolver.get_tint_info(tex_name)
                tex_info["tint_info"] = tint_info
                tex_info["pack_hash"] = stack_hash

                # Check if this texture is animated (or companion channels are animated)
                channels = ["albedo", "normal", "specular", "overlay"]
                has_animation = any(
                    is_channel_animated(tex_info.get(ch), tex_info.get(f"{ch}_mcmeta"))
                    for ch in channels
                    if tex_info.get(ch)
                )

                channel_files: Dict[str, Optional[str]] = {
                    "albedo": None,
                    "normal": None,
                    "specular": None,
                    "overlay": None,
                }

                anim_metadata = None

                if has_animation:
                    # Align animated channels to matching frame counts in textures_dir
                    aligned_info = align_standalone_textures(tex_info, pack_hash=stack_hash, output_dir=textures_dir)

                    ref_ch = "albedo" if aligned_info.get("albedo") else next(
                        ch for ch in channels if aligned_info.get(ch)
                    )
                    ref_path = Path(aligned_info[ref_ch])
                    ref_meta = aligned_info.get(f"{ref_ch}_mcmeta") or {}
                    ref_size = _get_channel_image_size(ref_path) or (16, 16)
                    ref_w, ref_h = ref_size

                    frame_w = int(ref_meta.get("width") or ref_w)
                    frame_h = int(ref_meta.get("height") or frame_w)
                    total_frames = max(1, ref_h // frame_h) if frame_h > 0 else 1
                    frametime = max(1, int(ref_meta.get("frametime", 1)))
                    interpolate = bool(ref_meta.get("interpolate", False))
                    frames = ref_meta.get("frames", list(range(total_frames)))

                    v_scale = (frame_h / ref_h) if ref_h > 0 else 1.0
                    v_offset = 1.0 - v_scale

                    anim_metadata = {
                        "frame_width": frame_w,
                        "frame_height": frame_h,
                        "image_width": ref_w,
                        "image_height": ref_h,
                        "total_frames": total_frames,
                        "frametime": frametime,
                        "interpolate": interpolate,
                        "frames": frames,
                        "v_scale": float(v_scale),
                        "v_offset": float(v_offset),
                    }

                    # Copy any untouched channel images into textures_dir if not already there
                    for ch in channels:
                        src_p = aligned_info.get(ch)
                        if not src_p or not Path(src_p).exists():
                            continue
                        src_path = Path(src_p)
                        if src_path.parent == textures_dir:
                            channel_files[ch] = f"textures/{src_path.name}"
                        else:
                            out_fname = f"{short_hash}_{ns}_{clean_name}_{ch}.png"
                            dst_p = textures_dir / out_fname
                            shutil.copy2(src_path, dst_p)
                            channel_files[ch] = f"textures/{out_fname}"
                else:
                    # Static texture channels: copy directly to textures_dir
                    for ch in channels:
                        src_p = tex_info.get(ch)
                        if not src_p or not Path(src_p).exists():
                            continue
                        src_path = Path(src_p)
                        out_fname = f"{short_hash}_{ns}_{clean_name}_{ch}.png"
                        dst_p = textures_dir / out_fname
                        if not dst_p.exists():
                            shutil.copy2(src_path, dst_p)
                        channel_files[ch] = f"textures/{out_fname}"

                canonical_key = canonical_texture_key(ns, path_key)
                full_key = f"{ns}:{path_key}"

                entry_record = {
                    "namespace": ns,
                    "texture_name": tex_name,
                    "texture_key": path_key,
                    "canonical_key": canonical_key,
                    "files": channel_files,
                    "is_animated": bool(has_animation),
                    "animation": anim_metadata,
                    "tint_info": tint_info,
                }

                textures_mapping[full_key] = entry_record
                textures_mapping[canonical_key] = entry_record
                if tex_name not in aliases_mapping:
                    aliases_mapping[tex_name] = canonical_key
                aliases_mapping[path_key] = canonical_key

            yield (0.90, "Writing standalone metadata index...", None)

            mapping_data = {
                "format_version": STANDALONE_FORMAT_VERSION,
                "stack_hash": stack_hash,
                "texture_count": len(valid_entries),
                "textures": textures_mapping,
                "aliases": aliases_mapping,
            }

            mapping_path = staging_dir / "standalone_mapping.json"
            with open(mapping_path, "w", encoding="utf-8") as fp:
                json.dump(mapping_data, fp, indent=2)

            # 4. Integrity Validation before Atomic Publish
            if not mapping_path.exists() or mapping_path.stat().st_size == 0:
                raise RuntimeError("Failed to generate valid standalone_mapping.json in staging directory.")

            for full_k, rec in textures_mapping.items():
                albedo_rel = rec["files"]["albedo"]
                if albedo_rel and not (staging_dir / albedo_rel).exists():
                    raise RuntimeError(f"Integrity check failed: missing precompiled albedo file '{albedo_rel}'")

            # 5. Atomic Publication
            yield (0.95, "Publishing standalone precompiled asset library...", None)
            if output_path.exists():
                shutil.rmtree(output_path, ignore_errors=True)
            staging_dir.rename(output_path)

            final_mapping_path = output_path / "standalone_mapping.json"
            outputs = {
                "mapping": final_mapping_path,
                "output_dir": output_path,
                "texture_count": len(valid_entries),
                "format_version": STANDALONE_FORMAT_VERSION,
            }

            yield (1.0, f"Standalone library precompiled successfully ({len(valid_entries)} textures).", outputs)

        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)

    def build(self, output_dir: Union[str, Path], progress_callback=None) -> dict:
        """Synchronously build the standalone asset library."""
        final_outputs = None
        for frac, msg, res in self.build_iter(output_dir):
            if progress_callback:
                progress_callback(frac, msg)
            if res is not None:
                final_outputs = res
        return final_outputs or {}
