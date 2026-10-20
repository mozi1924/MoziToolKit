"""
Operators for Asset Precompilation, Cache Management, and Environment checks.
"""

import time
from typing import Optional
import bpy
try:
    from ..bridge.assets import (
        precompile_stack,
        precompile_stack_async,
        reload_atlas_images,
    )
    from ..utils.assets import (
        check_asset_cache_status,
        clear_cache,
        get_cache_stats,
        open_cache_folder,
        prepare_asset_context,
    )
    from ..utils.system import get_prefs
    from ..utils.async_task import AsyncTask, ModalTaskRunner
    from ..utils.progress import BlenderProgressReporter, blender_progress_scope
except (ImportError, ValueError):
    from bridge.assets import (
        precompile_stack,
        precompile_stack_async,
        reload_atlas_images,
    )
    from utils.assets import (
        check_asset_cache_status,
        clear_cache,
        get_cache_stats,
        open_cache_folder,
        prepare_asset_context,
    )
    from utils.system import get_prefs
    from utils.async_task import AsyncTask, ModalTaskRunner
    from utils.progress import BlenderProgressReporter, blender_progress_scope


class MOZI_OT_precompile_cache(bpy.types.Operator):
    """Precompile and rebuild the complete Atlas, Standalone, and Model caches via libmtk."""

    bl_idname = "mozi.precompile_cache"
    bl_label = "Precompile Stack Caches"
    bl_options = {"REGISTER"}

    run_async: bpy.props.BoolProperty(
        name="Run Asynchronously",
        description="Run calculation in non-blocking background thread with live status bar progress",
        default=True,
        options={"HIDDEN"},
    )  # type: ignore

    _runner: Optional[ModalTaskRunner] = None

    def invoke(self, context, event):
        return self.execute(context)

    def execute(self, context):
        prefs = get_prefs(context)
        title = "Precompiling Assets"

        status = check_asset_cache_status(prefs)
        if status == "NO_PACKS":
            self.report({'WARNING'}, "No enabled resource packs configured. Please configure a Minecraft pack in Preferences.")
            return {'CANCELLED'}

        # Resolve stack/cache dir/thread count on the main thread; the worker must
        # not read bpy RNA or call get_cache_dir().
        asset_context = prepare_asset_context(prefs)
        raw_threads = getattr(prefs, "thread_count", 0) if prefs is not None else 0
        num_threads = raw_threads if isinstance(raw_threads, int) and not isinstance(raw_threads, bool) and raw_threads > 0 else None

        # Synchronous fallback for CLI / tests when run_async is explicitly False
        if not self.run_async:
            try:
                with blender_progress_scope(context, total=100, title=title) as reporter:
                    res = precompile_stack(
                        prefs,
                        num_threads=num_threads,
                        progress_callback=reporter.on_progress,
                        stack=asset_context["stack"],
                        cache_dir=asset_context["cache_dir"],
                    )

                models_cnt = res.get("models", res.get("baked_models", 0))
                duration = res.get("duration_seconds", 0.0)
                summary_msg = (
                    f"Compiled {res.get('pack_count', 0)} packs: "
                    f"{res.get('atlas_chunks', 0)} atlas chunks, "
                    f"{res.get('standalone_textures', 0)} standalone textures, "
                    f"{models_cnt} models in {duration:.2f}s"
                )
                self.report({'INFO'}, summary_msg)
                return {'FINISHED'}
            except Exception as e:
                self.report({'ERROR'}, f"Failed to precompile asset caches: {e}")
                return {'CANCELLED'}

        # Asynchronous non-blocking modal execution (UI mode)
        task = AsyncTask(
            target=precompile_stack,
            kwargs={
                "prefs": prefs,
                "num_threads": num_threads,
                "stack": asset_context["stack"],
                "cache_dir": asset_context["cache_dir"],
                "reload_images": False,
                "resolve_prefs": False,
            },
        )

        def on_success(res):
            # bpy image reload and stats refresh must happen on the main thread.
            try:
                reload_atlas_images(prefs)
            except Exception:
                pass
            try:
                get_cache_stats(prefs, force_refresh=True)
            except Exception:
                pass
            models_cnt = res.get("models", res.get("baked_models", 0))
            duration = res.get("duration_seconds", 0.0)
            summary_msg = (
                f"Compiled {res.get('pack_count', 0)} packs: "
                f"{res.get('atlas_chunks', 0)} atlas chunks, "
                f"{res.get('standalone_textures', 0)} standalone textures, "
                f"{models_cnt} models in {duration:.2f}s"
            )
            self.report({'INFO'}, summary_msg)

        reporter = BlenderProgressReporter(context=context, total=100, title=title)
        self._runner = ModalTaskRunner(
            operator=self,
            context=context,
            task=task,
            reporter=reporter,
            on_success=on_success,
            title=title,
        )
        return self._runner.start()

    def modal(self, context, event):
        if self._runner is not None:
            return self._runner.modal(event)
        return {'FINISHED'}


class MOZI_OT_clear_cache(bpy.types.Operator):
    """Clear all precompiled MoziToolKit caches."""

    bl_idname = "mozi.clear_cache"
    bl_label = "Clear Precompiled Cache"
    bl_options = {"REGISTER"}

    def execute(self, context):
        prefs = get_prefs(context)
        try:
            cleared_bytes = clear_cache(prefs) or 0
            mb = cleared_bytes / (1024 * 1024)
            self.report({'INFO'}, f"Cleared {mb:.2f} MB of precompiled caches.")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to clear caches: {e}")
            return {'CANCELLED'}


class MOZI_OT_open_cache_folder(bpy.types.Operator):
    """Open the directory containing precompiled caches in the system file manager."""

    bl_idname = "mozi.open_cache_folder"
    bl_label = "Open Cache Folder"
    bl_options = {"REGISTER"}

    def execute(self, context):
        prefs = get_prefs(context)
        try:
            path = open_cache_folder(prefs)
            self.report({'INFO'}, f"Opened cache directory: {path}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to open cache directory: {e}")
            return {'CANCELLED'}


class MOZI_OT_open_url(bpy.types.Operator):
    """Open a URL in the default web browser."""

    bl_idname = "mozi.open_url"
    bl_label = "Open URL"
    bl_description = "Open link in system web browser"

    url: bpy.props.StringProperty(
        name="URL",
        description="URL to open",
        default="https://github.com/mozi1924/MoziToolKit",
    )

    def execute(self, context):
        import webbrowser
        try:
            webbrowser.open(self.url)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Could not open URL: {e}")
            return {'CANCELLED'}


class MOZI_OT_open_preferences(bpy.types.Operator):
    """Open MoziToolKit Add-on Preferences."""

    bl_idname = "mozi.open_preferences"
    bl_label = "Open Preferences"
    bl_options = {"REGISTER"}

    tab: bpy.props.StringProperty(
        name="Tab",
        description="Preferences tab to open",
        default="MISC",
    )

    def execute(self, context):
        try:
            bpy.ops.screen.userpref_show("INVOKE_DEFAULT")
        except Exception:
            pass
        prefs = get_prefs(context)
        if prefs and hasattr(prefs, "active_tab"):
            prefs.active_tab = self.tab
        return {"FINISHED"}


OPERATOR_CLASSES = (
    MOZI_OT_precompile_cache,
    MOZI_OT_clear_cache,
    MOZI_OT_open_cache_folder,
    MOZI_OT_open_url,
    MOZI_OT_open_preferences,
)
OPERATORS_CLASSES = OPERATOR_CLASSES
