"""
Atlas Generator for Minecraft Resource Packs / JARs.
Generates size-bounded texture atlas images (Albedo, Normal, Specular) and mapping JSON.
"""

import sys
import os
import json
import zipfile
from pathlib import Path

from .constants import FACE_ORDER, ATLAS_FORMAT_VERSION
from ..system.dependencies import ensure_sys_paths, has_pillow

ensure_sys_paths()

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    Image = None
    HAS_PIL = False


def _is_power_of_two(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def is_animated_texture(image, mcmeta: dict | None) -> bool:
    """
    Determine if a texture is truly animated based on its image dimensions and mcmeta metadata.
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
    - Different namespaces are strictly isolated into separate chunks.
    - Native resolution is determined per-namespace via statistical mode.
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
        return f"{namespace}:block/{stem}"

    def _load_from_zip(self, zip_path: Path):
        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = zf.namelist()

            # 1. Index mcmetas
            mcmetas = {}
            for name in namelist:
                parts = Path(name).parts
                if len(parts) >= 5 and parts[:1] == ("assets",) and parts[2:4] == ("textures", "block") and name.endswith(".png.mcmeta"):
                    ns = parts[1].lower()
                    stem = "/".join(parts[4:])[:-11]
                    texture_name = self._texture_name(ns, stem)
                    try:
                        meta_obj = json.loads(zf.read(name).decode("utf-8"))
                        mcmetas[texture_name] = meta_obj
                        mcmetas[(ns, stem)] = meta_obj
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
                parts = Path(name).parts
                if len(parts) >= 5 and parts[:1] == ("assets",) and parts[2:4] == ("textures", "block") and name.endswith(".png"):
                    ns = parts[1].lower()
                    stem = "/".join(parts[4:])[:-4]
                    clean_stem = self._texture_name(ns, stem)

                    channel = "albedo"
                    if stem.endswith("_n"):
                        base_stem = stem[:-2]
                        clean_base_stem = clean_stem[:-2]
                        channel = "normal"
                    elif stem.endswith("_s"):
                        base_stem = stem[:-2]
                        clean_base_stem = clean_stem[:-2]
                        channel = "specular"
                    else:
                        base_stem = stem
                        clean_base_stem = clean_stem

                    try:
                        with zf.open(name) as img_file:
                            img = Image.open(img_file).convert("RGBA")
                            if channel == "normal":
                                self.normal_textures[clean_base_stem] = img
                                self.normal_by_namespace.setdefault(ns, {})[base_stem] = img
                            elif channel == "specular":
                                self.specular_textures[clean_base_stem] = img
                                self.specular_by_namespace.setdefault(ns, {})[base_stem] = img
                            else:
                                meta = mcmetas.get((ns, base_stem)) or mcmetas.get(clean_base_stem)
                                if is_animated_texture(img, meta):
                                    anim_data = {
                                        "image": img,
                                        "mcmeta": meta or {}
                                    }
                                    self.animated_textures[clean_base_stem] = anim_data
                                    self.animated_by_namespace.setdefault(ns, {})[base_stem] = anim_data
                                else:
                                    self.static_textures[clean_base_stem] = img
                                    self.static_by_namespace.setdefault(ns, {})[base_stem] = img
                    except Exception as e:
                        print(f"[AtlasGenerator] Warning: failed to load texture {name}: {e}")

    def _load_from_dir(self, dir_path: Path):
        models_dir = dir_path / "assets" / "minecraft" / "models" / "block"

        # 1. Index mcmetas
        mcmetas = {}
        assets_dir = dir_path / "assets"
        if assets_dir.exists():
            for namespace_dir in assets_dir.iterdir():
                textures_dir = namespace_dir / "textures" / "block"
                if not namespace_dir.is_dir() or not textures_dir.exists():
                    continue
                ns = namespace_dir.name.lower()
                for root, _, files in os.walk(textures_dir):
                    for f in files:
                        if f.endswith(".png.mcmeta"):
                            stem = (Path(root) / f).relative_to(textures_dir).as_posix()[:-11]
                            texture_name = self._texture_name(ns, stem)
                            mcmeta_path = Path(root) / f
                            try:
                                with open(mcmeta_path, "r", encoding="utf-8") as fp:
                                    meta_obj = json.load(fp)
                                    mcmetas[texture_name] = meta_obj
                                    mcmetas[(ns, stem)] = meta_obj
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
        if assets_dir.exists():
            for namespace_dir in assets_dir.iterdir():
                textures_dir = namespace_dir / "textures" / "block"
                if not namespace_dir.is_dir() or not textures_dir.exists():
                    continue
                ns = namespace_dir.name.lower()
                for root, _, files in os.walk(textures_dir):
                    for f in files:
                        if not f.endswith(".png"):
                            continue
                        stem = (Path(root) / f).relative_to(textures_dir).as_posix()[:-4]
                        clean_stem = self._texture_name(ns, stem)

                        channel = "albedo"
                        if stem.endswith("_n"):
                            base_stem = stem[:-2]
                            clean_base_stem = clean_stem[:-2]
                            channel = "normal"
                        elif stem.endswith("_s"):
                            base_stem = stem[:-2]
                            clean_base_stem = clean_stem[:-2]
                            channel = "specular"
                        else:
                            base_stem = stem
                            clean_base_stem = clean_stem

                        img_path = Path(root) / f
                        try:
                            img = Image.open(img_path).convert("RGBA")
                            if channel == "normal":
                                self.normal_textures[clean_base_stem] = img
                                self.normal_by_namespace.setdefault(ns, {})[base_stem] = img
                            elif channel == "specular":
                                self.specular_textures[clean_base_stem] = img
                                self.specular_by_namespace.setdefault(ns, {})[base_stem] = img
                            else:
                                meta = mcmetas.get((ns, base_stem)) or mcmetas.get(clean_base_stem)
                                if is_animated_texture(img, meta):
                                    anim_data = {
                                        "image": img,
                                        "mcmeta": meta or {}
                                    }
                                    self.animated_textures[clean_base_stem] = anim_data
                                    self.animated_by_namespace.setdefault(ns, {})[base_stem] = anim_data
                                else:
                                    self.static_textures[clean_base_stem] = img
                                    self.static_by_namespace.setdefault(ns, {})[base_stem] = img
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

    def build_iter(self, output_dir: str | Path):
        """
        Build deduplicated, size-bounded atlas chunks partitioned strictly per namespace.
        Yields (fraction: float, message: str, outputs: Optional[dict]).
        """
        if not HAS_PIL:
            raise ImportError("Pillow library is required for AtlasGenerator. Please install it using 'pip install pillow'.")
        from collections import Counter

        yield (0.05, "Reading textures and models from resource pack...", None)
        self.load_resources()
        yield (0.15, f"Loaded {len(self.static_textures)} static & {len(self.animated_textures)} animated textures", None)

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        all_namespaces = sorted(set(list(self.static_by_namespace.keys()) + list(self.animated_by_namespace.keys())))
        if "minecraft" in all_namespaces:
            all_namespaces.remove("minecraft")
            all_namespaces.insert(0, "minecraft")

        chunks = []
        texture_locations = {}
        animations = []
        outputs = {"chunks": []}
        has_normal = bool(self.normal_textures)
        has_specular = bool(self.specular_textures)

        total_ns = max(1, len(all_namespaces))
        for ns_idx, ns in enumerate(all_namespaces):
            ns_progress_base = 0.20 + 0.60 * (ns_idx / total_ns)
            static_map = self.static_by_namespace.get(ns, {})
            if static_map:
                yield (ns_progress_base, f"Packing static atlas chunks for namespace '{ns}'...", None)
                # Statistical mode for tile_size determination
                square_widths = [
                    image.width for image in static_map.values()
                    if image.width == image.height and _is_power_of_two(image.width)
                ]
                if square_widths:
                    counts = Counter(square_widths)
                    ns_tile_size = max(counts.keys(), key=lambda w: (counts[w], w))
                else:
                    ns_tile_size = self.default_tile_size

                if ns_tile_size > self.max_chunk_size:
                    raise ValueError(f"Tile size {ns_tile_size}px for namespace '{ns}' exceeds chunk limit {self.max_chunk_size}px.")

                tiles_per_row = self.max_chunk_size // ns_tile_size
                capacity = tiles_per_row * tiles_per_row
                static_stems = sorted(static_map.keys())

                def tile_for(stem, channel, tile_sz=ns_tile_size, namespace_val=ns):
                    source = {
                        "albedo": static_map,
                        "normal": self.normal_by_namespace.get(namespace_val, {}),
                        "specular": self.specular_by_namespace.get(namespace_val, {}),
                    }[channel].get(stem)
                    if source is None:
                        fill = (128, 128, 255, 255) if channel == "normal" else (0, 0, 0, 0)
                        return Image.new("RGBA", (tile_sz, tile_sz), fill)
                    if source.size == (tile_sz, tile_sz):
                        return source
                    return source.resize((tile_sz, tile_sz), Image.NEAREST)

                for first in range(0, len(static_stems), capacity):
                    names = static_stems[first:first + capacity]
                    chunk_id = len(chunks)
                    rows = max(1, (len(names) + tiles_per_row - 1) // tiles_per_row)
                    width = tiles_per_row * ns_tile_size
                    height = rows * ns_tile_size
                    images = {"albedo": Image.new("RGBA", (width, height), (0, 0, 0, 0))}
                    if has_normal:
                        images["normal"] = Image.new("RGBA", (width, height), (128, 128, 255, 255))
                    if has_specular:
                        images["specular"] = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                    files = {}

                    for texture_id, stem in enumerate(names):
                        x = (texture_id % tiles_per_row) * ns_tile_size
                        y = (texture_id // tiles_per_row) * ns_tile_size
                        raw_key = self._texture_name(ns, stem)
                        canonical_key = f"{ns}:block/{stem}"
                        loc_entry = {
                            "texture_key": canonical_key,
                            "namespace": ns,
                            "chunk_id": chunk_id,
                            "texture_id": texture_id,
                            "tile_column": texture_id % tiles_per_row,
                            "tile_row": texture_id // tiles_per_row,
                            "kind": "static",
                            "tile_size": ns_tile_size,
                            "frame_width": ns_tile_size,
                            "frame_height": ns_tile_size,
                            "frame_count": 1,
                            "frametime": 1,
                            "interpolate": False,
                        }
                        texture_locations[raw_key] = loc_entry
                        texture_locations[canonical_key] = loc_entry
                        if ns == "minecraft":
                            texture_locations[f"minecraft:{stem}"] = loc_entry
                            texture_locations[f"minecraft:block/{stem}"] = loc_entry

                        for channel, image in images.items():
                            image.paste(tile_for(stem, channel), (x, y))

                    for channel, image in images.items():
                        filename = f"atlas_chunk_{chunk_id:03d}_{channel}.png"
                        image.save(output_path / filename)
                        files[channel] = filename

                    chunks.append({
                        "chunk_id": chunk_id,
                        "namespace": ns,
                        "kind": "static",
                        "width": width,
                        "height": height,
                        "tile_size": ns_tile_size,
                        "tiles_per_row": tiles_per_row,
                        "texture_count": len(names),
                        "files": files,
                    })
                    outputs["chunks"].append(output_path / files["albedo"])

            # Animated textures for this namespace
            anim_map = self.animated_by_namespace.get(ns, {})
            if anim_map:
                yield (ns_progress_base + 0.05, f"Packing animated strip chunks for namespace '{ns}'...", None)
                animation_columns = []
                for stem in sorted(anim_map.keys()):
                    source = anim_map[stem]
                    image = source["image"]
                    if image.width > self.max_chunk_size or image.height > self.max_chunk_size:
                        raise ValueError(
                            f"Animation '{ns}:{stem}' ({image.width}x{image.height}) exceeds "
                            f"the {self.max_chunk_size}px chunk limit and cannot be stored losslessly."
                        )
                    animation_columns.append((stem, image, source["mcmeta"].get("animation", {})))

                def save_animation_chunk(columns, namespace_val=ns):
                    chunk_id = len(chunks)
                    # Align each column so its starting X pixel is a multiple of its width
                    x_calc = 0
                    for _s, img, _m in columns:
                        tw = img.width
                        x_calc = ((x_calc + tw - 1) // tw) * tw
                        x_calc += tw
                    chunk_width = max(16, x_calc)
                    chunk_height = max(img.height for _s, img, _m in columns)
                    images = {"albedo": Image.new("RGBA", (chunk_width, chunk_height), (0, 0, 0, 0))}
                    if has_normal:
                        images["normal"] = Image.new("RGBA", (chunk_width, chunk_height), (128, 128, 255, 255))
                    if has_specular:
                        images["specular"] = Image.new("RGBA", (chunk_width, chunk_height), (0, 0, 0, 0))

                    x_offset = 0
                    for texture_id, (stem, image, metadata) in enumerate(columns):
                        target_w = image.width
                        target_h = image.height
                        x_offset = ((x_offset + target_w - 1) // target_w) * target_w

                        for channel, img_canvas in images.items():
                            if channel == "albedo":
                                source_img = image
                            elif channel == "normal":
                                source_img = self.normal_by_namespace.get(namespace_val, {}).get(stem)
                            elif channel == "specular":
                                source_img = self.specular_by_namespace.get(namespace_val, {}).get(stem)
                            else:
                                source_img = None

                            if source_img is not None:
                                src_w, src_h = source_img.size
                                if src_w != target_w:
                                    scale_ratio = target_w / src_w
                                    scaled_h = max(1, int(round(src_h * scale_ratio)))
                                    source_img = source_img.resize((target_w, scaled_h), Image.NEAREST)
                                    src_w, src_h = source_img.size

                                if src_h >= target_h:
                                    img_canvas.paste(source_img.crop((0, 0, target_w, target_h)), (x_offset, 0))
                                else:
                                    y = 0
                                    while y < target_h:
                                        h_chunk = min(src_h, target_h - y)
                                        if h_chunk < src_h:
                                            img_canvas.paste(source_img.crop((0, 0, target_w, h_chunk)), (x_offset, y))
                                        else:
                                            img_canvas.paste(source_img, (x_offset, y))
                                        y += src_h

                        frame_width = max(1, int(metadata.get("width", image.width)))
                        frame_height = max(1, int(metadata.get("height", frame_width)))
                        frame_count = max(1, image.height // frame_height)
                        frametime = max(1, int(metadata.get("frametime", 2)))
                        interpolate = bool(metadata.get("interpolate", False))
                        raw_name = self._texture_name(namespace_val, stem)
                        canonical_key = f"{namespace_val}:block/{stem}"

                        anim_loc = {
                            "texture_key": canonical_key,
                            "namespace": namespace_val,
                            "chunk_id": chunk_id,
                            "texture_id": texture_id,
                            "kind": "animation",
                            "pixel_x": x_offset,
                            "pixel_y": 0,
                            "preview_frame": 0,
                            "frame_width": frame_width,
                            "frame_height": frame_height,
                            "frame_count": frame_count,
                            "frametime": frametime,
                            "interpolate": interpolate,
                        }
                        texture_locations[raw_name] = anim_loc
                        texture_locations[canonical_key] = anim_loc
                        if namespace_val == "minecraft":
                            texture_locations[f"minecraft:{stem}"] = anim_loc
                            texture_locations[f"minecraft:block/{stem}"] = anim_loc

                        animations.append({
                            "name": raw_name,
                            "texture_key": canonical_key,
                            "namespace": namespace_val,
                            "chunk_id": chunk_id,
                            "texture_id": texture_id,
                            "pixel_x": x_offset,
                            "frame_count": frame_count,
                            "frame_width": frame_width,
                            "frame_height": frame_height,
                            "frametime": frametime,
                            "interpolate": interpolate,
                            "preview_frame": 0,
                            "mcmeta": metadata,
                        })
                        x_offset += target_w

                    files = {}
                    for channel, img_canvas in images.items():
                        filename = f"atlas_chunk_{chunk_id:03d}_{channel}.png"
                        img_canvas.save(output_path / filename)
                        files[channel] = filename

                    chunks.append({
                        "chunk_id": chunk_id,
                        "namespace": namespace_val,
                        "kind": "animation",
                        "width": chunk_width,
                        "height": chunk_height,
                        "texture_count": len(columns),
                        "packing": "vertical_columns",
                        "files": files,
                    })
                    outputs["chunks"].append(output_path / files["albedo"])

                pending_columns, pending_width = [], 0
                for column in animation_columns:
                    column_width = column[1].width
                    aligned_next_width = ((pending_width + column_width - 1) // column_width) * column_width + column_width
                    if pending_columns and aligned_next_width > self.max_chunk_size:
                        save_animation_chunk(pending_columns)
                        pending_columns, pending_width = [], 0
                        aligned_next_width = column_width
                    pending_columns.append(column)
                    pending_width = aligned_next_width
                if pending_columns:
                    save_animation_chunk(pending_columns)

        yield (0.85, "Mapping materials and block faces...", None)
        materials = []
        all_material_names = sorted(set(self.models) | set(self.static_textures) | set(self.animated_textures))
        for material_id, name in enumerate(all_material_names):
            faces = self.get_6_faces_for_model(name) if name in self.models else {face: name for face in FACE_ORDER}
            materials.append({"material_id": material_id, "name": name, "faces": {
                face: texture_locations.get(texture_name) for face, texture_name in faces.items()
            }})

        # Determine base tile_size for mapping summary (preference to minecraft)
        mc_chunk = next((c for c in chunks if c.get("namespace") == "minecraft" and "tile_size" in c), None)
        primary_tile_size = mc_chunk["tile_size"] if mc_chunk else (chunks[0].get("tile_size", self.default_tile_size) if chunks else self.default_tile_size)

        mapping_data = {
            "format_version": ATLAS_FORMAT_VERSION,
            "provenance_schema_version": 1,
            "max_chunk_size": self.max_chunk_size,
            "tile_size": primary_tile_size,
            "face_order": list(FACE_ORDER),
            "chunks": chunks,
            "textures": texture_locations,
            "materials": materials,
            "animations": animations,
            "static_texture_count": len(self.static_textures),
            "static_chunk_count": sum(chunk["kind"] == "static" for chunk in chunks),
            "animation_count": len(animations),
        }
        mapping_path = output_path / "atlas_mapping.json"
        with open(mapping_path, "w", encoding="utf-8") as fp:
            json.dump(mapping_data, fp, indent=2)
        outputs["mapping"] = mapping_path

        yield (1.0, f"Atlas built: {len(chunks)} chunks, {len(animations)} animations", outputs)

    def build(self, output_dir: str | Path, progress_callback=None) -> dict:
        """Build deduplicated, size-bounded atlas chunks partitioned strictly per namespace."""
        final_outputs = None
        for frac, msg, res in self.build_iter(output_dir):
            if progress_callback:
                progress_callback(frac, msg)
            if res is not None:
                final_outputs = res
        return final_outputs or {}



if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate Minecraft Texture Atlas from Resource Pack / JAR.")
    parser.add_argument("resource_path", help="Path to resource pack ZIP/JAR or unpacked directory")
    parser.add_argument("-o", "--output", default="./dist_atlas", help="Output directory for generated atlas files")
    args = parser.parse_args()

    gen = AtlasGenerator(args.resource_path)
    gen.build(args.output)
