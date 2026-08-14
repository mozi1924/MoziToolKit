"""
Operators for dependency management and preferences navigation.
"""

import bpy
from bpy.props import BoolProperty, StringProperty
from ...utils.dependencies import (
    DEPENDENCIES,
    ensure_sys_paths,
    get_all_dependency_statuses,
    install_package,
)


def get_prefs(context=None):
    if context is None:
        context = bpy.context
    addon_name = __package__.split(".")[0]
    if addon_name in context.preferences.addons:
        return context.preferences.addons[addon_name].preferences
    for name, addon in context.preferences.addons.items():
        if name.endswith("MoziToolKit") or "MoziToolKit" in name:
            return addon.preferences
    return None


def refresh_ui_windows(context=None):
    """Force Blender UI regions to redraw."""
    if context is None:
        context = bpy.context
    try:
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


class MOZI_OT_install_dependency(bpy.types.Operator):
    """Install or update the selected Python dependency via pip into Blender"""

    bl_idname = "mozi.install_dependency"
    bl_label = "Install Dependency"
    bl_options = {"REGISTER", "INTERNAL"}

    package_name: StringProperty(name="Package Name", default="Pillow")
    upgrade: BoolProperty(name="Upgrade", default=False)

    def execute(self, context):
        prefs = get_prefs(context)
        mirror_key = "TSINGHUA"
        custom_url = ""

        if prefs:
            mirror_key = getattr(prefs, "pypi_mirror", "TSINGHUA")
            custom_url = getattr(prefs, "custom_pypi_mirror", "")

        self.report({"INFO"}, f"Installing '{self.package_name}' via pip... Please wait.")

        success, log_output = install_package(
            self.package_name,
            mirror_key=mirror_key,
            custom_url=custom_url,
            upgrade=self.upgrade,
        )

        if prefs:
            prefs.last_install_log = log_output

        refresh_ui_windows(context)

        if success:
            self.report({"INFO"}, f"Successfully installed '{self.package_name}'!")
            return {"FINISHED"}
        else:
            self.report({"ERROR"}, f"Failed to install '{self.package_name}'. Check log in preferences.")
            return {"CANCELLED"}


class MOZI_OT_install_all_dependencies(bpy.types.Operator):
    """Install all missing required dependencies for MoziToolKit"""

    bl_idname = "mozi.install_all_dependencies"
    bl_label = "Install All Missing Dependencies"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        prefs = get_prefs(context)
        mirror_key = "TSINGHUA"
        custom_url = ""

        if prefs:
            mirror_key = getattr(prefs, "pypi_mirror", "TSINGHUA")
            custom_url = getattr(prefs, "custom_pypi_mirror", "")

        all_statuses = get_all_dependency_statuses()
        missing = [s for s in all_statuses if not s["is_satisfied"]]

        if not missing:
            self.report({"INFO"}, "All dependencies are already installed and satisfied.")
            return {"FINISHED"}

        combined_logs = []
        overall_success = True

        for item in missing:
            pkg_name = item["name"]
            self.report({"INFO"}, f"Installing '{pkg_name}'... Please wait.")
            success, log_output = install_package(
                pkg_name,
                mirror_key=mirror_key,
                custom_url=custom_url,
            )
            combined_logs.append(log_output)
            if not success:
                overall_success = False

        if prefs:
            prefs.last_install_log = "\n\n" + ("=" * 50) + "\n\n".join(combined_logs)

        refresh_ui_windows(context)

        if overall_success:
            self.report({"INFO"}, "All dependencies installed successfully!")
            return {"FINISHED"}
        else:
            self.report({"ERROR"}, "Some dependencies failed to install. Check log in preferences.")
            return {"CANCELLED"}


class MOZI_OT_check_dependencies(bpy.types.Operator):
    """Refresh Python dependency detection status"""

    bl_idname = "mozi.check_dependencies"
    bl_label = "Refresh Dependency Status"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        ensure_sys_paths()
        refresh_ui_windows(context)
        self.report({"INFO"}, "Dependency status refreshed.")
        return {"FINISHED"}


class MOZI_OT_open_preferences(bpy.types.Operator):
    """Open Blender Preferences and navigate to MoziToolKit settings"""

    bl_idname = "mozi.open_preferences"
    bl_label = "Open MoziToolKit Preferences"
    bl_options = {"REGISTER", "INTERNAL"}

    tab: StringProperty(name="Tab", default="dependencies")

    def execute(self, context):
        try:
            bpy.ops.screen.userpref_show()
        except Exception:
            pass

        # Switch to Addons/Extensions section
        try:
            if hasattr(context.preferences, "active_section"):
                # Blender 4.2+ uses EXTENSIONS or ADDONS
                if "EXTENSIONS" in bpy.types.Preferences.bl_rna.properties["active_section"].enum_items:
                    context.preferences.active_section = "EXTENSIONS"
                else:
                    context.preferences.active_section = "ADDONS"
        except Exception:
            pass

        prefs = get_prefs(context)
        if prefs and hasattr(prefs, "active_tab"):
            prefs.active_tab = self.tab

        refresh_ui_windows(context)
        return {"FINISHED"}
