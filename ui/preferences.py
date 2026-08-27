"""
MoziToolKit Add-on Preferences interface and tab views.
Orchestrates Resource Packs & Base JARs stack, Context Menu presets, and Environment/Storage tabs.
"""

import bpy
import site
import sys
from pathlib import Path
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty

from ..utils.config import (
    get_config_manager,
    load_config,
    load_full_config,
    save_config,
    save_full_config,
    load_pack_stack_config,
    save_pack_stack_config,
    load_material_settings_config,
    save_material_settings_config,
    get_enabled_pack_entries,
    reset_config,
    reset_views_config,
    export_config,
    import_config,
    normalize_operator_id,
)
from ..utils.system import (
    ALL_OPERATORS,
    DEPENDENCIES,
    get_all_dependency_statuses,
    get_blender_site_packages,
    get_python_executable,
    has_all_dependencies,
    get_prefs,
)
from .preferences_packs import (
    MOZI_PG_resource_pack_entry,
    MOZI_UL_resource_packs_list,
    MOZI_OT_pack_add,
    MOZI_OT_pack_remove,
    MOZI_OT_pack_move,
    reorder_resource_packs_by_tier,
    populate_resource_packs,
    on_pack_entry_changed,
    on_pack_type_changed,
    on_pack_path_changed,
    PACKS_CLASSES,
)
from .preferences_menus import (
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
    on_item_label_changed,
    MENUS_CLASSES,
)

__all__ = [
    "refresh_ui_and_menus",
    "_safe_get_prefs",
    "on_backend_type_changed",
    "on_material_setting_changed",
    "on_item_label_changed",
    "reorder_resource_packs_by_tier",
    "populate_resource_packs",
    "sync_prefs_from_json",
    "save_prefs_to_json",
    "MOZI_PG_resource_pack_entry",
    "MOZI_UL_resource_packs_list",
    "MOZI_PG_context_menu_item",
    "MOZI_PG_available_menu_item",
    "MOZI_UL_added_items_list",
    "MOZI_UL_unadded_items_list",
    "MOZI_OT_pack_add",
    "MOZI_OT_pack_remove",
    "MOZI_OT_pack_move",
    "MOZI_OT_menu_add_item",
    "MOZI_OT_menu_remove_item",
    "MOZI_OT_menu_move_item",
    "MOZI_OT_menu_reset_config",
    "MOZI_OT_menu_export_config",
    "MOZI_OT_menu_import_config",
    "MOZI_OT_precompile_cache",
    "MOZI_AddonPreferences",
    "PREFERENCES_CLASSES",
]


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
    """Safely resolve AddonPreferences instance across various caller contexts."""
    if hasattr(self_or_context, "resource_packs"):
        return self_or_context
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


def on_backend_type_changed(self, context):
    """Callback when storage backend type is switched in preferences UI."""
    if get_config_manager().is_syncing():
        return
    prefs = _safe_get_prefs(self)
    if prefs and hasattr(prefs, "backend_type"):
        mgr = get_config_manager()
        mgr.switch_backend_by_name(prefs.backend_type, migrate_data=True)
        mgr.sync_to_preferences(prefs)
        refresh_ui_and_menus(context)


def on_material_setting_changed(self, context):
    """Callback when global material replacement preferences are edited."""
    if get_config_manager().is_syncing():
        return
    prefs = _safe_get_prefs(self)
    if prefs:
        get_config_manager().sync_from_preferences(prefs)
        refresh_ui_and_menus(context)


def sync_prefs_from_json(prefs):
    """Populate preferences PropertyGroups from central ConfigManager."""
    get_config_manager().sync_to_preferences(prefs)


