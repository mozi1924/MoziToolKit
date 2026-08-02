import json
import os
from pathlib import Path
import bpy

ALL_OPERATORS = {
    "object.mozi_adaptive_pixel_split": {
        "label": "Adaptive Pixel Split",
        "default_label": "Adaptive Pixel Split",
    },
    "mesh.mozi_select_hard_edges": {
        "label": "Select Hard & Sharp Edges",
        "default_label": "Select Hard & Sharp Edges",
    },
    "object.mozi_set_texture_interpolation_closest": {
        "label": "Set Image Interpolation to Closest",
        "default_label": "Set Image Interpolation to Closest",
    },
    "uv.mozi_scale_uv": {
        "label": "Scale UV Faces",
        "default_label": "Scale UV Faces",
    },
    "uv.mozi_select_transparent_faces": {
        "label": "Select Transparent Faces",
        "default_label": "Select Transparent Faces",
    },
}

DEFAULT_PRESETS = {
    "mesh": [
        {"operator": "object.mozi_adaptive_pixel_split", "label": "Adaptive Pixel Split", "enabled": True},
        {"operator": "mesh.mozi_select_hard_edges", "label": "Select Hard & Sharp Edges", "enabled": True},
        {"operator": "uv.mozi_select_transparent_faces", "label": "Select Transparent Faces", "enabled": True},
    ],
    "object": [
        {"operator": "object.mozi_adaptive_pixel_split", "label": "Adaptive Pixel Split", "enabled": True},
        {"operator": "object.mozi_set_texture_interpolation_closest", "label": "Set Image Interpolation to Closest", "enabled": True},
    ],
    "uv": [
        {"operator": "object.mozi_adaptive_pixel_split", "label": "Adaptive Pixel Split", "enabled": True},
        {"operator": "uv.mozi_scale_uv", "label": "Scale UV Faces", "enabled": True},
        {"operator": "uv.mozi_select_transparent_faces", "label": "Select Transparent Faces", "enabled": True},
    ],
}


def get_config_path() -> Path:
    """Return absolute path to user data config JSON file."""
    try:
        config_dir = Path(bpy.utils.user_resource("CONFIG")) / "MoziToolKit"
    except Exception:
        config_dir = Path.home() / ".config" / "blender" / "MoziToolKit"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "context_menus.json"


def load_config() -> dict:
    """Load configuration from JSON file or initialize with DEFAULT_PRESETS."""
    filepath = get_config_path()
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "views" in data:
                    return data["views"]
                elif isinstance(data, dict):
                    return data
        except Exception as e:
            print(f"[MoziToolKit] Error reading config file {filepath}: {e}")

    # Fallback to default presets and save
    save_config(DEFAULT_PRESETS)
    return json.loads(json.dumps(DEFAULT_PRESETS))


def save_config(views_data: dict) -> bool:
    """Save configuration to user JSON file."""
    filepath = get_config_path()
    try:
        data = {"version": 1, "views": views_data}
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[MoziToolKit] Error saving config file {filepath}: {e}")
        return False


def reset_config() -> dict:
    """Reset configuration to default presets and save."""
    default_copy = json.loads(json.dumps(DEFAULT_PRESETS))
    save_config(default_copy)
    return default_copy


def export_config(filepath: str, views_data: dict) -> bool:
    """Export configuration to specified filepath."""
    try:
        data = {"version": 1, "views": views_data}
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[MoziToolKit] Error exporting config to {filepath}: {e}")
        return False


def import_config(filepath: str) -> dict:
    """Import configuration from specified filepath."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            views = data.get("views", data) if isinstance(data, dict) else None
            if isinstance(views, dict):
                save_config(views)
                return views
    except Exception as e:
        print(f"[MoziToolKit] Error importing config from {filepath}: {e}")
    return None
