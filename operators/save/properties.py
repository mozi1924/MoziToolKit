"""
MoziToolKit Minecraft Save Container Properties.
Defines object-level RNA properties for save selection bounds, dimension,
meshing algorithm options, and dirty-state tracking for in-place re-meshing.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

try:
    import bpy
    from bpy.props import (
        BoolProperty,
        EnumProperty,
        IntVectorProperty,
        PointerProperty,
    )
except ImportError:
    bpy = None
    BoolProperty = object
    EnumProperty = object
    IntVectorProperty = object
    PointerProperty = object

from .utils import resolve_save_container

logger = logging.getLogger("MoziToolKit.Save.Properties")


def _on_save_property_changed(self, context):
    """Marks save properties as dirty when user edits bounds, dimension, or meshing flags."""
    if getattr(self, "suppress_dirty", False):
        return
    try:
        self.is_dirty = True
    except Exception:
        pass


class MoziSaveProperties(bpy.types.PropertyGroup if bpy else object):
    """Object-level properties for Minecraft World Save configuration and re-meshing."""
    __slots__ = ()

    suppress_dirty: BoolProperty(
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )  # type: ignore

    is_initialized: BoolProperty(
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )  # type: ignore

    show_rebuild_settings: BoolProperty(
        name="Show Re-mesh Settings",
        description="Toggle re-mesh and selection settings collapsible section",
        default=False,
    )  # type: ignore

    is_dirty: BoolProperty(
        name="Is Modified",
        description="Whether settings have changed since the last model generation",
        default=False,
    )  # type: ignore

    dimension: EnumProperty(
        name="World Dimension",
        description="World dimension to mesh from",
        items=[
            ("overworld", "Overworld", "Overworld dimension (region/ or dimensions/minecraft/overworld)"),
            ("the_nether", "The Nether", "Nether dimension (dimensions/minecraft/the_nether)"),
            ("the_end", "The End", "The End dimension (dimensions/minecraft/the_end)"),
        ],
        default="overworld",
        update=_on_save_property_changed,
    )  # type: ignore

    min_coord: IntVectorProperty(
        name="Min Coordinate",
        description="Minimum block coordinate [X, Y, Z] of the volume",
        size=3,
        default=(-64, -64, -64),
        update=_on_save_property_changed,
    )  # type: ignore

    max_coord: IntVectorProperty(
        name="Max Coordinate",
        description="Maximum block coordinate [X, Y, Z] of the volume",
        size=3,
        default=(64, 320, 64),
        update=_on_save_property_changed,
    )  # type: ignore

    enable_ao: BoolProperty(
        name="Ambient Occlusion",
        description="Calculate smooth 4-corner ambient occlusion lighting",
        default=True,
        update=_on_save_property_changed,
    )  # type: ignore

    mesh_fluids: BoolProperty(
        name="Mesh Fluids",
        description="Mesh physically accurate fluid surfaces",
        default=True,
        update=_on_save_property_changed,
    )  # type: ignore

    weld_vertices: BoolProperty(
        name="Weld Vertices",
        description="Weld adjacent shared coplanar vertices into seamless manifold topology",
        default=True,
        update=_on_save_property_changed,
    )  # type: ignore

    origin_centered: BoolProperty(
        name="Origin Centered",
        description="Center imported world geometry at the scene origin [0, 0, 0]",
        default=True,
        update=_on_save_property_changed,
    )  # type: ignore

    enable_ctm: BoolProperty(
        name="Connected Textures (CTM)",
        description="Enable OptiFine / Continuity connected textures during world meshing",
        default=True,
        update=_on_save_property_changed,
    )  # type: ignore

    enable_animated_textures: BoolProperty(
        name="Animated Textures",
        description="Enable animated texture frame playback for water, lava, and animated blocks",
        default=True,
        update=_on_save_property_changed,
    )  # type: ignore


def sync_save_properties_from_object(props: Any, obj: Any) -> None:
    """Populates MoziSaveProperties from an object's underlying mtk_* custom properties without marking dirty."""
    if not props or not obj or not hasattr(obj, "get"):
        return

    props.suppress_dirty = True
    try:
        dim = obj.get("mtk_dimension")
        if dim:
            dim_str = str(dim).strip().lower()
            if dim_str in ("overworld", "the_nether", "the_end"):
                props.dimension = dim_str
            elif "nether" in dim_str:
                props.dimension = "the_nether"
            elif "end" in dim_str:
                props.dimension = "the_end"
            else:
                props.dimension = "overworld"

        min_c = obj.get("mtk_min_coord")
        if min_c is not None and len(min_c) == 3:
            props.min_coord = tuple(int(x) for x in min_c)

        max_c = obj.get("mtk_max_coord")
        if max_c is not None and len(max_c) == 3:
            props.max_coord = tuple(int(x) for x in max_c)

        if obj.get("mtk_enable_ao") is not None:
            props.enable_ao = bool(obj.get("mtk_enable_ao"))
        if obj.get("mtk_mesh_fluids") is not None:
            props.mesh_fluids = bool(obj.get("mtk_mesh_fluids"))
        if obj.get("mtk_weld_vertices") is not None:
            props.weld_vertices = bool(obj.get("mtk_weld_vertices"))
        if obj.get("mtk_origin_centered") is not None:
            props.origin_centered = bool(obj.get("mtk_origin_centered"))
        if obj.get("mtk_enable_ctm") is not None:
            props.enable_ctm = bool(obj.get("mtk_enable_ctm"))
        if obj.get("mtk_enable_animated_textures") is not None:
            props.enable_animated_textures = bool(obj.get("mtk_enable_animated_textures"))
    except Exception as exc:
        logger.debug("Failed syncing save properties from object custom properties: %s", exc)
    finally:
        props.suppress_dirty = False
        props.is_dirty = False
        props.is_initialized = True


