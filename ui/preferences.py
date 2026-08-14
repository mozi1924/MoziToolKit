import bpy
import site
import sys
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper
from ..utils.menu_config import (
    ALL_OPERATORS,
    export_config,
    import_config,
    load_config,
    normalize_operator_id,
    reset_config,
    save_config,
)
from ..utils.dependencies import (
    DEPENDENCIES,
    ensure_sys_paths,
    get_all_dependency_statuses,
    get_python_executable,
    has_all_dependencies,
)


def get_prefs(context=None):
    if context is None:
        context = bpy.context
    addon_name = __package__.rsplit(".", 1)[0]
    if addon_name in context.preferences.addons:
        return context.preferences.addons[addon_name].preferences
    for name, addon in context.preferences.addons.items():
        if name.endswith("MoziToolKit") or "MoziToolKit" in name:
            return addon.preferences
    return None


def refresh_ui_and_menus(context=None):
    """Force Blender UI regions to redraw so menu modifications take effect immediately."""
    if context is None:
        context = bpy.context
    try:
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


def on_item_label_changed(self, context):
    """Callback when an item's custom label is edited."""
    try:
        prefs = get_prefs(context)
        save_prefs_to_json(prefs)
        refresh_ui_and_menus(context)
    except Exception:
        pass


class MOZI_PG_context_menu_item(bpy.types.PropertyGroup):
    operator_id: StringProperty(name="Operator ID")
    label: StringProperty(
        name="Label",
        description="Custom label shown in right-click menu",
        default="",
        update=on_item_label_changed,
    )
    enabled: BoolProperty(name="Enabled", default=True)


class MOZI_PG_available_menu_item(bpy.types.PropertyGroup):
    operator_id: StringProperty(name="Operator ID")
    label: StringProperty(name="Label", default="")


class MOZI_UL_added_items_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            row.label(text=item.label, icon="CHECKBOX_HLT")
            op_short = item.operator_id.split(".")[-1]
            row.label(text=f"({op_short})", icon="NONE")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=item.label, icon="CHECKBOX_HLT")


class MOZI_UL_unadded_items_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            row.label(text=item.label, icon="ADD")
            op_short = item.operator_id.split(".")[-1]
            row.label(text=f"({op_short})", icon="NONE")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=item.label, icon="ADD")


def sort_unadded_items(unadded_coll):
    """Sort unadded CollectionProperty items by live OPERATOR_ORDER."""
    op_order = list(ALL_OPERATORS.keys())
    items = [
        {"operator_id": elem.operator_id, "label": elem.label}
        for elem in unadded_coll
    ]
    items.sort(
        key=lambda x: op_order.index(x["operator_id"])
        if x["operator_id"] in op_order
        else 999
    )
    unadded_coll.clear()
    for item in items:
        elem = unadded_coll.add()
        elem.operator_id = item["operator_id"]
        elem.label = item["label"]


def sync_prefs_from_json(prefs):
    """Populate preferences PropertyGroups from JSON configuration."""
    config_data = load_config()
    for view in ["mesh", "object", "uv"]:
        added_coll = getattr(prefs, f"added_{view}")
        unadded_coll = getattr(prefs, f"unadded_{view}")

        added_coll.clear()
        unadded_coll.clear()

        added_op_ids = set()
        view_items = config_data.get(view, [])
        for item_data in view_items:
            op_id = normalize_operator_id(item_data.get("operator"))
            if not op_id:
                continue
            added_op_ids.add(op_id)
            elem = added_coll.add()
            elem.operator_id = op_id
            default_label = ALL_OPERATORS.get(op_id, {}).get("default_label", op_id)
            elem.label = item_data.get("label") or default_label
            elem.enabled = item_data.get("enabled", True)

        for op_id, op_info in ALL_OPERATORS.items():
            norm_op_id = normalize_operator_id(op_id)
            if norm_op_id not in added_op_ids:
                elem = unadded_coll.add()
                elem.operator_id = norm_op_id
                elem.label = op_info.get("label", norm_op_id)

        sort_unadded_items(unadded_coll)


