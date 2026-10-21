"""Legacy-vs-baked PBR visual regression harness (headless Blender).

Renders the same plane twice for each test block:

1. legacy: raw ``_n`` / ``_s`` + ``LabPBR 1.3 Decoder``
2. baked:  Rust-produced ``_n`` / ``_orm`` / ``_aux`` + standard Principled graph

It then reports MAE / RMSE / PSNR. This is a developer tool, not a CI test; it needs a
real vanilla client JAR and a LabPBR resource pack (SPBR-21 by default).

Run with the Blender binary used by the test suite:

```bash
cd MoziToolKit
BLENDER_USER_CONFIG="$PWD/.blender-test-config" \
MTK_TEST_SITE_PACKAGES="$("../libmozitoolkit/.venv/bin/python" -c 'import site; print(site.getsitepackages()[0])')" \
  blender --background --factory-startup --python tools/validate_pbr_visual_regression.py
```

Environment variables:

- ``MTK_VISUAL_VANILLA_JAR``: vanilla client JAR (default ``../26.2-Fabric.jar``)
- ``MTK_VISUAL_RESOURCE_PACK``: LabPBR pack zip (default ``../SPBR-21.zip`` or
  ``~/Downloads/SPBR-21.zip``)
- ``MTK_VISUAL_BLOCKS``: comma-separated block keys (default
  ``stone,gold_block,oak_planks``)
- ``MTK_VISUAL_PSNR_MIN``: fail below this PSNR in dB (default ``40``)
- ``MTK_VISUAL_OUTPUT``: output directory (default a new temp dir)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import bpy
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent

# Blender is started from the MoziToolKit directory in the documented command.
sys.path.insert(0, str(WORKSPACE_ROOT))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "dev" / "lib"))

try:
    import libmtk_py as mtk
except ImportError as exc:  # pragma: no cover - developer tool
    raise SystemExit(f"libmtk_py is not importable: {exc}")

from MoziToolKit.utils.materials.builder.image_utils import ensure_material_node_tree
from MoziToolKit.utils.materials.builder.pbr_graph import build_pbr_shading


def _first_existing(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    raise SystemExit(f"None of these assets exist: {candidates}")


def _load_decoder():
    """Import the legacy decoder from its current or legacy location."""
    try:
        from MoziToolKit.utils.legacy.materials.labpbr_decoder import ensure_labpbr_decoder
        return ensure_labpbr_decoder
    except ImportError:
        pass
    try:
        from MoziToolKit.utils.node_groups.labpbr import ensure_labpbr_decoder
        return ensure_labpbr_decoder
    except ImportError:
        raise RuntimeError(
            "Legacy LabPBR decoder generator has been removed. "
            "Visual regression oracle against live generator is no longer available."
        )


def _read_pack_texture(pack_path: Path, relative: str) -> bytes:
    if pack_path.is_dir():
        return (pack_path / relative).read_bytes()
    with zipfile.ZipFile(pack_path) as archive:
        return archive.read(relative)


def _extract_raw_textures(pack_path: Path, block: str, output_dir: Path) -> dict[str, Path]:
    paths = {}
    for suffix in ("", "_n", "_s"):
        relative = f"assets/minecraft/textures/block/{block}{suffix}.png"
        target = output_dir / f"{block}{suffix}.png"
        target.write_bytes(_read_pack_texture(pack_path, relative))
        paths[suffix] = target
    return paths


def _load_image(path: Path, colorspace: str):
    image = bpy.data.images.load(str(path), check_existing=True)
    image.colorspace_settings.name = colorspace
    return image


def _add_texture(nodes, image, location):
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    texture.interpolation = "Closest"
    texture.extension = "CLIP"
    texture.location = location
    return texture


def _build_legacy_material(block: str, raw: dict[str, Path]):
    ensure_labpbr_decoder = _load_decoder()
    material = bpy.data.materials.new(f"LEGACY:{block}")
    tree = ensure_material_node_tree(material)
    nodes, links = tree.nodes, tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (900, 0)
    uv = nodes.new("ShaderNodeUVMap")
    uv.uv_map = "UVMap"
    uv.location = (-1000, 0)

    albedo = _add_texture(nodes, _load_image(raw[""], "sRGB"), (-700, 300))
    normal = _add_texture(nodes, _load_image(raw["_n"], "Non-Color"), (-700, 0))
    specular = _add_texture(nodes, _load_image(raw["_s"], "Non-Color"), (-700, -300))
    for texture in (albedo, normal, specular):
        links.new(uv.outputs["UV"], texture.inputs["Vector"])

    decoder = nodes.new("ShaderNodeGroup")
    decoder.node_tree = ensure_labpbr_decoder()
    decoder.name = "LabPBR Decoder"
    decoder.location = (0, 0)
    decoder.inputs["Enable PBR (0-1)"].default_value = 1.0
    decoder.inputs["Emission Strength"].default_value = 5.0
    decoder.inputs["Subsurface Scale"].default_value = 0.1
    decoder.inputs["Hardcoded Emission"].default_value = 0.0
    decoder.inputs["Thin Wall"].default_value = False
    decoder.inputs["Transmission Weight"].default_value = 0.0
    decoder.inputs["Sticker Threshold"].default_value = 0.55
    decoder.inputs["Disable Subsurface"].default_value = False
    decoder.inputs["Displacement Scale"].default_value = 0.0

    links.new(albedo.outputs["Color"], decoder.inputs["Albedo Color"])
    links.new(albedo.outputs["Alpha"], decoder.inputs["Albedo Alpha"])
    links.new(normal.outputs["Color"], decoder.inputs["Normal (_n) Color"])
    links.new(normal.outputs["Alpha"], decoder.inputs["Normal (_n) Alpha (Height)"])
    links.new(specular.outputs["Color"], decoder.inputs["Specular (_s) Color"])
    links.new(specular.outputs["Alpha"], decoder.inputs["Specular (_s) Alpha (Emission)"])
    links.new(decoder.outputs["BSDF"], output.inputs["Surface"])
    links.new(decoder.outputs["Displacement"], output.inputs["Displacement"])
    return material


def _build_baked_material(block: str, sheets: Path):
    material = bpy.data.materials.new(f"BAKED:{block}")
    tree = ensure_material_node_tree(material)
    nodes, links = tree.nodes, tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (900, 0)
    uv = nodes.new("ShaderNodeUVMap")
    uv.uv_map = "UVMap"
    uv.location = (-1000, 0)

    albedo = _add_texture(nodes, _load_image(sheets / "albedo.png", "sRGB"), (-700, 300))
    normal = _add_texture(nodes, _load_image(sheets / "normal.png", "Non-Color"), (-700, 0))
    orm = _add_texture(nodes, _load_image(sheets / "orm.png", "Non-Color"), (-700, -300))
    aux = _add_texture(nodes, _load_image(sheets / "aux.png", "Non-Color"), (-700, -600))
    for texture in (albedo, normal, orm, aux):
        links.new(uv.outputs["UV"], texture.inputs["Vector"])

    build_pbr_shading(
        nodes,
        links,
        output,
        None,
        base_color=albedo.outputs["Color"],
        alpha=albedo.outputs["Alpha"],
        normal_color=normal.outputs["Color"],
        orm_color=orm.outputs["Color"],
        orm_alpha=orm.outputs["Alpha"],
        aux_color=aux.outputs["Color"],
        disable_subsurface=False,
        emission_strength=5.0,
        subsurface_method="BURLEY",
    )
    return material


def _set_plane_uv(plane, uv_bounds=None):
    u0, v0, u1, v1 = uv_bounds or (0.0, 0.0, 1.0, 1.0)
    corners = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
    mesh = plane.data
    uv = mesh.uv_layers.active or mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for index, loop_index in enumerate(polygon.loop_indices):
            uv.data[loop_index].uv = corners[index % 4]


def _read_render(path: Path) -> np.ndarray:
    image = bpy.data.images.load(str(path), check_existing=False)
    image.colorspace_settings.name = "Non-Color"
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    bpy.data.images.remove(image)
    return pixels.reshape(height, width, 4)[:, :, :3]


def _compare(legacy_path: Path, baked_path: Path) -> tuple[float, float, float, float]:
    legacy = _read_render(legacy_path)
    baked = _read_render(baked_path)
    difference = np.abs(legacy - baked)
    mae = float(difference.mean())
    rmse = float(np.sqrt(((legacy - baked) ** 2).mean()))
    psnr = 20.0 * np.log10(1.0 / max(rmse, 1e-6))
    height, width = legacy.shape[:2]
    crop = difference[height // 4 : height * 3 // 4, width // 4 : width * 3 // 4]
    return mae, rmse, psnr, float(crop.mean())


def main() -> None:
    vanilla_jar = Path(
        os.environ.get(
            "MTK_VISUAL_VANILLA_JAR",
            str(WORKSPACE_ROOT / "26.2-Fabric.jar"),
        )
    )
    resource_pack = _first_existing(
        Path(os.environ["MTK_VISUAL_RESOURCE_PACK"])
        if os.environ.get("MTK_VISUAL_RESOURCE_PACK")
        else None,
        WORKSPACE_ROOT / "SPBR-21.zip",
        Path.home() / "Downloads" / "SPBR-21.zip",
    )
    if not vanilla_jar.exists():
        raise SystemExit(f"vanilla client JAR not found: {vanilla_jar}")

    output_dir = Path(
        os.environ.get("MTK_VISUAL_OUTPUT")
        or tempfile.mkdtemp(prefix="mtk-pbr-visual-")
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw"
    sheets_root = output_dir / "sheets"
    raw_dir.mkdir(exist_ok=True)
    sheets_root.mkdir(exist_ok=True)

    blocks = [
        block.strip()
        for block in os.environ.get("MTK_VISUAL_BLOCKS", "stone,gold_block,oak_planks").split(",")
        if block.strip()
    ]
    psnr_min = float(os.environ.get("MTK_VISUAL_PSNR_MIN", "40"))

    stack = mtk.ResourcePackStack()
    assert stack.add_zip_pack(str(vanilla_jar)), vanilla_jar
    assert stack.add_zip_pack(str(resource_pack)), resource_pack
    if not stack.has_vanilla_client_base():
        raise SystemExit("resource stack has no vanilla client base")

    cache_dir = output_dir / "cache"
    cache_dir.mkdir(exist_ok=True)
    result = mtk.precompile_all_assets(
        stack,
        str(cache_dir),
        atlas_category="blocks",
        max_atlas_width=4096,
        max_atlas_height=4096,
        compile_atlas=True,
        compile_models=False,
    )
    if not result.success:
        raise SystemExit("precompile failed")

    cache = mtk.AssetCache.open(str(result.package_path))
    mapping = json.loads(cache.load_atlas_mapping())

    # Reset scene.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for material in list(bpy.data.materials):
        bpy.data.materials.remove(material)

    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except Exception:
        scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.world.color = (0.04, 0.04, 0.04)
    try:
        scene.eevee.taa_render_samples = 32
    except Exception:
        pass

    bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0, 0, 0))
    plane = bpy.context.active_object
    plane.name = "PBRVisualRegressionPlane"

    bpy.ops.object.camera_add(location=(0, 0, 4))
    camera = bpy.context.active_object
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 2.2
    scene.camera = camera

    bpy.ops.object.light_add(type="AREA", location=(2.2, -2.2, 4.0))
    light = bpy.context.active_object
    light.data.energy = 500.0
    light.data.size = 4.0

    bpy.ops.object.empty_add(location=(0, 0, 0))
    target = bpy.context.active_object
    for obj in (camera, light):
        constraint = obj.constraints.new("TRACK_TO")
        constraint.target = target
        constraint.track_axis = "TRACK_NEGATIVE_Z"
        constraint.up_axis = "UP_Y"

    failures = []
    print(f"OUTPUT {output_dir}")
    print(f"PACK {resource_pack}")
    for block in blocks:
        key = f"minecraft:block/{block}"
        sprite = mapping["sprites"][key]
        chunk_id = sprite["chunk_id"]
        chunk = next(item for item in mapping["chunks"] if item["chunk_id"] == chunk_id)
        stem = chunk.get("file_stem") or f"blocks_chunk_{chunk['category_chunk_index']:03d}"

        sheets = sheets_root / stem
        sheets.mkdir(exist_ok=True)
        for suffix, target_name in (
            ("", "albedo.png"),
            ("_n", "normal.png"),
            ("_orm", "orm.png"),
            ("_aux", "aux.png"),
        ):
            cache.extract_atlas_texture(f"{stem}{suffix}.png", str(sheets / target_name))

        raw = _extract_raw_textures(resource_pack, block, raw_dir)

        plane.data.materials.clear()
        legacy_material = _build_legacy_material(block, raw)
        plane.data.materials.append(legacy_material)
        _set_plane_uv(plane, None)
        legacy_path = output_dir / f"legacy_{block}.png"
        scene.render.filepath = str(legacy_path)
        bpy.ops.render.render(write_still=True)

        baked_material = _build_baked_material(block, sheets)
        plane.data.materials.clear()
        plane.data.materials.append(baked_material)
        _set_plane_uv(plane, sprite["uv_bounds"])
        baked_path = output_dir / f"baked_{block}.png"
        scene.render.filepath = str(baked_path)
        bpy.ops.render.render(write_still=True)

        mae, rmse, psnr, crop_mae = _compare(legacy_path, baked_path)
        passed = psnr >= psnr_min
        print(
            f"{block}: MAE={mae:.6f} RMSE={rmse:.6f} PSNR={psnr:.2f}dB "
            f"crop_MAE={crop_mae:.6f} {'PASS' if passed else 'FAIL'}"
        )
        if not passed:
            failures.append(block)

    if failures:
        raise SystemExit(f"visual regression below {psnr_min} dB: {failures}")
    print("PASS: all blocks are within the legacy-vs-baked tolerance")


if __name__ == "__main__":
    main()
