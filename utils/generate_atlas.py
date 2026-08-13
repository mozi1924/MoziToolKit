"""
Atlas Generator for Minecraft Resource Packs / JARs.
Generates unified texture atlas images (Albedo, Normal, Specular) and mapping JSON.
"""

import os
import json
import zipfile
from pathlib import Path
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    Image = None
    HAS_PIL = False


class AtlasGenerator:
    """
    Parses Minecraft block models and textures from a JAR archive, ZIP file, or directory.
    Constructs a unified texture atlas:
    - Static materials: 1 row per material, 6 face tiles: [+X, -X, +Y, -Y, +Z, -Z].
    - Animated materials: 1 column per animation, vertical frame strips.
    """

    def __init__(self, resource_path: str | Path, default_tile_size: int = 16):
        self.resource_path = Path(resource_path)
        self.default_tile_size = default_tile_size

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
                                if base_stem in mcmetas:
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
                                if base_stem in mcmetas:
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
        """Build the atlas image files and mapping JSON."""
        if not HAS_PIL:
            raise ImportError("Pillow library is required for AtlasGenerator. Please install it using 'pip install pillow'.")

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        self.load_resources()

        # 1. Index all block models and single static textures alphabetically (a-z)
        all_materials = set()
        for model_name in self.models.keys():
            all_materials.add(model_name)
        for tex_name in self.static_textures.keys():
            all_materials.add(tex_name)

        sorted_materials = sorted(all_materials)

        # 2. Assign Material IDs and resolve face mappings
        material_list = []
        material_id_counter = 0

        for mat_name in sorted_materials:
            if mat_name in self.models:
                faces = self.get_6_faces_for_model(mat_name)
            else:
                faces = {
                    "+X": mat_name,
                    "-X": mat_name,
                    "+Y": mat_name,
                    "-Y": mat_name,
                    "+Z": mat_name,
                    "-Z": mat_name
                }

            material_entry = {
                "material_id": material_id_counter,
                "name": mat_name,
                "faces": faces
            }
            material_list.append(material_entry)
            material_id_counter += 1

        # 3. Sort animated textures
        sorted_animated = sorted(self.animated_textures.keys())
        anim_list = []
        for anim_id, anim_name in enumerate(sorted_animated):
            anim_data = self.animated_textures[anim_name]
            img = anim_data["image"]
            frame_width = img.width
            total_frames = img.height // frame_width if frame_width > 0 else 1

            anim_entry = {
                "anim_col_id": anim_id,
                "name": anim_name,
                "frame_width": frame_width,
                "total_frames": max(1, total_frames),
                "mcmeta": anim_data["mcmeta"].get("animation", {})
            }
            anim_list.append(anim_entry)

        # 4. Compute Atlas dimensions
        tile_size = self.default_tile_size
        num_static_rows = len(material_list)
        num_anim_cols = len(anim_list)

        static_width = 6 * tile_size
        anim_width = num_anim_cols * tile_size
        atlas_width = static_width + anim_width

        static_height = num_static_rows * tile_size
        max_anim_frames = max([a["total_frames"] for a in anim_list], default=1)
        anim_height = max_anim_frames * tile_size
        atlas_height = max(static_height, anim_height, tile_size)

        print(f"[AtlasGenerator] Building Atlas: {atlas_width}x{atlas_height} px "
              f"({num_static_rows} static materials, {num_anim_cols} animated columns)")

        # Blank image initialization
        blank_albedo = Image.new("RGBA", (atlas_width, atlas_height), (0, 0, 0, 0))
        blank_normal = Image.new("RGBA", (atlas_width, atlas_height), (128, 128, 255, 255))
        blank_specular = Image.new("RGBA", (atlas_width, atlas_height), (0, 0, 0, 0))

        has_normal = bool(self.normal_textures)
        has_specular = bool(self.specular_textures)

        # Helper to get sub-tile image
        def get_tile(tex_name, channel="albedo"):
            if channel == "albedo":
                if tex_name in self.static_textures:
                    return self.static_textures[tex_name]
                elif tex_name in self.animated_textures:
                    # Return first frame of animated texture as fallback tile
                    img = self.animated_textures[tex_name]["image"]
                    return img.crop((0, 0, img.width, img.width))
            elif channel == "normal" and tex_name in self.normal_textures:
                return self.normal_textures[tex_name]
            elif channel == "specular" and tex_name in self.specular_textures:
                return self.specular_textures[tex_name]

            # Fallback placeholder transparent image
            return Image.new("RGBA", (tile_size, tile_size), (0, 0, 0, 0))

        # 5. Paste static materials into rows
        face_order = ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]
        for mat in material_list:
            row = mat["material_id"]
            y_offset = row * tile_size

            for face_idx, face_dir in enumerate(face_order):
                x_offset = face_idx * tile_size
                tex_name = mat["faces"][face_dir]

                alb_tile = get_tile(tex_name, "albedo").resize((tile_size, tile_size), Image.NEAREST)
                blank_albedo.paste(alb_tile, (x_offset, y_offset))

                if has_normal:
                    norm_tile = get_tile(tex_name, "normal").resize((tile_size, tile_size), Image.NEAREST)
                    blank_normal.paste(norm_tile, (x_offset, y_offset))

                if has_specular:
                    spec_tile = get_tile(tex_name, "specular").resize((tile_size, tile_size), Image.NEAREST)
                    blank_specular.paste(spec_tile, (x_offset, y_offset))

        # 6. Paste animated materials into columns (starting at x = static_width)
        for anim in anim_list:
            col = anim["anim_col_id"]
            x_offset = static_width + col * tile_size

            anim_name = anim["name"]
            anim_img = self.animated_textures[anim_name]["image"]

            # Resize width if necessary to fit tile_size
            if anim_img.width != tile_size:
                scaled_h = int(anim_img.height * (tile_size / anim_img.width))
                anim_img = anim_img.resize((tile_size, scaled_h), Image.NEAREST)

            blank_albedo.paste(anim_img, (x_offset, 0))

            if has_normal and anim_name in self.normal_textures:
                norm_img = self.normal_textures[anim_name]
                if norm_img.width != tile_size:
                    scaled_h = int(norm_img.height * (tile_size / norm_img.width))
                    norm_img = norm_img.resize((tile_size, scaled_h), Image.NEAREST)
                blank_normal.paste(norm_img, (x_offset, 0))

            if has_specular and anim_name in self.specular_textures:
                spec_img = self.specular_textures[anim_name]
                if spec_img.width != tile_size:
                    scaled_h = int(spec_img.height * (tile_size / spec_img.width))
                    spec_img = spec_img.resize((tile_size, scaled_h), Image.NEAREST)
                blank_specular.paste(spec_img, (x_offset, 0))

        # 7. Save PNG outputs
        albedo_path = output_path / "atlas_albedo.png"
        blank_albedo.save(albedo_path)
        print(f"[AtlasGenerator] Saved {albedo_path}")

        outputs = {"albedo": albedo_path}

        if has_normal:
            normal_path = output_path / "atlas_normal.png"
            blank_normal.save(normal_path)
            outputs["normal"] = normal_path
            print(f"[AtlasGenerator] Saved {normal_path}")

        if has_specular:
            specular_path = output_path / "atlas_specular.png"
            blank_specular.save(specular_path)
            outputs["specular"] = specular_path
            print(f"[AtlasGenerator] Saved {specular_path}")

        # 8. Save mapping JSON metadata
        mapping_data = {
            "tile_size": tile_size,
            "atlas_width": atlas_width,
            "atlas_height": atlas_height,
            "static_materials_count": len(material_list),
            "animated_columns_count": len(anim_list),
            "face_order": face_order,
            "materials": material_list,
            "animations": anim_list
        }

        mapping_path = output_path / "atlas_mapping.json"
        with open(mapping_path, "w", encoding="utf-8") as fp:
            json.dump(mapping_data, fp, indent=2)

        print(f"[AtlasGenerator] Saved mapping {mapping_path}")

        outputs["mapping"] = mapping_path
        return outputs


if __name__ == "__main__":
    import sys
    jar_file = sys.argv[1] if len(sys.argv) > 1 else "/Users/jaxlocke/26.2-Fabric.jar"
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "./dist_atlas"

    gen = AtlasGenerator(jar_file)
    gen.build(out_dir)
