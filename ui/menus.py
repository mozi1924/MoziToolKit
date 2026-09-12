"""
MoziToolKit Context Menu Hooks & Registration.
Appends dynamic MoziToolKit items to Blender's 3D View and UV Editor context menus.
"""

try:
    import bpy
    HAS_BPY = True
except ImportError:
    bpy = None
    HAS_BPY = False

try:
    from ..utils.system.menu_registry import draw_dynamic_menu
except (ImportError, ValueError):
    from utils.system.menu_registry import draw_dynamic_menu




def draw_object_menu_func(self, context):
    draw_dynamic_menu(self.layout, "object")


def draw_mesh_menu_func(self, context):
    draw_dynamic_menu(self.layout, "mesh")


def draw_uv_menu_func(self, context):
    draw_dynamic_menu(self.layout, "uv")


MENU_HOOKS = (
    # 3D Viewport - Object Mode Context & Header Menus
    ("VIEW3D_MT_object_context_menu", draw_object_menu_func),
    ("VIEW3D_MT_object", draw_object_menu_func),
    # 3D Viewport - Edit Mesh Mode Context & Header Menus
    ("VIEW3D_MT_edit_mesh_context_menu", draw_mesh_menu_func),
    ("VIEW3D_MT_edit_mesh", draw_mesh_menu_func),
    # UV Editor Context & Header Menus
    ("IMAGE_MT_uvs_context_menu", draw_uv_menu_func),
    ("IMAGE_MT_uvs", draw_uv_menu_func),
    ("VIEW3D_MT_uvs", draw_uv_menu_func),
)


def register():
    """Register menu hooks into Blender UI."""
    for menu_name, func in MENU_HOOKS:
        menu_cls = getattr(bpy.types, menu_name, None)
        if menu_cls is not None:
            try:
                menu_cls.append(func)
            except Exception:
                pass


def unregister():
    """Unregister menu hooks from Blender UI."""
    for menu_name, func in reversed(MENU_HOOKS):
        menu_cls = getattr(bpy.types, menu_name, None)
        if menu_cls is not None:
            try:
                menu_cls.remove(func)
            except Exception:
                pass