def save_prefs_to_json(prefs):
    """Save preferences PropertyGroups state to JSON configuration."""
    views_data = {}
    for view in ["mesh", "object", "uv"]:
        added_coll = getattr(prefs, f"added_{view}")
        items_list = []
        for elem in added_coll:
            items_list.append({
                "operator": normalize_operator_id(elem.operator_id),
                "label": elem.label,
                "enabled": elem.enabled,
            })
        views_data[view] = items_list
    save_config(views_data)


class MOZI_OT_menu_add_item(bpy.types.Operator):
    """Add selected item to right-click menu for current view tab"""

    bl_idname = "mozi.menu_add_item"
    bl_label = "Add to Menu"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = get_prefs(context)
        view = prefs.active_tab

        added_coll = getattr(prefs, f"added_{view}")
        unadded_coll = getattr(prefs, f"unadded_{view}")
        unadded_idx_prop = f"unadded_{view}_index"
        idx = getattr(prefs, unadded_idx_prop)

        if 0 <= idx < len(unadded_coll):
            item_to_add = unadded_coll[idx]
            elem = added_coll.add()
            elem.operator_id = normalize_operator_id(item_to_add.operator_id)
            elem.label = item_to_add.label
            elem.enabled = True
            unadded_coll.remove(idx)
            setattr(prefs, unadded_idx_prop, min(idx, max(0, len(unadded_coll) - 1)))
            setattr(prefs, f"added_{view}_index", len(added_coll) - 1)
            sort_unadded_items(unadded_coll)
            save_prefs_to_json(prefs)
            refresh_ui_and_menus(context)

        return {"FINISHED"}


class MOZI_OT_menu_remove_item(bpy.types.Operator):
    """Remove selected item from right-click menu for current view tab"""

    bl_idname = "mozi.menu_remove_item"
    bl_label = "Remove from Menu"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = get_prefs(context)
        view = prefs.active_tab

        added_coll = getattr(prefs, f"added_{view}")
        unadded_coll = getattr(prefs, f"unadded_{view}")
        added_idx_prop = f"added_{view}_index"
        idx = getattr(prefs, added_idx_prop)

        if 0 <= idx < len(added_coll):
            item_to_remove = added_coll[idx]
            op_id = normalize_operator_id(item_to_remove.operator_id)
            elem = unadded_coll.add()
            elem.operator_id = op_id
            elem.label = ALL_OPERATORS.get(op_id, {}).get("label", op_id)
            added_coll.remove(idx)
            setattr(prefs, added_idx_prop, min(idx, max(0, len(added_coll) - 1)))
            sort_unadded_items(unadded_coll)
            setattr(prefs, f"unadded_{view}_index", 0)
            save_prefs_to_json(prefs)
            refresh_ui_and_menus(context)

        return {"FINISHED"}


class MOZI_OT_menu_move_item(bpy.types.Operator):
    """Move selected item up or down in right-click menu list"""

    bl_idname = "mozi.menu_move_item"
    bl_label = "Move Item"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(items=[("UP", "Up", ""), ("DOWN", "Down", "")])

    def execute(self, context):
        prefs = get_prefs(context)
        view = prefs.active_tab

        added_coll = getattr(prefs, f"added_{view}")
        added_idx_prop = f"added_{view}_index"
        idx = getattr(prefs, added_idx_prop)

        if self.direction == "UP" and idx > 0:
            added_coll.move(idx, idx - 1)
            setattr(prefs, added_idx_prop, idx - 1)
            save_prefs_to_json(prefs)
            refresh_ui_and_menus(context)
        elif self.direction == "DOWN" and idx < len(added_coll) - 1:
            added_coll.move(idx, idx + 1)
            setattr(prefs, added_idx_prop, idx + 1)
            save_prefs_to_json(prefs)
            refresh_ui_and_menus(context)

        return {"FINISHED"}


class MOZI_OT_menu_reset_config(bpy.types.Operator):
    """Reset right-click menu configuration to default presets"""

    bl_idname = "mozi.menu_reset_config"
    bl_label = "Reset to Default Presets"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        reset_config()
        prefs = get_prefs(context)
        sync_prefs_from_json(prefs)
        refresh_ui_and_menus(context)
        self.report({"INFO"}, "Menu configuration reset to default presets.")
        return {"FINISHED"}


