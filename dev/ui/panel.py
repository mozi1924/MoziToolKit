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
        from ...i18n import tr
        layout = self.layout

        # 1. Native Engine Status
        status = get_engine_status()
        box = layout.box()
        col = box.column(align=True)

        header = col.row(align=True)
        if status["available"]:
            header.label(text=tr("Engine: ONLINE"), icon="CHECKMARK")
            mode_text = tr("DEV (.so)") if status.get("is_dev") else tr("PROD (Wheel)")
            header.label(text=f"[{mode_text}]")
        else:
            header.label(text=tr("Engine: OFFLINE"), icon="CANCEL")

        col.separator(factor=0.5)
        col.label(text=f"{tr('Version')}: {status.get('version', 'N/A')}")
        path_str = status.get("path", "")
        if path_str:
            short_path = path_str if len(path_str) <= 38 else "..." + path_str[-35:]
            col.label(text=f"{tr('Path')}: {short_path}")

        # 2. Debug Scenarios
        scenarios_box = layout.box()
        scenarios_box.label(text=tr("Debug Scenarios"), icon="SCENE_DATA")

        row = scenarios_box.row(align=True)
        row.scale_y = 1.3
        op = row.operator("mozi.dev_load_debug_world", text=tr("Load Debug World"), icon="WORLD")
        op.enable_ao = True
        op.mesh_fluids = True

        row2 = scenarios_box.row(align=True)
        row2.operator("mozi.dev_mesh_benchmark", text=tr("Mesher Benchmark"), icon="TIME")

        # 3. Execution Profile Breakdown (Most Recent Operation)
        try:
            from ..profile_tracker import get_last_profile
            profile = get_last_profile()
        except Exception:
            profile = None

        prof_box = layout.box()
        prof_header = prof_box.row(align=True)
        prof_header.label(text=tr("Last Operation Profile"), icon="PREVIEW_RANGE")

        if profile:
            op_label = f"{profile['operation']}: {profile['total_ms']} ms"
            prof_header.label(text=f"[{profile['timestamp']}]")

            sub = prof_box.column(align=True)
            sub.label(text=op_label, icon="SORTTIME")
            sub.separator(factor=0.5)

            stages = profile.get("stages", [])
            for idx, stage in enumerate(stages):
                s_row = sub.row(align=True)
                # Stage name
                s_name = stage["name"]
                s_row.label(text=f"{idx+1}. {s_name}")

                # Optional items count
                if stage.get("items_count") is not None:
                    s_row.label(text=f"[{stage['items_count']} items]")
                else:
                    s_row.label(text="")

                # Duration & percentage
                dur_text = f"{stage['duration_ms']:.2f} ms ({stage['percent']}%)"
                s_row.label(text=dur_text)

            prof_box.separator(factor=0.3)
            clear_row = prof_box.row(align=True)
            clear_row.operator("mozi.dev_clear_profile", text=tr("Clear Profile"), icon="PANEL_CLOSE")
        else:
            prof_col = prof_box.column(align=True)
            prof_col.label(text=tr("No operations profiled yet"), icon="INFO")
            prof_col.label(text=tr("Run benchmark or load world to inspect steps"))

        # 4. Material & Asset Cache Status
        cache_box = layout.box()
        cache_box.label(text=tr("Material & Asset Cache"), icon="FILE_CACHE")
        try:
            stats = bridge.get_cache_stats()
            c_col = cache_box.column(align=True)
            files = stats.get('files_count', stats.get('total_files', 0))
            size = stats.get('size_formatted', '0 B')
            c_col.label(text=f"{tr('Files')}: {files} ({size})")
        except Exception:
            cache_box.label(text=tr("Cache unavailable"))

        row_c = cache_box.row(align=True)
        row_c.operator("mozi.precompile_cache", text=tr("Precompile Cache"), icon="FILE_REFRESH")
        row_c.operator("mozi.clear_cache", text=tr("Clear Cache"), icon="TRASH")

        row_f = cache_box.row(align=True)
        row_f.operator("mozi.open_cache_folder", text=tr("Open Cache Folder"), icon="FILE_FOLDER")
