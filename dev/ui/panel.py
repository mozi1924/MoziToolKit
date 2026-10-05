"""
MoziToolKit Dev 3D Viewport Sidebar Panel.
Provides quick visual verification, scenario loading, and native engine diagnostics.
"""

import bpy
from ..loader import get_engine_status
from ... import bridge


class VIEW3D_PT_mtk_dev_panel(bpy.types.Panel):
    """Developer sidebar panel for MoziToolKit native core diagnostics and debugging"""

    bl_label = "MTK Dev Tools"
    bl_idname = "VIEW3D_PT_mtk_dev_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MTK Dev"

    def draw(self, context):
        layout = self.layout

        # 1. Native Engine Status
        status = get_engine_status()
        box = layout.box()
        col = box.column(align=True)

        header = col.row(align=True)
        if status["available"]:
            header.label(text="Engine: ONLINE", icon="CHECKMARK")
            mode_text = "DEV (.so)" if status.get("is_dev") else "PROD (Wheel)"
            header.label(text=f"[{mode_text}]")
        else:
            header.label(text="Engine: OFFLINE", icon="CANCEL")

        col.separator(factor=0.5)
        col.label(text=f"Version: {status.get('version', 'N/A')}")
        path_str = status.get("path", "")
        if path_str:
            short_path = path_str if len(path_str) <= 38 else "..." + path_str[-35:]
            col.label(text=f"Path: {short_path}")

        # 2. Debug Scenarios
        scenarios_box = layout.box()
        scenarios_box.label(text="Debug Scenarios", icon="SCENE_DATA")

        row = scenarios_box.row(align=True)
        row.scale_y = 1.3
        op = row.operator("mozi.dev_load_debug_world", text="Load Debug World", icon="WORLD")
        op.enable_ao = True
        op.mesh_fluids = True

        row2 = scenarios_box.row(align=True)
        row2.operator("mozi.dev_mesh_benchmark", text="Mesher Benchmark", icon="TIME")

        # 3. Material & Asset Cache Status
        cache_box = layout.box()
        cache_box.label(text="Material & Asset Cache", icon="FILE_CACHE")
        try:
            stats = bridge.get_cache_stats()
            c_col = cache_box.column(align=True)
            files = stats.get('files_count', stats.get('total_files', 0))
            size = stats.get('size_formatted', '0 B')
            c_col.label(text=f"Files: {files} ({size})")
        except Exception:
            cache_box.label(text="Cache unavailable")

        row_c = cache_box.row(align=True)
        row_c.operator("mozi.precompile_cache", text="Precompile Cache", icon="FILE_REFRESH")
        row_c.operator("mozi.clear_cache", text="Clear Cache", icon="TRASH")

        row_f = cache_box.row(align=True)
        row_f.operator("mozi.open_cache_folder", text="Open Cache Folder", icon="FILE_FOLDER")
