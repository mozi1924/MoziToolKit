"""
Atlas Generator for Minecraft Resource Packs / JARs.
Generates unified texture atlas images (Albedo, Normal, Specular) and mapping JSON.
"""

import sys
import os
import json
import zipfile
from pathlib import Path
try:
    from .atlas_layout import FACE_ORDER
except ImportError:
    from atlas_layout import FACE_ORDER

try:
    from .dependencies import ensure_sys_paths, has_pillow
    ensure_sys_paths()
except (ImportError, ValueError):
    try:
        from dependencies import ensure_sys_paths, has_pillow
        ensure_sys_paths()
    except ImportError:
        pass

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    Image = None
    HAS_PIL = False


# Bump this whenever the on-disk atlas layout changes.  The replacement step
# uses it to avoid silently reusing an atlas produced by an older layout.
ATLAS_FORMAT_VERSION = 8


def _is_power_of_two(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def is_animated_texture(image, mcmeta: dict | None) -> bool:
    """
    Determine if a texture is truly animated based on its image dimensions and mcmeta metadata.

    A texture is animated if and only if:
    1. mcmeta is a dictionary containing an 'animation' dictionary; AND
    2. The animation contains multiple frames (frame_count > 1 derived from image height / frame height,
       or explicit frames list length > 1).
    Textures with only 'texture' or 'gui' settings (e.g. mipmap_strategy, alpha_cutoff_bias) or
    single-frame textures are static.
    """
    if not mcmeta or not isinstance(mcmeta, dict):
        return False
    anim = mcmeta.get("animation")
    if anim is None or not isinstance(anim, dict):
        return False

    if image is None:
        return True

    w, h = image.size
    frame_width = max(1, int(anim.get("width", w)))
    frame_height = max(1, int(anim.get("height", frame_width)))
    frame_count = max(1, h // frame_height) if frame_height > 0 else 1
    frames = anim.get("frames", [])

    return (frame_count > 1) or (isinstance(frames, list) and len(frames) > 1)


class AtlasGenerator:
    """
    Parses Minecraft block models and textures from a JAR archive, ZIP file, or directory.
    Constructs deduplicated, size-bounded atlas chunks:
    - Static textures are packed once each and referenced by every matching face.
    - Each animation owns independent vertical frame-strip chunk(s).
    """

    def __init__(
        self,
        resource_path: str | Path,
        default_tile_size: int = 16,
        max_chunk_size: int = 4096,
    ):
        self.resource_path = Path(resource_path)
        self.default_tile_size = default_tile_size
        self.max_chunk_size = max_chunk_size

        self.static_textures = {}    # name -> Image
        self.animated_textures = {}  # name -> {image: Image, mcmeta: dict}
        self.normal_textures = {}    # name -> Image
        self.specular_textures = {}  # name -> Image
        self.models = {}             # model_name -> dict JSON

        self.block_mappings = {}     # block_id -> 6 face texture names
        self.static_materials = []   # list of static material metadata
        self.animated_materials = [] # list of animated material metadata

    def load_resources(self):
        """Load PNG images, mcmeta animation data, and block models from source."""
        if not self.resource_path.exists():
            raise FileNotFoundError(f"Resource path not found: {self.resource_path}")

        if self.resource_path.is_dir():
            self._load_from_dir(self.resource_path)
        elif zipfile.is_zipfile(self.resource_path):
            self._load_from_zip(self.resource_path)
        else:
            raise ValueError(f"Unsupported resource format: {self.resource_path}")

    def _load_from_zip(self, zip_path: Path):
        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = zf.namelist()

            # 1. Index mcmetas
            mcmetas = {}
            for name in namelist:
                if name.startswith("assets/minecraft/textures/block/") and name.endswith(".png.mcmeta"):
                    stem = name.replace("assets/minecraft/textures/block/", "").replace(".png.mcmeta", "")
                    try:
                        mcmetas[stem.lower()] = json.loads(zf.read(name).decode("utf-8"))
                    except Exception:
                        pass

            # 2. Load models
            for name in namelist:
                if name.startswith("assets/minecraft/models/block/") and name.endswith(".json"):
                    stem = name.replace("assets/minecraft/models/block/", "").replace(".json", "")
                    try:
                        self.models[stem.lower()] = json.loads(zf.read(name).decode("utf-8"))
                    except Exception:
                        pass

            # 3. Load PNG textures
            for name in namelist:
                if name.startswith("assets/minecraft/textures/block/") and name.endswith(".png"):
                    stem = name.replace("assets/minecraft/textures/block/", "").replace(".png", "")
                    clean_stem = stem.lower()

                    channel = "albedo"
                    if clean_stem.endswith("_n"):
                        base_stem = clean_stem[:-2]
                        channel = "normal"
                    elif clean_stem.endswith("_s"):
                        base_stem = clean_stem[:-2]
                        channel = "specular"
                    else:
                        base_stem = clean_stem

                    try:
                        with zf.open(name) as img_file:
                            img = Image.open(img_file).convert("RGBA")
                            if channel == "normal":
                                self.normal_textures[base_stem] = img
                            elif channel == "specular":
                                self.specular_textures[base_stem] = img
                            else:
                                if is_animated_texture(img, mcmetas.get(base_stem)):
                                    self.animated_textures[base_stem] = {
                                        "image": img,
                                        "mcmeta": mcmetas[base_stem]
                                    }
                                else:
                                    self.static_textures[base_stem] = img
                    except Exception as e:
                        print(f"[AtlasGenerator] Warning: failed to load texture {name}: {e}")

    def _load_from_dir(self, dir_path: Path):
        textures_dir = dir_path / "assets" / "minecraft" / "textures" / "block"
        models_dir = dir_path / "assets" / "minecraft" / "models" / "block"

        # 1. Index mcmetas
        mcmetas = {}
        if textures_dir.exists():
            for root, _, files in os.walk(textures_dir):
                for f in files:
                    if f.endswith(".png.mcmeta"):
                        stem = f[:-11]
                        mcmeta_path = Path(root) / f
                        try:
                            with open(mcmeta_path, "r", encoding="utf-8") as fp:
                                mcmetas[stem.lower()] = json.load(fp)
                        except Exception:
                            pass

        # 2. Load models
        if models_dir.exists():
            for root, _, files in os.walk(models_dir):
                for f in files:
                    if f.endswith(".json"):
                        stem = f[:-5]
                        model_path = Path(root) / f
                        try:
                            with open(model_path, "r", encoding="utf-8") as fp:
                                self.models[stem.lower()] = json.load(fp)
                        except Exception:
                            pass

        # 3. Load PNG textures
        if textures_dir.exists():
            for root, _, files in os.walk(textures_dir):
                for f in files:
                    if f.endswith(".png"):
                        stem = f[:-4]
                        clean_stem = stem.lower()

                        channel = "albedo"
                        if clean_stem.endswith("_n"):
                            base_stem = clean_stem[:-2]
                            channel = "normal"
                        elif clean_stem.endswith("_s"):
                            base_stem = clean_stem[:-2]
                            channel = "specular"
                        else:
                            base_stem = clean_stem

                        img_path = Path(root) / f
                        try:
                            img = Image.open(img_path).convert("RGBA")
                            if channel == "normal":
                                self.normal_textures[base_stem] = img
                            elif channel == "specular":
                                self.specular_textures[base_stem] = img
                            else:
                                if is_animated_texture(img, mcmetas.get(base_stem)):
                                    self.animated_textures[base_stem] = {
                                        "image": img,
                                        "mcmeta": mcmetas[base_stem]
                                    }
                                else:
                                    self.static_textures[base_stem] = img
                        except Exception as e:
                            print(f"[AtlasGenerator] Warning: failed to load {img_path}: {e}")

    def resolve_model_textures(self, model_name: str, depth: int = 0) -> dict:
        """Recursively resolve texture variables from block model JSONs."""
        if depth > 10 or model_name not in self.models:
            return {}
        m = self.models[model_name]
        res = {}

        parent = m.get("parent")
        if parent and isinstance(parent, str):
            parent_clean = parent.replace("minecraft:block/", "").replace("block/", "").lower()
            res.update(self.resolve_model_textures(parent_clean, depth + 1))

        texs = m.get("textures", {})
        if isinstance(texs, dict):
            for k, v in texs.items():
                if isinstance(v, str):
                    res[k] = v.replace("minecraft:block/", "").replace("block/", "").lower()
        return res

    @staticmethod
    def expand_variables(tex_dict: dict) -> dict:
        """Resolve #variable references in texture dictionary."""
        resolved = dict(tex_dict)
        for _ in range(5):
            changed = False
            for k, v in list(resolved.items()):
                if v.startswith("#"):
                    var_key = v[1:]
                    if var_key in resolved and not resolved[var_key].startswith("#"):
                        resolved[k] = resolved[var_key]
                        changed = True
            if not changed:
                break
        return resolved

    def get_6_faces_for_model(self, model_name: str) -> dict:
        """
        Map block model to 6 face sub-textures:
        +X (East), -X (West), +Y (Up), -Y (Down), +Z (South), -Z (North).
        """
        raw_texs = self.resolve_model_textures(model_name)
        exp = self.expand_variables(raw_texs)

        fallback = list(exp.values())[0] if exp else model_name
        east = exp.get("east") or exp.get("side") or exp.get("all") or fallback
        west = exp.get("west") or exp.get("side") or exp.get("all") or east
        up = exp.get("up") or exp.get("top") or exp.get("end") or exp.get("all") or east
        down = exp.get("down") or exp.get("bottom") or exp.get("end") or exp.get("all") or east
        south = exp.get("south") or exp.get("side") or exp.get("all") or east
        north = exp.get("north") or exp.get("side") or exp.get("front") or exp.get("all") or east

        return {
            "+X": east,
            "-X": west,
            "+Y": up,
            "-Y": down,
            "+Z": south,
            "-Z": north
        }

    def build(self, output_dir: str | Path) -> dict:
        """Build deduplicated, size-bounded atlas chunks and their mapping."""
        if not HAS_PIL:
            raise ImportError("Pillow library is required for AtlasGenerator. Please install it using 'pip install pillow'.")
        self.load_resources()
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Determine tile size from standard square power-of-two static textures
        square_widths = [
            image.width for image in self.static_textures.values()
            if image.width == image.height and _is_power_of_two(image.width)
        ]
        if square_widths:
            tile_size = max(square_widths)
        else:
            tile_size = self.default_tile_size

        if tile_size > self.max_chunk_size:
            raise ValueError(f"Tile size {tile_size}px exceeds chunk limit {self.max_chunk_size}px.")
        tiles_per_row = self.max_chunk_size // tile_size
        capacity = tiles_per_row * tiles_per_row

        static_names = sorted(self.static_textures)
        chunks, texture_locations, outputs = [], {}, {"chunks": []}
        has_normal, has_specular = bool(self.normal_textures), bool(self.specular_textures)

        def tile_for(texture_name, channel):
            source = {
                "albedo": self.static_textures,
                "normal": self.normal_textures,
                "specular": self.specular_textures,
            }[channel].get(texture_name)
            if source is None:
                fill = (128, 128, 255, 255) if channel == "normal" else (0, 0, 0, 0)
                return Image.new("RGBA", (tile_size, tile_size), fill)
            return source.resize((tile_size, tile_size), Image.NEAREST)

        for first in range(0, len(static_names), capacity):
            names = static_names[first:first + capacity]
            chunk_id = len(chunks)
            rows = max(1, (len(names) + tiles_per_row - 1) // tiles_per_row)
            width, height = tiles_per_row * tile_size, rows * tile_size
            images = {"albedo": Image.new("RGBA", (width, height), (0, 0, 0, 0))}
            if has_normal:
                images["normal"] = Image.new("RGBA", (width, height), (128, 128, 255, 255))
            if has_specular:
                images["specular"] = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            files = {}
            for texture_id, texture_name in enumerate(names):
                x, y = (texture_id % tiles_per_row) * tile_size, (texture_id // tiles_per_row) * tile_size
                texture_locations[texture_name] = {
                    "chunk_id": chunk_id, "texture_id": texture_id,
                    "tile_column": texture_id % tiles_per_row, "tile_row": texture_id // tiles_per_row,
                    "kind": "static",
                    "frame_width": tile_size, "frame_height": tile_size,
                    "frame_count": 1, "frametime": 1, "interpolate": False,
                }
                for channel, image in images.items():
                    image.paste(tile_for(texture_name, channel), (x, y))
            for channel, image in images.items():
                filename = f"atlas_chunk_{chunk_id:03d}_{channel}.png"
                image.save(output_path / filename)
                files[channel] = filename
            chunks.append({
                "chunk_id": chunk_id, "kind": "static", "width": width, "height": height,
                "tile_size": tile_size, "tiles_per_row": tiles_per_row, "texture_count": len(names), "files": files,
            })
            outputs["chunks"].append(output_path / files["albedo"])

        # Animation strips stay byte-for-byte at their original dimensions.
        # They are packed as vertical columns (c1, c2, …) from left to right;
        # a strip is never wrapped or split merely to fill a row.
        animation_columns = []
        for animation_name in sorted(self.animated_textures):
            source = self.animated_textures[animation_name]
            image = source["image"]
            if image.width > self.max_chunk_size or image.height > self.max_chunk_size:
                raise ValueError(
                    f"Animation '{animation_name}' ({image.width}x{image.height}) exceeds "
                    f"the {self.max_chunk_size}px chunk limit and cannot be stored losslessly."
                )
            animation_columns.append((animation_name, image, source["mcmeta"].get("animation", {})))

        animations = []
        pending_columns, pending_width = [], 0

        def save_animation_chunk(columns):
            chunk_id = len(chunks)
            chunk_width = sum(image.width for _name, image, _meta in columns)
            chunk_height = max(image.height for _name, image, _meta in columns)
            images = {"albedo": Image.new("RGBA", (chunk_width, chunk_height), (0, 0, 0, 0))}
            if has_normal:
                images["normal"] = Image.new("RGBA", (chunk_width, chunk_height), (128, 128, 255, 255))
            if has_specular:
                images["specular"] = Image.new("RGBA", (chunk_width, chunk_height), (0, 0, 0, 0))

            x_offset = 0
            for texture_id, (name, image, metadata) in enumerate(columns):
                target_w = image.width
                target_h = image.height

                for channel, img_canvas in images.items():
                    if channel == "albedo":
                        source_img = image
                    elif channel == "normal":
                        source_img = self.normal_textures.get(name)
                    elif channel == "specular":
                        source_img = self.specular_textures.get(name)
                    else:
                        source_img = None

                    if source_img is not None:
                        src_w, src_h = source_img.size
                        # Resize width to match target_w if resolutions differ
                        if src_w != target_w:
                            scale_ratio = target_w / src_w
                            scaled_h = max(1, int(round(src_h * scale_ratio)))
                            source_img = source_img.resize((target_w, scaled_h), Image.NEAREST)
                            src_w, src_h = source_img.size

                        if src_h >= target_h:
                            img_canvas.paste(source_img.crop((0, 0, target_w, target_h)), (x_offset, 0))
                        else:
                            # Single frame or shorter strip: repeat/tile vertically to fill target_h
                            y = 0
                            while y < target_h:
                                h_chunk = min(src_h, target_h - y)
                                if h_chunk < src_h:
                                    img_canvas.paste(source_img.crop((0, 0, target_w, h_chunk)), (x_offset, y))
                                else:
                                    img_canvas.paste(source_img, (x_offset, y))
                                y += src_h

                # Minecraft permits non-square animation frames.  The frame
                # dimensions are defined by mcmeta when present; otherwise a
                # frame is as wide as the source image.  Do not infer both
                # dimensions from ``image.width``: that makes the shader step
                # into transparent padding for rectangular animations.
                frame_width = max(1, int(metadata.get("width", image.width)))
                frame_height = max(1, int(metadata.get("height", frame_width)))
                frame_count = max(1, image.height // frame_height)
                frametime = max(1, int(metadata.get("frametime", 2)))
                interpolate = bool(metadata.get("interpolate", False))
                texture_locations[name] = {
                    "chunk_id": chunk_id, "texture_id": texture_id, "kind": "animation",
                    "pixel_x": x_offset, "pixel_y": 0, "preview_frame": 0,
                    "frame_width": frame_width, "frame_height": frame_height,
                    "frame_count": frame_count, "frametime": frametime, "interpolate": interpolate,
                }
                animations.append({
                    "name": name, "chunk_id": chunk_id, "texture_id": texture_id,
                    "pixel_x": x_offset, "frame_count": frame_count,
                    "frame_width": frame_width, "frame_height": frame_height,
                    "frametime": frametime, "interpolate": interpolate,
                    "preview_frame": 0, "mcmeta": metadata,
                })
                x_offset += image.width

            files = {}
            for channel, img_canvas in images.items():
                filename = f"atlas_chunk_{chunk_id:03d}_{channel}.png"
                img_canvas.save(output_path / filename)
                files[channel] = filename

            chunks.append({
                "chunk_id": chunk_id, "kind": "animation", "width": chunk_width,
                "height": chunk_height, "texture_count": len(columns),
                "packing": "vertical_columns", "files": files,
            })
            outputs["chunks"].append(output_path / files["albedo"])

        for column in animation_columns:
            column_width = column[1].width
            if pending_columns and pending_width + column_width > self.max_chunk_size:
                save_animation_chunk(pending_columns)
                pending_columns, pending_width = [], 0
            pending_columns.append(column)
            pending_width += column_width
        if pending_columns:
            save_animation_chunk(pending_columns)

        materials = []
        all_material_names = sorted(set(self.models) | set(self.static_textures) | set(self.animated_textures))
        for material_id, name in enumerate(all_material_names):
            faces = self.get_6_faces_for_model(name) if name in self.models else {face: name for face in FACE_ORDER}
            materials.append({"material_id": material_id, "name": name, "faces": {
                face: texture_locations.get(texture_name) for face, texture_name in faces.items()
            }})

        mapping_data = {
            "format_version": ATLAS_FORMAT_VERSION, "max_chunk_size": self.max_chunk_size,
            "tile_size": tile_size, "face_order": list(FACE_ORDER), "chunks": chunks,
            "textures": texture_locations, "materials": materials, "animations": animations,
            "static_texture_count": len(static_names),
            "static_chunk_count": sum(chunk["kind"] == "static" for chunk in chunks),
            "animation_count": len(animations),
        }
        mapping_path = output_path / "atlas_mapping.json"
        with open(mapping_path, "w", encoding="utf-8") as fp:
            json.dump(mapping_data, fp, indent=2)
        outputs["mapping"] = mapping_path
        print(f"[AtlasGenerator] Built {len(chunks)} chunk(s), {len(static_names)} static texture(s), "
              f"and {len(animations)} animation(s).")
        return outputs


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate Minecraft Texture Atlas from Resource Pack / JAR.")
    parser.add_argument("resource_path", help="Path to resource pack ZIP/JAR or unpacked directory")
    parser.add_argument("-o", "--output", default="./dist_atlas", help="Output directory for generated atlas files")
    args = parser.parse_args()

    gen = AtlasGenerator(args.resource_path)
    gen.build(args.output)

