"""
Resource pack preferences PropertyGroup, UIList, tier ordering, and management operators.
"""

import bpy
from pathlib import Path
from bpy.props import BoolProperty, EnumProperty, StringProperty

from ..utils.config import get_config_manager


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

def _get_is_reordering() -> bool:
    return getattr(bpy.types.WindowManager, "_mozi_is_reordering_packs", False)


def _set_is_reordering(val: bool) -> None:
    setattr(bpy.types.WindowManager, "_mozi_is_reordering_packs", val)


def reorder_resource_packs_by_tier(prefs):
    """
    Sorts prefs.resource_packs CollectionProperty into three strict tiers:
    1. RESOURCE_PACK (top)
    2. MOD_JAR (middle)
    3. VANILLA (bottom)
    Preserves existing relative order within each tier using stable in-place moves.
    """
    if _get_is_reordering() or get_config_manager().is_syncing():
        return
    if prefs is None or not hasattr(prefs, "resource_packs") or len(prefs.resource_packs) <= 1:
        return

    def tier_key(item):
        pt = getattr(item, "pack_type", "RESOURCE_PACK")
        if pt == "RESOURCE_PACK":
            return 0
        elif pt == "MOD_JAR":
            return 1
        else:  # VANILLA
            return 2

    _set_is_reordering(True)
    try:
        n = len(prefs.resource_packs)
        for i in range(1, n):
            j = i
            while j > 0 and tier_key(prefs.resource_packs[j]) < tier_key(prefs.resource_packs[j - 1]):
                prefs.resource_packs.move(j, j - 1)
                j -= 1
    finally:
        _set_is_reordering(False)


def on_pack_entry_changed(self, context):
    """Callback when a resource pack entry's attributes change."""
    if _get_is_reordering() or get_config_manager().is_syncing():
        return
    prefs = _safe_get_prefs(self)
    if prefs:
        get_config_manager().sync_from_preferences(prefs)
        refresh_ui_and_menus(context)


def on_pack_type_changed(self, context):
    """Callback when a resource pack entry's pack_type tier changes."""
    if _get_is_reordering() or get_config_manager().is_syncing():
        return
    prefs = _safe_get_prefs(self)
    if prefs:
        reorder_resource_packs_by_tier(prefs)
        get_config_manager().sync_from_preferences(prefs)
        refresh_ui_and_menus(context)


def on_pack_path_changed(self, context):
    """Auto-detect pack name and type when path is changed."""
    if _get_is_reordering() or get_config_manager().is_syncing():
        return
    try:
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
        reorder_resource_packs_by_tier(prefs)
        get_config_manager().sync_from_preferences(prefs)
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
            ("RESOURCE_PACK", "Resource Pack", "Standard ZIP or folder resource pack (Overrides base assets)"),
            ("MOD_JAR", "Mod JAR", "Mod JAR archive (Fabric/Forge/NeoForge) containing assets"),
            ("VANILLA", "Vanilla JAR", "Minecraft vanilla client or server JAR archive (Base foundation)"),
        ],
        default="RESOURCE_PACK",
        update=on_pack_type_changed,
    )


class MOZI_UL_resource_packs_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            row.prop(item, "enabled", text="", emboss=False)

            if item.pack_type == "VANILLA":
                icon_type = "WORLD_DATA"
                tier_badge = "Vanilla Base"
            elif item.pack_type == "MOD_JAR":
                icon_type = "MODIFIER"
                mod_idx = sum(1 for i, elem in enumerate(data.resource_packs) if elem.pack_type == "MOD_JAR" and i <= index)
                tier_badge = f"Mod #{mod_idx}"
            else:
                icon_type = "PACKAGE"
                rp_idx = sum(1 for i, elem in enumerate(data.resource_packs) if elem.pack_type == "RESOURCE_PACK" and i <= index)
                tier_badge = f"RP #{rp_idx}"

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
            p_badge.label(text=tier_badge)
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=item.name, icon="PACKAGE")



