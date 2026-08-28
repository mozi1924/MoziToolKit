"""
Material replacement and reconstruction pipeline step.
Lightweight coordinator that routes between Atlas and Standalone replacement engines.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, Union
import bpy

from ..progress import ProgressUpdate
from ..step import PipelineStep, StepResult
from ...utils.materials.pack import (
    ZipResourcePack,
    ResourcePackStack,
    get_configured_pack_stack,
)
from ...utils.materials.pipeline import (
    detect_material_mode,
)
from ...utils.materials.constants import (
    ATTR_ATLAS_CHUNK_ID,
    ATTR_ATLAS_TEXTURE_ID,
    ATTR_SOURCE_TEXTURE_KEY,
)
from ...utils.materials.atlas import AtlasReplacementEngine
from ...utils.materials.standalone import StandaloneReplacementEngine


class StepReplaceMaterial(PipelineStep):
    """
    Modular PipelineStep for replacing and reconstructing materials from a Minecraft Java Resource Pack.
    Supports both Atlas and Standalone material generation modes.
    """

    name = "replace_material"
    description = "Replace and reconstruct materials from Minecraft Java Resource Pack"

    def execute_iter(self, pipeline_context) -> Iterator[Union[ProgressUpdate, StepResult]]:
        pack_stack = pipeline_context.get_param("pack_stack")
        zip_path = pipeline_context.get_param("zip_path")
        pack_textures = pipeline_context.get_param("pack_textures", True)
        material_mode = pipeline_context.get_param("material_mode", "ATLAS")
        biome_preset = pipeline_context.get_param("biome_preset", "PLAINS")

        if not pack_stack:
            if zip_path and Path(zip_path).exists():
                try:
                    pack = ZipResourcePack(zip_path)
                    pack_stack = get_configured_pack_stack(pack)
                except Exception as e:
                    yield StepResult.failed(f"Failed to load resource pack: {e}")
                    return
            else:
                pack_stack = get_configured_pack_stack()

        if not pack_stack or not pack_stack.packs:
            yield StepResult.failed(
                "No active resource packs or Minecraft JARs configured. "
                "Please configure your Resource Pack Stack in Edit > Preferences > Add-ons > MoziToolKit and click 'Precompile / Rebuild Stack Atlas Cache'."
            )
            return

        if material_mode == "STANDALONE":
            if not pack_stack.is_standalone_baked():
                yield StepResult.failed(
                    "The configured Resource Pack Stack has not been precompiled for Standalone mode. "
                    "Please go to Edit > Preferences > Add-ons > MoziToolKit and click 'Precompile / Rebuild Stack Atlas Cache'."
                )
                return
        else:
            if not pack_stack.is_stack_baked():
                yield StepResult.failed(
                    "The configured Resource Pack Stack has not been precompiled. "
                    "Please go to Edit > Preferences > Add-ons > MoziToolKit and click 'Precompile / Rebuild Stack Atlas Cache'."
                )
                return

        pack = pack_stack.packs[0]

        target_objects = pipeline_context.target_objects
        if not target_objects:
            yield StepResult.failed("No objects selected for material replacement.")
            return

        yield ProgressUpdate(0.05, 1.0, "Loading Minecraft resource pack stack...")

        if pipeline_context.is_cancelled:
            yield StepResult.cancelled("Material replacement cancelled by user.")
            return

        valid_objects = [
            o for o in target_objects
            if o and o.type == "MESH" and o.data and (
                o.material_slots or (hasattr(o.data, "attributes") and ATTR_SOURCE_TEXTURE_KEY in o.data.attributes)
            )
        ]
        if not valid_objects:
            yield StepResult.failed("No valid mesh objects with materials or source provenance found.")
            return

        # Unified-atlas builder lacks per-face chunk/texture locations and cannot be inverted safely.
        for obj in valid_objects:
            mesh = obj.data
            chunk_attr = mesh.attributes.get(ATTR_ATLAS_CHUNK_ID)
            texture_attr = mesh.attributes.get(ATTR_ATLAS_TEXTURE_ID)
            for poly_idx, poly in enumerate(mesh.polygons):
                if poly.material_index >= len(obj.material_slots):
                    continue
                mat = obj.material_slots[poly.material_index].material
                if detect_material_mode(mat) != "ATLAS_UNIFIED":
                    continue
                has_location = (
                    chunk_attr and texture_attr
                    and poly_idx < len(chunk_attr.data) and poly_idx < len(texture_attr.data)
                    and chunk_attr.data[poly_idx].value >= 0
                    and texture_attr.data[poly_idx].value >= 0
                )
                if not has_location:
                    yield StepResult.failed(
                        "Unified Atlas material lacks per-face provenance and cannot be converted safely. "
                        "Rebuild it as Atlas Chunk material first."
                    )
                    return

        if material_mode == "ATLAS":
            yield from AtlasReplacementEngine.execute(
                pipeline_context, pack, valid_objects, pack_textures,
                biome_preset=biome_preset, pack_stack=pack_stack,
            )
        else:
            yield from StandaloneReplacementEngine.execute(
                pipeline_context, pack, valid_objects, pack_textures,
                biome_preset=biome_preset, pack_stack=pack_stack,
            )
