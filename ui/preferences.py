import bpy
import site
import sys
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper
from ..utils.system import (
    ALL_OPERATORS,
    export_config,
    import_config,
    load_config,
    normalize_operator_id,
    reset_config,
    save_config,
    DEPENDENCIES,
    ensure_sys_paths,
    get_all_dependency_statuses,
    get_blender_site_packages,
    get_python_executable,
    has_all_dependencies,
    get_prefs,
)


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
        view = getattr(prefs, "context_menu_tab", getattr(prefs, "active_tab", "mesh"))
        if view not in {"mesh", "object", "uv"}:
            view = "mesh"

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
        view = getattr(prefs, "context_menu_tab", getattr(prefs, "active_tab", "mesh"))
        if view not in {"mesh", "object", "uv"}:
            view = "mesh"

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
        view = getattr(prefs, "context_menu_tab", getattr(prefs, "active_tab", "mesh"))
        if view not in {"mesh", "object", "uv"}:
            view = "mesh"

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

    category_tab: EnumProperty(
        name="Category",
        description="Select preferences category",
        items=[
            ("CONTEXT_MENU", "Context Menu Presets", "Configure right-click context menu options"),
            ("MISC", "Environment & Cache", "Extension environment status, dependencies, and cache settings"),
        ],
        default="CONTEXT_MENU",
    )

    context_menu_tab: EnumProperty(
        name="Context Menu View",
        description="Select view context to configure right-click menu",
        items=[
            ("mesh", "Mesh Edit Mode", "Mesh Edit Mode Context Menu"),
            ("object", "Object Mode", "Object Mode Context Menu"),
            ("uv", "UV Editor", "UV Editor Context Menu"),
        ],
        default="mesh",
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

        # Primary Category Tabs
        cat_row = layout.row(align=True)
        cat_row.prop(self, "category_tab", expand=True)

        layout.separator()

        if self.category_tab == "MISC":
            self.draw_misc(layout, context)
        elif self.category_tab == "CONTEXT_MENU":
            self.draw_context_menus(layout, context)

    def draw_context_menus(self, layout, context):
        # Secondary Context Menu Sub-Tabs
        sub_row = layout.row(align=True)
        sub_row.prop(self, "context_menu_tab", expand=True)

        layout.separator()

        # Top Bar (Header Actions for Menu tabs)
        top_box = layout.box()
        top_row = top_box.row(align=True)
        top_row.operator(MOZI_OT_menu_reset_config.bl_idname, text="Reset Default Presets", icon="FILE_REFRESH")
        top_row.operator(MOZI_OT_menu_import_config.bl_idname, text="Import Presets JSON...", icon="IMPORT")
        top_row.operator(MOZI_OT_menu_export_config.bl_idname, text="Export Presets JSON...", icon="EXPORT")

        layout.separator()

        view = self.context_menu_tab
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
        left_box.label(text="Added Right-Click Menu Items:", icon="CHECKBOX_HLT")
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
            edit_box.label(text="Edit Menu Item Label:", icon="EDITMODE_HLT")
            edit_box.prop(item, "label", text="Label")

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
        right_box.label(text="Available Unadded Options:", icon="ADD")
        right_box.template_list(
            "MOZI_UL_unadded_items_list",
            "",
            self,
            unadded_coll_name,
            self,
            unadded_idx_name,
            rows=6,
        )

    def draw_misc(self, layout, context):
        statuses = get_all_dependency_statuses()
        all_ok = has_all_dependencies()

        # Status Summary Banner
        status_box = layout.box()
        banner_row = status_box.row(align=True)
        if all_ok:
            banner_row.label(text="All required modules and dependencies are available.", icon="CHECKMARK")
        else:
            banner_row.alert = True
            banner_row.label(text="Optional dependency 'Pillow' is not installed (required for Atlas Material Mode).", icon="INFO")

        layout.separator()

        # Dependencies List Box
        list_box = layout.box()
        header_row = list_box.row(align=True)
        header_row.label(text="Extension Dependencies:", icon="PACKAGE")
        header_row.operator("mozi.check_dependencies", text="Refresh Status", icon="FILE_REFRESH")

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
                title_row.label(text="(Not Installed / Missing)", icon="NONE")

            desc_row = info_col.row(align=True)
            desc_row.scale_y = 0.85
            desc_row.label(text=item["description"] or "")

            if item["required_by"]:
                req_row = info_col.row(align=True)
                req_row.scale_y = 0.85
                req_row.label(text=f"Used by: {item['required_by']}")

            # Right Status Tag
            action_col = row.column(align=True)
            action_col.alignment = "RIGHT"
            if item["installed"]:
                tag_row = action_col.row(align=True)
                tag_row.label(text="Ready", icon="CHECKMARK")
            else:
                tag_row = action_col.row(align=True)
                tag_row.label(text="Unavailable", icon="CANCEL")

        layout.separator()

        # Cache & Storage Management
        cache_box = layout.box()
        cache_box.label(text="Resource Pack Cache & Storage:", icon="DISK_DRIVE")
        cache_row = cache_box.row(align=True)
        cache_row.operator("mozi.clear_cache", text="Clear Resource Pack Cache", icon="TRASH")

        layout.separator()

        # Python Environment Info Box
        env_box = layout.box()
        env_box.label(text="Python & Extension Environment:", icon="INFO")
        env_col = env_box.column(align=True)
        env_col.scale_y = 0.85
        env_col.label(text=f"Python Version: {sys.version.split()[0]}")
        env_col.label(text=f"Python Executable: {get_python_executable()}")
        blender_sites = get_blender_site_packages()
        if blender_sites:
            env_col.label(text=f"Package Search Path: {blender_sites[0]}")
            for extra_site in blender_sites[1:]:
                env_col.label(text=f"  + {extra_site}")

