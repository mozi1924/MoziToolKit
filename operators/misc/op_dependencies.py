"""
Operators for environment status checks, cache cleanup, and preferences navigation.
"""

import bpy
from bpy.props import StringProperty
from ...utils.system import get_prefs


def refresh_ui_windows(context=None):
    """Force Blender UI regions to redraw."""
    if context is None:
        context = bpy.context
    try:
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


class MOZI_OT_check_dependencies(bpy.types.Operator):
    """Refresh Python dependency detection status"""

    bl_idname = "mozi.check_dependencies"
    bl_label = "Refresh Dependency Status"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        from ...utils.system import get_all_dependency_statuses
        from ...utils.materials import get_cache_stats
        get_all_dependency_statuses(force_refresh=True)
        get_cache_stats(force_refresh=True)
        refresh_ui_windows(context)
        self.report({"INFO"}, "Environment and dependency status refreshed.")
        return {"FINISHED"}


class MOZI_OT_open_preferences(bpy.types.Operator):
    """Open Blender Preferences and navigate to MoziToolKit settings"""

    bl_idname = "mozi.open_preferences"
    bl_label = "Open MoziToolKit Preferences"
    bl_options = {"REGISTER", "INTERNAL"}

    tab: StringProperty(name="Tab", default="MISC")

    def execute(self, context):
        try:
            bpy.ops.screen.userpref_show()
        except Exception:
            pass

        # Switch to Addons/Extensions section
        try:
            if hasattr(context.preferences, "active_section"):
                # Blender 4.2+ uses EXTENSIONS or ADDONS
                if "EXTENSIONS" in bpy.types.Preferences.bl_rna.properties["active_section"].enum_items:
                    context.preferences.active_section = "EXTENSIONS"
                else:
                    context.preferences.active_section = "ADDONS"
        except Exception:
            pass

        prefs = get_prefs(context)
        if prefs:
            if self.tab in {"dependencies", "MISC", "misc", "environment"}:
                if hasattr(prefs, "category_tab"):
                    prefs.category_tab = "MISC"
            elif self.tab in {"mesh", "object", "uv"}:
                if hasattr(prefs, "category_tab"):
                    prefs.category_tab = "CONTEXT_MENU"
                if hasattr(prefs, "context_menu_tab"):
                    prefs.context_menu_tab = self.tab

        refresh_ui_windows(context)
        return {"FINISHED"}


class MOZI_OT_clear_cache(bpy.types.Operator):
    """Clear temporary extracted resource pack files and atlas caches"""

    bl_idname = "mozi.clear_cache"
    bl_label = "Clear Resource Pack Cache"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        from ...utils.materials import clear_resource_pack_cache, get_cache_stats
        count, bytes_freed = clear_resource_pack_cache()
        get_cache_stats(force_refresh=True)
        mb_freed = bytes_freed / (1024 * 1024)
        self.report({"INFO"}, f"Cache cleared: removed {count} files ({mb_freed:.2f} MB freed).")
        return {"FINISHED"}


class MOZI_OT_open_cache_folder(bpy.types.Operator):
    """Open the persistent cache directory in system file manager."""

    bl_idname = "mozi.open_cache_folder"
    bl_label = "Open Cache Folder"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        from ...utils.materials import get_cache_dir
        import subprocess
        import sys
        import os

        cache_dir = get_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(cache_dir)])
            elif sys.platform == "win32":
                os.startfile(str(cache_dir))
            else:
                subprocess.Popen(["xdg-open", str(cache_dir)])
            self.report({'INFO'}, f"Opened cache folder: {cache_dir}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to open cache directory: {e}")
            return {'CANCELLED'}