class MOZI_OT_menu_export_config(bpy.types.Operator, ExportHelper):
    """Export MoziToolKit context menu configuration to a JSON file"""

    bl_idname = "mozi.menu_export_config"
    bl_label = "Export Menu Preset JSON"

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        prefs = get_prefs(context)
        save_prefs_to_json(prefs)

        views_data = {}
        for view in ["mesh", "object", "uv"]:
            added_coll = getattr(prefs, f"added_{view}")
            views_data[view] = [
                {"operator": normalize_operator_id(elem.operator_id), "label": elem.label, "enabled": elem.enabled}
                for elem in added_coll
            ]

        if export_config(self.filepath, views_data):
            self.report({"INFO"}, f"Configuration exported to {self.filepath}")
            return {"FINISHED"}
        else:
            self.report({"ERROR"}, "Failed to export configuration")
            return {"CANCELLED"}


class MOZI_OT_menu_import_config(bpy.types.Operator, ImportHelper):
    """Import MoziToolKit context menu configuration from a JSON file"""

    bl_idname = "mozi.menu_import_config"
    bl_label = "Import Menu Preset JSON"

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        imported = import_config(self.filepath)
        if imported is not None:
            prefs = get_prefs(context)
            sync_prefs_from_json(prefs)
            refresh_ui_and_menus(context)
            self.report({"INFO"}, f"Configuration imported from {self.filepath}")
            return {"FINISHED"}
        else:
            self.report({"ERROR"}, "Failed to import configuration JSON")
            return {"CANCELLED"}