def sync_save_properties_to_custom_props(props: Any, root_obj: Any, mesh_obj: Optional[Any] = None) -> None:
    """Updates underlying mtk_* custom properties on container root and mesh objects from MoziSaveProperties."""
    if not props:
        return

    targets = [t for t in (root_obj, mesh_obj) if t is not None and hasattr(t, "__setitem__")]
    min_list = list(props.min_coord)
    max_list = list(props.max_coord)
    dim_str = str(props.dimension)

    for target in targets:
        try:
            target["mtk_dimension"] = dim_str
            target["mtk_min_coord"] = min_list
            target["mtk_max_coord"] = max_list
            target["mtk_enable_ao"] = bool(props.enable_ao)
            target["mtk_mesh_fluids"] = bool(props.mesh_fluids)
            target["mtk_weld_vertices"] = bool(props.weld_vertices)
            target["mtk_origin_centered"] = bool(props.origin_centered)
            target["mtk_enable_ctm"] = bool(props.enable_ctm)
            target["mtk_enable_animated_textures"] = bool(props.enable_animated_textures)
        except Exception as exc:
            logger.debug("Failed saving property to object %s: %s", getattr(target, "name", ""), exc)


class _FallbackSaveProperties:
    """Mock-safe pure Python fallback when bpy RNA descriptors are unavailable in test fixtures."""
    def __init__(self):
        self.suppress_dirty = False
        self.is_initialized = False
        self.show_rebuild_settings = False
        self.is_dirty = False
        self.dimension = "overworld"
        self.min_coord = (-64, -64, -64)
        self.max_coord = (64, 320, 64)
        self.enable_ao = True
        self.mesh_fluids = True
        self.weld_vertices = True
        self.origin_centered = True
        self.enable_ctm = True
        self.enable_animated_textures = True


def get_save_properties(obj: Optional[Any], ensure_synced: bool = True) -> Optional[Any]:
    """
    Resolves the canonical MoziSaveProperties instance for a Minecraft Save container object.
    Prefers the root Empty container, seamlessly syncing initial values from mtk_* custom properties.
    """
    if not obj:
        return None

    root_obj, mesh_obj, _ = resolve_save_container(obj)
    target = root_obj or mesh_obj or obj
    if not target:
        return None

    props = getattr(target, "mozi_save", None)
    if props is None and root_obj and hasattr(root_obj, "mozi_save"):
        props = root_obj.mozi_save

    # Support mock objects in test fixtures
    if props is None or not hasattr(props, "dimension"):
        if hasattr(target, "__dict__"):
            try:
                props = _FallbackSaveProperties()
                target.mozi_save = props
            except Exception:
                return None
        else:
            return None

    if props is not None and ensure_synced:
        if hasattr(props, "is_initialized") and not props.is_initialized:
            sync_save_properties_from_object(props, target)

    return props


CLASSES = (
    MoziSaveProperties,
)


def register():
    if not bpy:
        return
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except (ValueError, Exception):
            pass

    if hasattr(bpy.types, "Object"):
        try:
            bpy.types.Object.mozi_save = PointerProperty(type=MoziSaveProperties)
        except (ValueError, Exception):
            pass


def unregister():
    if not bpy:
        return
    if hasattr(bpy.types, "Object") and hasattr(bpy.types.Object, "mozi_save"):
        try:
            del bpy.types.Object.mozi_save
        except Exception:
            pass

    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
