"""
MoziToolKit Operator: Import Minecraft World / Save.

Provides an open-folder file dialog with bounded 3D coordinate inputs in the sidebar.
"""

from __future__ import annotations

import logging
from pathlib import Path

try:
    import bpy
    from bpy.props import BoolProperty, EnumProperty, IntVectorProperty, StringProperty
    from bpy_extras.io_utils import ImportHelper
except ImportError:
    bpy = None
    ImportHelper = object

try:
    from ...bridge.save import import_save_to_blender, inspect_minecraft_save
except (ImportError, ValueError):
    from bridge.save import import_save_to_blender, inspect_minecraft_save

logger = logging.getLogger("MoziToolKit.Operators.Save")


class MTK_OT_import_minecraft_save(bpy.types.Operator, ImportHelper):
    """Import Minecraft Java Edition world save folder (.mca / level.dat) within a bounded 3D selection"""

    bl_idname = "mtk.import_minecraft_save"
    bl_label = "Import Minecraft World"
    bl_options = {"REGISTER", "UNDO"}

    # Directory picker configuration
    directory: StringProperty(
        name="World Folder",
        description="Select the Minecraft world save folder containing level.dat or region files",
        subtype="DIR_PATH",
    ) # type: ignore

    # Filter out non-folders
    filter_folder: BoolProperty(
        default=True,
        options={"HIDDEN"},
    ) # type: ignore

    dimension: EnumProperty(
        name="Dimension",
        description="World dimension to import from",
        items=[
            ("overworld", "Overworld", "Overworld dimension (region/ or dimensions/minecraft/overworld)"),
            ("the_nether", "The Nether", "Nether dimension (DIM-1/ or dimensions/minecraft/the_nether)"),
            ("the_end", "The End", "The End dimension (DIM1/ or dimensions/minecraft/the_end)"),
        ],
        default="overworld",
    ) # type: ignore

    min_coord: IntVectorProperty(
        name="Min Coordinate",
        description="Minimum block coordinate [X, Y, Z] to import",
        size=3,
        default=(-64, -64, -64),
    ) # type: ignore

    max_coord: IntVectorProperty(
        name="Max Coordinate",
        description="Maximum block coordinate [X, Y, Z] to import",
        size=3,
        default=(64, 320, 64),
    ) # type: ignore

    enable_ao: BoolProperty(
        name="Ambient Occlusion",
        description="Calculate smooth 4-corner ambient occlusion lighting",
        default=True,
    ) # type: ignore

    mesh_fluids: BoolProperty(
        name="Mesh Fluids",
        description="Mesh physically accurate top and side fluid surfaces",
        default=True,
    ) # type: ignore

    weld_vertices: BoolProperty(
        name="Weld Vertices",
        description="Weld adjacent shared coplanar vertices into seamless manifold topology",
        default=True,
    ) # type: ignore

    origin_centered: BoolProperty(
        name="Origin Centered",
        description="Center imported world geometry at the scene origin [0, 0, 0]",
        default=True,
    ) # type: ignore

    def draw(self, context):
        layout = self.layout

        # 1. Dimension selection
        box_dim = layout.box()
        box_dim.label(text="Dimension", icon="WORLD")
        box_dim.prop(self, "dimension", text="")

        # 2. 3D Bounding Box selection
        box_coords = layout.box()
        box_coords.label(text="3D Selection Bounds (Blocks)", icon="SNAP_INCREMENT")
        col_coords = box_coords.column(align=True)
        col_coords.prop(self, "min_coord")
        col_coords.prop(self, "max_coord")

        # Range preview
        dx = abs(self.max_coord[0] - self.min_coord[0]) + 1
        dy = abs(self.max_coord[1] - self.min_coord[1]) + 1
        dz = abs(self.max_coord[2] - self.min_coord[2]) + 1
        vol = dx * dy * dz
        box_coords.label(
            text=f"Size: {dx} × {dy} × {dz} ({vol:,} blocks)",
            icon="INFO",
        )

        # 3. Meshing & Shading Options
        box_mesh = layout.box()
        box_mesh.label(text="Meshing & Shaders", icon="MATERIAL")
        box_mesh.prop(self, "enable_ao")
        box_mesh.prop(self, "mesh_fluids")
        box_mesh.prop(self, "weld_vertices")
        box_mesh.prop(self, "origin_centered")

    def execute(self, context):
        target_dir = self.directory or getattr(self, "filepath", "")
        if not target_dir:
            self.report({"ERROR"}, "Please select a valid Minecraft world save folder.")
            return {"CANCELLED"}

        path = Path(target_dir)
        if path.is_file():
            path = path.parent

        if not path.exists():
            self.report({"ERROR"}, f"Folder does not exist: {path}")
            return {"CANCELLED"}

        try:
            from ...utils.system.dependencies import get_prefs
            prefs = get_prefs()
        except Exception:
            prefs = None

        min_c = tuple(self.min_coord)
        max_c = tuple(self.max_coord)

        try:
            obj, stats = import_save_to_blender(
                world_dir=path,
                dimension=self.dimension,
                min_block=min_c,
                max_block=max_c,
                context=context,
                prefs=prefs,
                enable_ao=self.enable_ao,
                mesh_fluids=self.mesh_fluids,
                weld_vertices=self.weld_vertices,
                origin_centered=self.origin_centered,
            )

            self.report(
                {"INFO"},
                f"Imported '{stats['level_name']}' ({self.dimension}): "
                f"{stats['polygon_count']:,} faces, {stats['voxel_count']:,} voxels "
                f"in {stats['elapsed_ms']}ms",
            )
            return {"FINISHED"}
        except Exception as e:
            logger.exception("Failed importing Minecraft world save")
            self.report({"ERROR"}, f"Save import failed: {e}")
            return {"CANCELLED"}


OPERATOR_CLASSES = (
    MTK_OT_import_minecraft_save,
)
