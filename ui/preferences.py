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
    load_pack_stack_config,
    save_pack_stack_config,
    save_full_config,
    get_enabled_pack_entries,
    normalize_operator_id,
    reset_config,
    save_config,
    DEPENDENCIES,
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


def _safe_get_prefs(self_or_context=None):
    if isinstance(self_or_context, bpy.types.Context):
        prefs = get_prefs(self_or_context)
        if prefs:
            return prefs
    if hasattr(self_or_context, "id_data") and hasattr(self_or_context.id_data, "resource_packs"):
        return self_or_context.id_data
    prefs = get_prefs(bpy.context)
    if prefs:
        return prefs
    try:
        for addon in bpy.context.preferences.addons.values():
            if hasattr(addon, "preferences") and hasattr(addon.preferences, "resource_packs"):
                return addon.preferences
    except Exception:
        pass
    return None


def on_item_label_changed(self, context):
    """Callback when an item's custom label is edited."""
    prefs = _safe_get_prefs(self)
    if prefs:
        save_prefs_to_json(prefs)
        refresh_ui_and_menus(context)


def on_pack_entry_changed(self, context):
    """Callback when a resource pack entry's attributes change."""
    prefs = _safe_get_prefs(self)
    if prefs:
        save_prefs_to_json(prefs)
        refresh_ui_and_menus(context)


def on_pack_path_changed(self, context):
    """Auto-detect pack name and type when path is changed."""
    try:
        from pathlib import Path
        p = Path(self.path.strip())
        if p.exists() and (not self.name or self.name.startswith("Resource Pack") or self.name == "New Resource Pack"):
            self.name = p.stem.replace("_", " ").replace("-", " ").title()
            if p.suffix.lower() == ".jar":
                low = p.name.lower()
                if "fabric" in low or "forge" in low or "mod" in low:
                    self.pack_type = "MOD_JAR"
                else:
                    self.pack_type = "VANILLA"
            elif p.suffix.lower() == ".zip" or p.is_dir():
                self.pack_type = "RESOURCE_PACK"
    except Exception:
        pass
    prefs = _safe_get_prefs(self)
    if prefs:
        save_prefs_to_json(prefs)
        refresh_ui_and_menus(context)


class MOZI_PG_resource_pack_entry(bpy.types.PropertyGroup):
    name: StringProperty(
        name="Name",
        description="Display name for this pack/JAR",
        default="New Resource Pack",
        update=on_pack_entry_changed,
    )
    path: StringProperty(
        name="Path",
        description="File path to .zip/.jar archive or extracted directory",
        subtype="FILE_PATH",
        default="",
        update=on_pack_path_changed,
    )
    enabled: BoolProperty(
        name="Enabled",
        description="Enable this pack in the fallback resolution stack",
        default=True,
        update=on_pack_entry_changed,
    )
    pack_type: EnumProperty(
        name="Pack Type",
        description="Classification of this asset source",
        items=[
            ("RESOURCE_PACK", "Resource Pack", "Standard ZIP or folder resource pack"),
            ("VANILLA", "Vanilla JAR", "Minecraft vanilla client or server JAR archive"),
            ("MOD_JAR", "Mod JAR", "Mod JAR archive (Fabric/Forge/NeoForge) containing assets"),
        ],
        default="RESOURCE_PACK",
        update=on_pack_entry_changed,
    )


class MOZI_UL_resource_packs_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            row.prop(item, "enabled", text="", emboss=False)

            if item.pack_type == "VANILLA":
                icon_type = "WORLD_DATA"
            elif item.pack_type == "MOD_JAR":
                icon_type = "MODIFIER"
            else:
                icon_type = "PACKAGE"

            from pathlib import Path
            is_valid = bool(item.path and Path(item.path).exists())
            name_text = item.name or (Path(item.path).stem if item.path else "Unnamed Pack")

            if not is_valid and item.path:
                row.label(text=f"{name_text} (Missing File)", icon="ERROR")
            elif not item.path:
                row.label(text=f"{name_text} (No Path)", icon="QUESTION")
            else:
                row.label(text=name_text, icon=icon_type)

            p_badge = row.row(align=True)
            p_badge.alignment = "RIGHT"
            p_badge.enabled = False
            p_badge.label(text=f"Priority #{index + 1}")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=item.name, icon="PACKAGE")


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

    # Sync resource packs stack
    packs_data = load_pack_stack_config()
    prefs.resource_packs.clear()
    for p_item in packs_data:
        if isinstance(p_item, dict):
            p_elem = prefs.resource_packs.add()
            p_elem.name = p_item.get("name", "Resource Pack")
            p_elem.path = p_item.get("path", "")
            p_elem.enabled = p_item.get("enabled", True)
            p_elem.pack_type = p_item.get("pack_type", "RESOURCE_PACK")


