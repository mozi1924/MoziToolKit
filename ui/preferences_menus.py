"""
Right-click context menu configuration PropertyGroups, UILists, and operators.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from ..utils.config import (
    get_config_manager,
    export_config,
    import_config,
    normalize_operator_id,
)
from ..utils.system import ALL_OPERATORS
from ..utils.system.menu_registry import sort_unadded_items


def _safe_get_prefs(self_or_context=None):
    if hasattr(self_or_context, "resource_packs"):
        return self_or_context
    if isinstance(self_or_context, bpy.types.Context):
        from ..utils.system import get_prefs
        prefs = get_prefs(self_or_context)
        if prefs:
            return prefs
    if hasattr(self_or_context, "id_data") and hasattr(self_or_context.id_data, "resource_packs"):
        return self_or_context.id_data
    from ..utils.system import get_prefs
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


def refresh_ui_and_menus(context=None):
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
    if get_config_manager().is_syncing():
        return
    prefs = _safe_get_prefs(self)
    if prefs:
        get_config_manager().sync_from_preferences(prefs)
        refresh_ui_and_menus(context)


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



class MOZI_OT_menu_add_item(bpy.types.Operator):
    """Add selected item to right-click menu for current view tab"""

    bl_idname = "mozi.menu_add_item"
    bl_label = "Add to Menu"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = _safe_get_prefs(context)
        if prefs is None:
            return {"CANCELLED"}

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
            get_config_manager().sync_from_preferences(prefs)
            refresh_ui_and_menus(context)

        return {"FINISHED"}


class MOZI_OT_menu_remove_item(bpy.types.Operator):
    """Remove selected item from right-click menu for current view tab"""

    bl_idname = "mozi.menu_remove_item"
    bl_label = "Remove from Menu"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = _safe_get_prefs(context)
        if prefs is None:
            return {"CANCELLED"}

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
            get_config_manager().sync_from_preferences(prefs)
            refresh_ui_and_menus(context)

        return {"FINISHED"}


class MOZI_OT_menu_move_item(bpy.types.Operator):
    """Move selected item up or down in right-click menu list"""

    bl_idname = "mozi.menu_move_item"
    bl_label = "Move Item"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(items=[("UP", "Up", ""), ("DOWN", "Down", "")])

    def execute(self, context):
        prefs = _safe_get_prefs(context)
        if prefs is None:
            return {"CANCELLED"}

        view = getattr(prefs, "context_menu_tab", getattr(prefs, "active_tab", "mesh"))
        if view not in {"mesh", "object", "uv"}:
            view = "mesh"

        added_coll = getattr(prefs, f"added_{view}")
        added_idx_prop = f"added_{view}_index"
        idx = getattr(prefs, added_idx_prop)

        if self.direction == "UP" and idx > 0:
            added_coll.move(idx, idx - 1)
            setattr(prefs, added_idx_prop, idx - 1)
            get_config_manager().sync_from_preferences(prefs)
            refresh_ui_and_menus(context)
        elif self.direction == "DOWN" and idx < len(added_coll) - 1:
            added_coll.move(idx, idx + 1)
            setattr(prefs, added_idx_prop, idx + 1)
            get_config_manager().sync_from_preferences(prefs)
            refresh_ui_and_menus(context)

        return {"FINISHED"}


class MOZI_OT_menu_reset_config(bpy.types.Operator):
    """Reset configuration to default presets"""

    bl_idname = "mozi.menu_reset_config"
    bl_label = "Reset to Default Presets"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        get_config_manager().reset_views()
        prefs = _safe_get_prefs(context)
        if prefs:
            get_config_manager().sync_to_preferences(prefs)
        refresh_ui_and_menus(context)
        self.report({"INFO"}, "Right-click context menu reset to default presets.")
        return {"FINISHED"}


class MOZI_OT_menu_export_config(bpy.types.Operator, ExportHelper):
    """Export MoziToolKit configuration to a JSON file"""

    bl_idname = "mozi.menu_export_config"
    bl_label = "Export Menu Preset JSON"

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        prefs = _safe_get_prefs(context)
        if prefs:
            get_config_manager().sync_from_preferences(prefs)

        if export_config(self.filepath):
            self.report({"INFO"}, f"Configuration exported to {self.filepath}")
            return {"FINISHED"}
        else:
            self.report({"ERROR"}, "Failed to export configuration")
            return {"CANCELLED"}


class MOZI_OT_menu_import_config(bpy.types.Operator, ImportHelper):
    """Import MoziToolKit configuration from a JSON file"""

    bl_idname = "mozi.menu_import_config"
    bl_label = "Import Menu Preset JSON"

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        imported = import_config(self.filepath)
        if imported is not None:
            prefs = _safe_get_prefs(context)
            if prefs:
                get_config_manager().sync_to_preferences(prefs)
            refresh_ui_and_menus(context)
            self.report({"INFO"}, f"Configuration imported from {self.filepath}")
            return {"FINISHED"}
        else:
            self.report({"ERROR"}, "Failed to import configuration JSON")
            return {"CANCELLED"}


MENUS_CLASSES = (
    MOZI_PG_context_menu_item,
    MOZI_PG_available_menu_item,
    MOZI_UL_added_items_list,
    MOZI_UL_unadded_items_list,
    MOZI_OT_menu_add_item,
    MOZI_OT_menu_remove_item,
    MOZI_OT_menu_move_item,
    MOZI_OT_menu_reset_config,
    MOZI_OT_menu_export_config,
    MOZI_OT_menu_import_config,
)