class MOZI_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__.rsplit(".", 1)[0]

    active_tab: EnumProperty(
        name="View Tab",
        description="Select preferences section to configure",
        items=[
            ("mesh", "Mesh Edit Mode (3D View)", "Mesh Edit Mode Context Menu"),
            ("object", "Object Mode (3D View)", "Object Mode Context Menu"),
            ("uv", "UV Editor", "UV Editor Context Menu"),
            ("dependencies", "Dependencies (依赖管理)", "Manage Python dependencies required by MoziToolKit"),
        ],
        default="mesh",
    )

    pypi_mirror: EnumProperty(
        name="PyPI Mirror",
        description="Select PyPI mirror source for fast and reliable dependency downloads",
        items=[
            ("TSINGHUA", "Tsinghua (清华大学镜像源 - 推荐)", "https://pypi.tuna.tsinghua.edu.cn/simple"),
            ("ALIYUN", "Aliyun (阿里云镜像源)", "https://mirrors.aliyun.com/pypi/simple/"),
            ("TENCENT", "Tencent (腾讯云镜像源)", "https://mirrors.cloud.tencent.com/pypi/simple/"),
            ("USTC", "USTC (中国科技大学镜像源)", "https://pypi.mirrors.ustc.edu.cn/simple/"),
            ("OFFICIAL", "Official (PyPI 官方源)", "https://pypi.org/simple"),
            ("CUSTOM", "Custom (自定义镜像源)", "Use custom index URL"),
        ],
        default="TSINGHUA",
    )
    custom_pypi_mirror: StringProperty(
        name="Custom Mirror URL",
        description="Custom Python Package Index URL",
        default="",
    )
    last_install_log: StringProperty(
        name="Last Install Log",
        description="Console and pip output log from last installation",
        default="",
    )

    added_mesh: CollectionProperty(type=MOZI_PG_context_menu_item)
    added_mesh_index: IntProperty(default=0)
    unadded_mesh: CollectionProperty(type=MOZI_PG_available_menu_item)
    unadded_mesh_index: IntProperty(default=0)

    added_object: CollectionProperty(type=MOZI_PG_context_menu_item)
    added_object_index: IntProperty(default=0)
    unadded_object: CollectionProperty(type=MOZI_PG_available_menu_item)
    unadded_object_index: IntProperty(default=0)

    added_uv: CollectionProperty(type=MOZI_PG_context_menu_item)
    added_uv_index: IntProperty(default=0)
    unadded_uv: CollectionProperty(type=MOZI_PG_available_menu_item)
    unadded_uv_index: IntProperty(default=0)

    is_initialized: BoolProperty(default=False)

    def draw(self, context):
        if not self.is_initialized or (not len(self.added_mesh) and not len(self.unadded_mesh)):
            sync_prefs_from_json(self)
            self.is_initialized = True

        layout = self.layout

        # View Tabs
        tab_row = layout.row(align=True)
        tab_row.prop(self, "active_tab", expand=True)

        layout.separator()

        if self.active_tab == "dependencies":
            self.draw_dependencies(layout, context)
            return

        # Top Bar (Header Actions for Menu tabs)
        top_box = layout.box()
        top_row = top_box.row(align=True)
        top_row.operator(MOZI_OT_menu_reset_config.bl_idname, text="Reset Default Presets", icon="FILE_REFRESH")
        top_row.operator(MOZI_OT_menu_import_config.bl_idname, text="Import Presets JSON...", icon="IMPORT")
        top_row.operator(MOZI_OT_menu_export_config.bl_idname, text="Export Presets JSON...", icon="EXPORT")

        layout.separator()

        view = self.active_tab
        added_coll_name = f"added_{view}"
        added_idx_name = f"added_{view}_index"
        unadded_coll_name = f"unadded_{view}"
        unadded_idx_name = f"unadded_{view}_index"

        added_coll = getattr(self, added_coll_name)
        added_idx = getattr(self, added_idx_name)
        unadded_coll = getattr(self, unadded_coll_name)
        unadded_idx = getattr(self, unadded_idx_name)

        # Main Two-Column Structure
        main_row = layout.row(align=False)

        # Left Column: Added Right-Click Menu Items
        left_col = main_row.column(align=False)
        left_box = left_col.box()
        left_box.label(text="Added Right-Click Menu Items (已添加右键菜单选项):", icon="CHECKBOX_HLT")
        left_box.template_list(
            "MOZI_UL_added_items_list",
            "",
            self,
            added_coll_name,
            self,
            added_idx_name,
            rows=6,
        )

        # Custom Description Input Box under left column
        if 0 <= added_idx < len(added_coll):
            item = added_coll[added_idx]
            edit_box = left_col.box()
            edit_box.label(text="Edit Menu Item Description (修改右键菜单描述):", icon="EDITMODE_HLT")
            edit_box.prop(item, "label", text="Description")

        # Middle Column: Action Buttons (Icon-Only Compact Column)
        mid_col = main_row.column(align=True)
        mid_col.alignment = "CENTER"
        mid_col.separator(factor=3)

        # Add Button (Left Arrow)
        sub_row1 = mid_col.row(align=True)
        sub_row1.enabled = len(unadded_coll) > 0 and 0 <= unadded_idx < len(unadded_coll)
        sub_row1.operator(MOZI_OT_menu_add_item.bl_idname, text="", icon="BACK")

        # Remove Button (Right Arrow)
        sub_row2 = mid_col.row(align=True)
        sub_row2.enabled = len(added_coll) > 0 and 0 <= added_idx < len(added_coll)
        sub_row2.operator(MOZI_OT_menu_remove_item.bl_idname, text="", icon="FORWARD")

        mid_col.separator(factor=3)

        # Move Up Button
        sub_row3 = mid_col.row(align=True)
        sub_row3.enabled = len(added_coll) > 0 and added_idx > 0
        op_up = sub_row3.operator(MOZI_OT_menu_move_item.bl_idname, text="", icon="TRIA_UP")
        op_up.direction = "UP"

        # Move Down Button
        sub_row4 = mid_col.row(align=True)
        sub_row4.enabled = len(added_coll) > 0 and added_idx < len(added_coll) - 1
        op_down = sub_row4.operator(MOZI_OT_menu_move_item.bl_idname, text="", icon="TRIA_DOWN")
        op_down.direction = "DOWN"

        # Right Column: Available / Unadded Options
        right_col = main_row.column(align=False)
        right_box = right_col.box()
        right_box.label(text="Unadded Available Options (未添加的选项):", icon="ADD")
        right_box.template_list(
            "MOZI_UL_unadded_items_list",
            "",
            self,
            unadded_coll_name,
            self,
            unadded_idx_name,
            rows=6,
        )

    def draw_dependencies(self, layout, context):
        statuses = get_all_dependency_statuses()
        all_ok = has_all_dependencies()

        # Status Summary Banner
        status_box = layout.box()
        banner_row = status_box.row(align=True)
        if all_ok:
            banner_row.label(text="All required Python dependencies are installed and ready to use.", icon="CHECKMARK")
        else:
            banner_row.alert = True
            banner_row.label(text="Some dependencies are missing. Click 'Install' below to enable all features.", icon="ERROR")

        layout.separator()

        # Dependencies List Box
        list_box = layout.box()
        header_row = list_box.row()
        header_row.label(text="Required Python Packages (所需 Python 依赖库):", icon="PACKAGE")

        col = list_box.column(align=False)
        for item in statuses:
            dep_box = col.box()
            row = dep_box.row(align=False)

            # Left Info Column
            info_col = row.column(align=False)
            title_row = info_col.row(align=True)
            title_row.label(text=item["display_name"], icon="SCRIPT")
            if item["installed"]:
                title_row.label(text=f"(v{item['version'] or 'unknown'})", icon="NONE")
            else:
                title_row.label(text="(Not Installed / 未安装)", icon="NONE")

            desc_row = info_col.row(align=True)
            desc_row.scale_y = 0.85
            desc_row.label(text=item["description"] or "")

            if item["required_by"]:
                req_row = info_col.row(align=True)
                req_row.scale_y = 0.85
                req_row.label(text=f"Used by: {item['required_by']}")

            # Right Action Column
            action_col = row.column(align=True)
            action_col.alignment = "RIGHT"
            if item["installed"]:
                tag_row = action_col.row(align=True)
                tag_row.label(text="Installed (已就绪)", icon="CHECKMARK")
                btn = action_col.operator("mozi.install_dependency", text="Update / Reinstall", icon="FILE_REFRESH")
                btn.package_name = item["name"]
                btn.upgrade = True
            else:
                tag_row = action_col.row(align=True)
                tag_row.alert = True
                tag_row.label(text="Missing (未安装)", icon="CANCEL")
                btn = action_col.operator("mozi.install_dependency", text="Install Package", icon="IMPORT")
                btn.package_name = item["name"]
                btn.upgrade = False

        layout.separator()

        # Global Actions Row
        act_row = layout.row(align=True)
        act_row.scale_y = 1.2
        act_row.operator("mozi.install_all_dependencies", text="Install All Missing Dependencies", icon="IMPORT")
        act_row.operator("mozi.check_dependencies", text="Refresh Status", icon="FILE_REFRESH")

        layout.separator()

        # Download & Mirror Settings Box
        mirror_box = layout.box()
        mirror_box.label(text="Download & Mirror Configuration (下载源配置):", icon="INTERNET")
        mirror_box.prop(self, "pypi_mirror", text="PyPI Mirror")
        if self.pypi_mirror == "CUSTOM":
            mirror_box.prop(self, "custom_pypi_mirror", text="Custom URL")

        layout.separator()

        # Python Environment Info Box
        env_box = layout.box()
        env_box.label(text="Python Environment Details (Python 环境信息):", icon="INFO")
        env_col = env_box.column(align=True)
        env_col.scale_y = 0.85
        env_col.label(text=f"Python Executable: {get_python_executable()}")
        env_col.label(text=f"Python Version: {sys.version.split()[0]}")
        try:
            user_site = site.getusersitepackages()
            env_col.label(text=f"User Site-Packages: {user_site}")
        except Exception:
            pass

        # Installation Output Log Box
        if self.last_install_log:
            layout.separator()
            log_box = layout.box()
            log_box.label(text="Last Installation Output Log (最新安装日志):", icon="TEXT")
            log_col = log_box.column(align=True)
            log_col.scale_y = 0.8
            lines = self.last_install_log.strip().splitlines()
            for line in lines[-15:]:
                log_col.label(text=line)
