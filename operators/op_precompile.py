"""
Operators for Asset Precompilation, Cache Management, and Environment checks.
"""

import bpy
try:
    from ..bridge import clear_cache, open_cache_folder, precompile_stack
    from ..utils.system import get_all_dependency_statuses, get_prefs
except (ImportError, ValueError):
    from bridge import clear_cache, open_cache_folder, precompile_stack
    from utils.system import get_all_dependency_statuses, get_prefs


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
                f"{res['models']} models in {res['duration_seconds']:.2f}s"
            )
            self.report({'INFO'}, summary_msg)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to precompile asset caches: {e}")
            return {'CANCELLED'}


class MOZI_OT_clear_cache(bpy.types.Operator):
    """Clear all precompiled MoziToolKit caches."""

    bl_idname = "mozi.clear_cache"
    bl_label = "Clear Precompiled Cache"
    bl_options = {"REGISTER"}

    def execute(self, context):
        prefs = get_prefs(context)
        try:
            cleared_bytes = clear_cache(prefs)
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


class MOZI_OT_check_dependencies(bpy.types.Operator):
    """Check availability of optional and required dependencies."""

    bl_idname = "mozi.check_dependencies"
    bl_label = "Check Dependencies"
    bl_options = {"REGISTER"}

    def execute(self, context):
        statuses = get_all_dependency_statuses()
        for name, info in statuses.items():
            level = 'INFO' if info.get('installed', False) else 'WARNING'
            self.report({level}, f"{name}: {info.get('status', 'Unknown')}")
        return {'FINISHED'}


OPERATORS_CLASSES = (
    MOZI_OT_precompile_cache,
    MOZI_OT_clear_cache,
    MOZI_OT_open_cache_folder,
    MOZI_OT_open_url,
    MOZI_OT_check_dependencies,
)