def save_prefs_to_json(prefs):
    """Save preferences PropertyGroups state to central ConfigManager."""
    get_config_manager().sync_from_preferences(prefs)

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
            ("MISC", "Environment & Storage", "Storage backend, extension environment status, dependencies, and cache settings"),
        ],
        default="RESOURCE_PACKS",
    )

    backend_type: EnumProperty(
        name="Storage Backend",
        description="Choose where addon configuration is stored and persisted",
        items=[
            ("JSON", "JSON File Backend", "Persist to independent JSON file with atomic writes, backups, and export/import support (Default)"),
            ("BLENDER_PREFS", "Blender Preferences Backend", "Persist directly into Blender's user preferences file (userpref.blend)"),
        ],
        default="JSON",
        update=on_backend_type_changed,
    )

    resource_packs: CollectionProperty(type=MOZI_PG_resource_pack_entry)
    resource_packs_index: IntProperty(default=0)

    material_mode: EnumProperty(
        name="Material Mode",
        description="Choose how imported materials are structured and generated",
        items=[
            ('ATLAS', "Atlas", "Combine all textures into a single texture atlas material (Default)"),
            ('STANDALONE', "Standalone", "Create individual materials for each texture"),
        ],
        default='ATLAS',
        update=on_material_setting_changed,
    )

    biome_preset: EnumProperty(
        name="Biome Palette",
        description="Choose the Minecraft Biome color palette preset for grass, foliage, and water tinting",
        items=[
            ('PLAINS', "Plains", "Default vanilla plains vibrant colors"),
            ('FOREST', "Forest", "Vibrant forest green foliage and grass"),
            ('BIRCH_FOREST', "Birch Forest", "Bright spring green foliage and grass"),
            ('TAIGA', "Taiga", "Cooler spruce forest tones"),
            ('JUNGLE', "Jungle", "Lush vibrant tropical greens"),
            ('SAVANNA', "Savanna", "Warm dry yellowish greens"),
            ('BADLANDS', "Badlands (Mesa)", "Dry olive/brown foliage and grass"),
            ('SWAMP', "Swamp", "Murky dark swamp greens and water"),
            ('DARK_FOREST', "Dark Forest", "Deep dark canopy greens"),
            ('MANGROVE_SWAMP', "Mangrove Swamp", "Warm olive mangrove colors"),
            ('CHERRY_GROVE', "Cherry Grove", "Pastel spring greens"),
            ('SNOWY_PLAINS', "Snowy Plains", "Muted frost green tones"),
            ('DESERT', "Desert", "Dry desert and savanna vegetation tint"),
            ('WARM_OCEAN', "Warm Ocean", "Bright turquoise water"),
        ],
        default='PLAINS',
        update=on_material_setting_changed,
    )

    pack_textures: BoolProperty(
        name="Pack Textures into Blend File",
        description="Embed imported textures directly into the Blender file. When unchecked and the .blend file is saved, textures will be saved externally to '//textures/block/' in your project directory",
        default=True,
        update=on_material_setting_changed,
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
        if not self.is_initialized:
            mgr = get_config_manager()
            mgr.sync_to_preferences(self)
            b_name = mgr.get_backend().backend_name
            if b_name in {"JSON", "BLENDER_PREFS"}:
                self.backend_type = b_name
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
        idx = self.resource_packs_index
        can_move_up = False
        can_move_down = False
        if 0 <= idx < len(self.resource_packs):
            curr_tier = self.resource_packs[idx].pack_type
            if idx > 0 and self.resource_packs[idx - 1].pack_type == curr_tier:
                can_move_up = True
            if idx < len(self.resource_packs) - 1 and self.resource_packs[idx + 1].pack_type == curr_tier:
                can_move_down = True

        btn_col = list_row.column(align=True)
        btn_col.operator("mozi.pack_add", text="", icon="ADD")
        btn_col.operator("mozi.pack_remove", text="", icon="REMOVE")
        btn_col.separator(factor=2)

        up_col = btn_col.column(align=True)
        up_col.enabled = can_move_up
        op_up = up_col.operator("mozi.pack_move", text="", icon="TRIA_UP")
        op_up.direction = "UP"

        down_col = btn_col.column(align=True)
        down_col.enabled = can_move_down
        op_down = down_col.operator("mozi.pack_move", text="", icon="TRIA_DOWN")
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

        # Material Replacement & Atlas Options Box
        layout.separator()
        mat_box = layout.box()
        m_head = mat_box.row(align=True)
        m_head.label(text="Default Material Replacement Settings:", icon="MATERIAL")

        m_col = mat_box.column(align=False)
        row_mode = m_col.row(align=True)
        row_mode.prop(self, "material_mode", text="Mode")
        row_mode.prop(self, "biome_preset", text="Biome")

        row_opts = m_col.row(align=True)
        row_opts.prop(self, "pack_textures")

        row_precompile = mat_box.row(align=True)
        row_precompile.operator("mozi.precompile_cache", text="Precompile / Rebuild Stack Atlas Cache", icon="FILE_REFRESH")
        row_precompile.operator("mozi.open_cache_folder", text="Open Cache Folder", icon="FOLDER_REDIRECT")

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
        # Configuration Backend Selector Box
        backend_box = layout.box()
        b_header = backend_box.row(align=True)
        b_header.label(text="Configuration Storage Backend:", icon="PREFERENCES")
        backend_row = backend_box.row(align=True)
        backend_row.prop(self, "backend_type", expand=True)

        b_desc = backend_box.column(align=True)
        b_desc.scale_y = 0.85
        if self.backend_type == "JSON":
            mgr = get_config_manager()
            from ..utils.config.backends.json_backend import JsonConfigBackend
            path_str = mgr.get_backend().get_config_path() if isinstance(mgr.get_backend(), JsonConfigBackend) else "context_menus.json"
            b_desc.label(text=f"Active File: {path_str}")
            b_desc.label(text="Changes are atomically written to external JSON file with automatic backup.")
        else:
            b_desc.label(text="Saved directly inside Blender's default user preferences (userpref.blend).")

        layout.separator()

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
        from ..utils.materials import get_cache_stats
        stats = get_cache_stats()

        cache_box = layout.box()
        cache_header = cache_box.row(align=True)
        cache_header.label(text="Persistent Cache & Storage:", icon="DISK_DRIVE")
        cache_header.label(text=f"Total: {stats['size_formatted']} ({stats['files_count']} files)", icon="INFO")

        cache_col = cache_box.column(align=True)
        cache_col.scale_y = 0.85
        cache_col.label(text=f"Location: {stats['path']}")
        cache_col.label(text="Extracted packs, compiled multi-layer atlases, and JSON indices persist here across restarts.")

        cache_row = cache_box.row(align=True)
        cache_row.operator("mozi.open_cache_folder", text="Open Cache Folder", icon="FILE_FOLDER")
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


class MOZI_OT_precompile_cache(bpy.types.Operator):
    """Precompile and rebuild the complete Atlas and Standalone caches for the current Resource Pack Stack."""

    bl_idname = "mozi.precompile_cache"
    bl_label = "Precompile Stack Caches"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            from ..utils.system import has_pillow
            from ..utils.materials.pack import get_configured_pack_stack, get_cache_dir, clean_obsolete_stack_caches
            from ..utils.materials.atlas import AtlasGenerator
            from ..utils.materials.standalone import StandaloneGenerator
        except (ImportError, ValueError):
            from utils.system import has_pillow
            from utils.materials.pack import get_configured_pack_stack, get_cache_dir, clean_obsolete_stack_caches
            from utils.materials.atlas import AtlasGenerator
            from utils.materials.standalone import StandaloneGenerator

        if not has_pillow():
            self.report({'ERROR'}, "Cache precompilation requires 'Pillow' (PIL) module.")
            return {'CANCELLED'}

        stack = get_configured_pack_stack()
        if not stack.packs:
            self.report({'WARNING'}, "No enabled resource packs or JARs found in stack to compile.")
            return {'CANCELLED'}

        try:
            from ..utils.mc_baker import clear_shared_baker_cache
            clear_shared_baker_cache()
            cache_root = get_cache_dir()

            prefs = _safe_get_prefs(context)
            if prefs and hasattr(prefs, "material_mode"):
                material_mode = prefs.material_mode
            else:
                material_mode = load_material_settings_config().get("material_mode", "ATLAS")

            # 1. Always Precompile Atlas Cache (needed for Atlas Mode and Live Sync)
            atlas_dir = cache_root / stack.stack_hash / "full_scene"
            gen_atlas = AtlasGenerator(fallback_stack=stack)
            res_atlas = gen_atlas.build(atlas_dir)
            num_chunks = len(res_atlas.get("chunks", []))
            num_baked = len(res_atlas.get("materials", []))

            # 2. Always Precompile Models Cache (needed for Live Sync zero-latency model dispatch)
            res_models = stack.precompile_models()
            num_models = res_models.get("models_count", 0)

            # 3. Conditionally Precompile Standalone Asset Library (only if STANDALONE mode)
            if material_mode == "STANDALONE":
                standalone_dir = cache_root / stack.stack_hash / "standalone"
                gen_st = StandaloneGenerator(fallback_stack=stack)
                res_st = gen_st.build(standalone_dir)
                num_st = res_st.get("texture_count", 0)
                clean_obsolete_stack_caches(current_stack_hash=stack.stack_hash)
                refresh_ui_and_menus(context)
                self.report(
                    {'INFO'},
                    f"Successfully precompiled caches for pack stack (Atlas: {num_chunks} chunks, {num_baked} materials; Models: {num_models} models; Standalone: {num_st} textures)."
                )
            else:
                clean_obsolete_stack_caches(current_stack_hash=stack.stack_hash)
                refresh_ui_and_menus(context)
                self.report(
                    {'INFO'},
                    f"Successfully precompiled caches for pack stack (Atlas: {num_chunks} chunks, {num_baked} materials; Models: {num_models} models)."
                )
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to precompile stack cache: {e}")
            return {'CANCELLED'}

PREFERENCES_CLASSES = (
    *PACKS_CLASSES,
    *MENUS_CLASSES,
    MOZI_AddonPreferences,
    MOZI_OT_precompile_cache,
)
