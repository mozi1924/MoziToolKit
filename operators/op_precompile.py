"""
Operators for Asset Precompilation, Cache Management, and Environment checks.
"""

import time
from typing import Optional
import bpy
try:
    from ..bridge import clear_cache, open_cache_folder, precompile_stack, precompile_stack_async
    from ..utils.system import get_prefs
    from ..utils.async_task import AsyncTask, ModalTaskRunner
    from ..utils.progress import BlenderProgressReporter, blender_progress_scope
except (ImportError, ValueError):
    from bridge import clear_cache, open_cache_folder, precompile_stack, precompile_stack_async
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

        # Synchronous fallback for CLI / tests when run_async is explicitly False
        if not self.run_async:
            try:
                with blender_progress_scope(context, total=100, title=title) as reporter:
                    res = precompile_stack(prefs, progress_callback=reporter.on_progress)

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
            kwargs={"prefs": prefs},
        )

        def on_success(res):
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