def save_prefs_to_json(prefs):
    """Save preferences PropertyGroups state to JSON configuration."""
    if prefs is None:
        return

    views_data = {}
    for view in ["mesh", "object", "uv"]:
        added_coll = getattr(prefs, f"added_{view}", None)
        if added_coll is not None:
            items_list = []
            for elem in added_coll:
                items_list.append({
                    "operator": normalize_operator_id(elem.operator_id),
                    "label": elem.label,
                    "enabled": elem.enabled,
                })
            views_data[view] = items_list

    # Save resource packs stack
    packs_list = []
    if hasattr(prefs, "resource_packs"):
        for p_elem in prefs.resource_packs:
            packs_list.append({
                "name": p_elem.name,
                "path": p_elem.path,
                "enabled": p_elem.enabled,
                "pack_type": p_elem.pack_type,
            })
    save_full_config(views_data=views_data, pack_entries=packs_list)


class MOZI_OT_pack_add(bpy.types.Operator):
    """Add a new resource pack or Minecraft/Mod JAR entry to the fallback stack"""

    bl_idname = "mozi.pack_add"
    bl_label = "Add Pack or JAR"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = get_prefs(context)
        if prefs is None:
            return {"CANCELLED"}
        elem = prefs.resource_packs.add()
        elem.name = f"Resource Pack #{len(prefs.resource_packs)}"
        elem.enabled = True
        elem.pack_type = "RESOURCE_PACK"
        prefs.resource_packs_index = len(prefs.resource_packs) - 1
        save_prefs_to_json(prefs)
        refresh_ui_and_menus(context)
        return {"FINISHED"}


class MOZI_OT_pack_remove(bpy.types.Operator):
    """Remove selected pack from the fallback stack"""

    bl_idname = "mozi.pack_remove"
    bl_label = "Remove Pack or JAR"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = get_prefs(context)
        if prefs is None:
            return {"CANCELLED"}
        idx = prefs.resource_packs_index
        if 0 <= idx < len(prefs.resource_packs):
            prefs.resource_packs.remove(idx)
            prefs.resource_packs_index = max(0, min(idx, len(prefs.resource_packs) - 1))
            save_prefs_to_json(prefs)
            refresh_ui_and_menus(context)
        return {"FINISHED"}


class MOZI_OT_pack_move(bpy.types.Operator):
    """Move selected pack up or down to adjust resolution priority"""

    bl_idname = "mozi.pack_move"
    bl_label = "Move Pack Priority"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        items=[("UP", "Up", "Increase Priority"), ("DOWN", "Down", "Decrease Priority")],
        default="UP",
    )

    def execute(self, context):
        prefs = get_prefs(context)
        if prefs is None:
            return {"CANCELLED"}
        idx = prefs.resource_packs_index
        if self.direction == "UP" and idx > 0:
            prefs.resource_packs.move(idx, idx - 1)
            prefs.resource_packs_index = idx - 1
            save_prefs_to_json(prefs)
            refresh_ui_and_menus(context)
        elif self.direction == "DOWN" and idx < len(prefs.resource_packs) - 1:
            prefs.resource_packs.move(idx, idx + 1)
            prefs.resource_packs_index = idx + 1
            save_prefs_to_json(prefs)
            refresh_ui_and_menus(context)
        return {"FINISHED"}


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



def _detect_addon_idname():
    pkg = __package__ or ""
    if pkg.startswith("bl_ext."):
        parts = pkg.split(".")
        if len(parts) >= 3:
            return ".".join(parts[:3])
    elif "MoziToolKit" in pkg:
        return "MoziToolKit"
    return "MoziToolKit"


