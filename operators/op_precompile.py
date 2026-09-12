"""
Operators for Asset Precompilation, Cache Management, and Environment checks.
"""

import bpy
from ..bridge import clear_cache, open_cache_folder, precompile_stack
from ..utils.system import get_all_dependency_statuses, get_prefs


class MOZI_OT_precompile_cache(bpy.types.Operator):
    """Precompile and rebuild the complete Atlas, Standalone, and Model caches via libmtk."""

    bl_idname = "mozi.precompile_cache"
    bl_label = "Precompile Stack Caches"
    bl_options = {"REGISTER"}

    def execute(self, context):
        prefs = get_prefs(context)
        try:
            self.report({'INFO'}, "Precompiling assets via libmtk (Rust backend)...")
            res = precompile_stack(prefs)
            summary_msg = (
                f"Compiled {res['pack_count']} packs: "
                f"{res['atlas_chunks']} atlas chunks, "
                f"{res['standalone_textures']} standalone textures, "
                f"{res['baked_models']} core models."
            )
            self.report({'INFO'}, summary_msg)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to precompile asset caches: {e}")
            return {'CANCELLED'}


class MOZI_OT_open_cache_folder(bpy.types.Operator):
    """Open persistent asset cache directory in system file explorer."""

    bl_idname = "mozi.open_cache_folder"
    bl_label = "Open Cache Folder"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            open_cache_folder()
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Could not open cache folder: {e}")
            return {'CANCELLED'}


class MOZI_OT_clear_cache(bpy.types.Operator):
    """Clear all precompiled asset caches."""

    bl_idname = "mozi.clear_cache"
    bl_label = "Clear Resource Pack Cache"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            clear_cache()
            self.report({'INFO'}, "Asset cache cleared successfully.")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Could not clear cache: {e}")
            return {'CANCELLED'}


class MOZI_OT_check_dependencies(bpy.types.Operator):
    """Refresh extension environment and dependency status."""

    bl_idname = "mozi.check_dependencies"
    bl_label = "Refresh Environment Status"
    bl_options = {"REGISTER"}

    def execute(self, context):
        get_all_dependency_statuses(force_refresh=True)
        self.report({'INFO'}, "Environment status refreshed.")
        return {'FINISHED'}


class MOZI_OT_open_preferences(bpy.types.Operator):
    """Open MoziToolKit add-on preferences dialog."""

    bl_idname = "mozi.open_preferences"
    bl_label = "Open Preferences"
    bl_options = {"REGISTER"}

    tab: bpy.props.StringProperty(default="MISC")

    def execute(self, context):
        try:
            bpy.ops.screen.userpref_show()
            prefs = get_prefs(context)
            if prefs and hasattr(prefs, "category_tab"):
                prefs.category_tab = self.tab
        except Exception:
            pass
        return {'FINISHED'}


class MOZI_OT_refresh_cache_stats(bpy.types.Operator):
    """Scan and refresh asset cache storage statistics."""

    bl_idname = "mozi.refresh_cache_stats"
    bl_label = "Refresh Cache Stats"
    bl_options = {"REGISTER"}

    def execute(self, context):
        from ..bridge import get_cache_stats
        prefs = get_prefs(context)
        stats = get_cache_stats(prefs, force_refresh=True)
        self.report({'INFO'}, f"Cache stats updated: {stats['size_formatted']} ({stats['files_count']} files)")
        return {'FINISHED'}


OPERATORS_CLASSES = (
    MOZI_OT_precompile_cache,
    MOZI_OT_open_cache_folder,
    MOZI_OT_clear_cache,
    MOZI_OT_refresh_cache_stats,
    MOZI_OT_check_dependencies,
    MOZI_OT_open_preferences,
)

