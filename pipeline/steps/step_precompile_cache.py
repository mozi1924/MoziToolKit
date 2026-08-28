"""
Precompile Cache Pipeline Step for MoziToolKit.

Drives resource pack stack precompilation (Atlas chunks, Models manifest, Standalone library)
with non-blocking progress streaming and cooperative cancellation.
"""

from __future__ import annotations

from typing import Iterator, Union
import bpy

from ..progress import ProgressUpdate
from ..step import PipelineStep, StepResult
from ...utils.materials.pack import (
    ResourcePackStack,
    get_configured_pack_stack,
    get_cache_stats,
)
from ...utils.materials.pack.resource_pack import clean_obsolete_stack_caches
from ...utils.mc_baker import clear_shared_baker_cache


class StepPrecompileCache(PipelineStep):
    """
    Modular PipelineStep for precompiling Atlas, Models, and Standalone caches.
    Streams fine-grained progress updates to the Modal Pipeline Runner and ProgressBar.
    """

    name = "precompile_cache"
    description = "Precompile Atlas, Models, and Standalone caches for active resource pack stack"

    def execute_iter(self, pipeline_context) -> Iterator[Union[ProgressUpdate, StepResult]]:
        pack_stack = pipeline_context.get_param("pack_stack")
        if not pack_stack:
            pack_stack = get_configured_pack_stack()

        if not pack_stack or not pack_stack.packs:
            yield StepResult.failed("No enabled resource packs or JARs found in stack to precompile.")
            return

        material_mode = pipeline_context.get_param("material_mode", "ATLAS")
        yefira_only = pipeline_context.get_param("yefira_only", False)

        clear_shared_baker_cache()

        yield ProgressUpdate(0.01, 1.0, "Starting stack cache precompilation...")

        if pipeline_context.is_cancelled:
            yield StepResult.cancelled("Precompilation cancelled by user.")
            return

        res_data = {}
        for frac, msg, outputs in pack_stack.precompile_iter(
            material_mode=material_mode,
            yefira_only=yefira_only,
        ):
            if pipeline_context.is_cancelled:
                yield StepResult.cancelled("Precompilation cancelled by user.")
                return

            if outputs:
                res_data.update(outputs)
            yield ProgressUpdate(frac, 1.0, msg)

        clean_obsolete_stack_caches(current_stack_hash=pack_stack.stack_hash)
        stats = get_cache_stats(force_refresh=True)
        res_data["cache_stats"] = stats

        num_chunks = len(res_data.get("atlas", {}).get("chunks", []))
        num_models = res_data.get("models", {}).get("models_count", 0)
        num_st = res_data.get("standalone", {}).get("texture_count", 0)

        if material_mode == "STANDALONE":
            success_msg = (
                f"Successfully precompiled caches for pack stack "
                f"(Atlas: {num_chunks} chunks; Models: {num_models} models; Standalone: {num_st} textures)."
            )
        else:
            success_msg = (
                f"Successfully precompiled caches for pack stack "
                f"(Atlas: {num_chunks} chunks; Models: {num_models} models)."
            )

        yield StepResult.success(
            message=success_msg,
            data=res_data,
        )