class MOZI_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = _detect_addon_idname()

    category_tab: EnumProperty(
        name="Category",
        description="Select preferences category",
        items=[
            ("RESOURCE_PACKS", "Resource Packs & Base JARs", "Manage prioritized resource packs, Minecraft vanilla JARs, and mod JARs for fallback and texture/model baking"),
            ("CONTEXT_MENU", "Context Menu Presets", "Configure right-click context menu options"),
            ("MISC", "Environment & Cache", "Extension environment status, dependencies, and cache settings"),
        ],
        default="RESOURCE_PACKS",
    )

    resource_packs: CollectionProperty(type=MOZI_PG_resource_pack_entry)
    resource_packs_index: IntProperty(default=0)

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
        if not self.is_initialized:
            sync_prefs_from_json(self)
            self.is_initialized = True

        layout = self.layout

        # Primary Category Tabs
        cat_row = layout.row(align=True)
        cat_row.prop(self, "category_tab", expand=True)

        layout.separator()

        if self.category_tab == "RESOURCE_PACKS":
            self.draw_resource_packs(layout, context)
        elif self.category_tab == "CONTEXT_MENU":
            self.draw_context_menus(layout, context)
        elif self.category_tab == "MISC":
            self.draw_misc(layout, context)

    def draw_resource_packs(self, layout, context):
        # Information Banner
        info_box = layout.box()
        banner_row = info_box.row(align=True)
        banner_row.label(text="Resource Pack & Base JAR Stack (Prioritized Resolution):", icon="PACKAGE")
        info_col = info_box.column(align=True)
        info_col.scale_y = 0.85
        info_col.label(text="Packs are checked from top to bottom. Higher entries override lower entries.")
        info_col.label(text="Add custom/PBR packs at top, Mod JARs in middle, and Vanilla Minecraft JAR at bottom as base fallback.")

        layout.separator()

        # Split Layout: UIList + Up/Down/Add/Remove Tools
        list_row = layout.row(align=False)

        # Left List Box
        list_box = list_row.box()
        list_box.template_list(
            "MOZI_UL_resource_packs_list",
            "",
            self,
            "resource_packs",
            self,
            "resource_packs_index",
            rows=6,
        )

        # Right Action Buttons Column
        btn_col = list_row.column(align=True)
        btn_col.operator("mozi.pack_add", text="", icon="ADD")
        btn_col.operator("mozi.pack_remove", text="", icon="REMOVE")
        btn_col.separator(factor=2)
        op_up = btn_col.operator("mozi.pack_move", text="", icon="TRIA_UP")
        op_up.direction = "UP"
        op_down = btn_col.operator("mozi.pack_move", text="", icon="TRIA_DOWN")
        op_down.direction = "DOWN"

        # Selected Pack Detail & Properties Box
        idx = self.resource_packs_index
        if 0 <= idx < len(self.resource_packs):
            item = self.resource_packs[idx]
            detail_box = layout.box()
            d_header = detail_box.row(align=True)
            d_header.label(text=f"Pack Details: {item.name}", icon="PREFERENCES")
            d_header.prop(item, "enabled", text="Enabled")

            d_col = detail_box.column(align=False)
            row1 = d_col.row(align=True)
            row1.prop(item, "name", text="Name")
            row1.prop(item, "pack_type", text="Type")

            row2 = d_col.row(align=True)
            row2.prop(item, "path", text="Path")

            # Path Status and Namespaces Inspection
            from pathlib import Path
            p_val = item.path.strip()
            if not p_val:
                st_row = d_col.row(align=True)
                st_row.alert = True
                st_row.label(text="Path is empty. Please select a .zip, .jar, or assets folder.", icon="INFO")
            elif not Path(p_val).exists():
                st_row = d_col.row(align=True)
                st_row.alert = True
                st_row.label(text=f"File not found: '{p_val}'", icon="ERROR")
            else:
                st_row = d_col.row(align=True)
                st_row.label(text=f"File Valid: {Path(p_val).name}", icon="CHECKMARK")

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