def populate_resource_packs(prefs, entries):
    """Safely populate prefs.resource_packs from a list of dicts without reorder race conditions."""
    if prefs is None:
        return
    _set_is_reordering(True)
    try:
        setattr(prefs, "_mozi_is_syncing", True)
        prefs.resource_packs.clear()
        for p_item in entries:
            if isinstance(p_item, dict):
                p_elem = prefs.resource_packs.add()
                p_elem.name = p_item.get("name", "Resource Pack")
                p_elem.path = p_item.get("path", "")
                p_elem.enabled = p_item.get("enabled", True)
                p_elem.pack_type = p_item.get("pack_type", "RESOURCE_PACK")
    finally:
        setattr(prefs, "_mozi_is_syncing", False)
        _set_is_reordering(False)

    reorder_resource_packs_by_tier(prefs)


class MOZI_OT_pack_add(bpy.types.Operator):
    """Add a new resource pack or Minecraft/Mod JAR entry to the fallback stack"""

    bl_idname = "mozi.pack_add"
    bl_label = "Add Pack or JAR"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = _safe_get_prefs(context)
        if prefs is None:
            return {"CANCELLED"}
        if not getattr(prefs, "is_initialized", False):
            get_config_manager().sync_to_preferences(prefs)

        elem = prefs.resource_packs.add()
        elem.name = f"Resource Pack #{len(prefs.resource_packs)}"
        elem.enabled = True
        elem.pack_type = "RESOURCE_PACK"
        reorder_resource_packs_by_tier(prefs)

        for i, p in enumerate(prefs.resource_packs):
            if p.name == elem.name and not p.path:
                prefs.resource_packs_index = i
                break

        get_config_manager().sync_from_preferences(prefs)
        refresh_ui_and_menus(context)
        return {"FINISHED"}


class MOZI_OT_pack_remove(bpy.types.Operator):
    """Remove selected pack from the fallback stack"""

    bl_idname = "mozi.pack_remove"
    bl_label = "Remove Pack or JAR"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = _safe_get_prefs(context)
        if prefs is None:
            return {"CANCELLED"}
        idx = prefs.resource_packs_index
        if 0 <= idx < len(prefs.resource_packs):
            prefs.resource_packs.remove(idx)
            reorder_resource_packs_by_tier(prefs)
            prefs.resource_packs_index = max(0, min(idx, len(prefs.resource_packs) - 1))
            get_config_manager().sync_from_preferences(prefs)
            refresh_ui_and_menus(context)
        return {"FINISHED"}


class MOZI_OT_pack_move(bpy.types.Operator):
    """Move selected pack up or down to adjust resolution priority within its tier"""

    bl_idname = "mozi.pack_move"
    bl_label = "Move Pack Priority"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        items=[("UP", "Up", "Increase Priority"), ("DOWN", "Down", "Decrease Priority")],
        default="UP",
    )

    def execute(self, context):
        prefs = _safe_get_prefs(context)
        if prefs is None:
            return {"CANCELLED"}
        idx = prefs.resource_packs_index
        if not (0 <= idx < len(prefs.resource_packs)):
            return {"CANCELLED"}

        curr_item = prefs.resource_packs[idx]
        curr_tier = curr_item.pack_type

        if self.direction == "UP" and idx > 0:
            target_item = prefs.resource_packs[idx - 1]
            if target_item.pack_type != curr_tier:
                self.report({'INFO'}, f"Cannot move {curr_tier.replace('_', ' ').title()} above {target_item.pack_type.replace('_', ' ').title()} tier.")
                return {"CANCELLED"}
            prefs.resource_packs.move(idx, idx - 1)
            prefs.resource_packs_index = idx - 1
            get_config_manager().sync_from_preferences(prefs)
            refresh_ui_and_menus(context)
        elif self.direction == "DOWN" and idx < len(prefs.resource_packs) - 1:
            target_item = prefs.resource_packs[idx + 1]
            if target_item.pack_type != curr_tier:
                self.report({'INFO'}, f"Cannot move {curr_tier.replace('_', ' ').title()} below {target_item.pack_type.replace('_', ' ').title()} tier.")
                return {"CANCELLED"}
            prefs.resource_packs.move(idx, idx + 1)
            prefs.resource_packs_index = idx + 1
            get_config_manager().sync_from_preferences(prefs)
            refresh_ui_and_menus(context)
        return {"FINISHED"}


PACKS_CLASSES = (
    MOZI_PG_resource_pack_entry,
    MOZI_UL_resource_packs_list,
    MOZI_OT_pack_add,
    MOZI_OT_pack_remove,
    MOZI_OT_pack_move,
)
