"""
MoziToolKit Dev Operator: Load Embedded Debug World.
"""

import bpy
from ... import bridge


class MOZI_OT_dev_load_debug_world(bpy.types.Operator):
    """Mesh and load canonical embedded Minecraft debug world with models and PBR materials into the active scene"""

    bl_idname = "mozi.dev_load_debug_world"
    bl_label = "Load Debug World"
    bl_description = "Mesh and load canonical embedded Minecraft debug world with models and PBR materials into the active scene"
    bl_options = {"REGISTER", "UNDO"}

    enable_ao: bpy.props.BoolProperty(
        name="Smooth AO",
        description="Calculate 4-corner ambient occlusion lighting",
        default=True,
    )

    mesh_fluids: bpy.props.BoolProperty(
        name="Mesh Fluids",
        description="Include physically accurate fluid surfaces",
        default=True,
    )

    weld_vertices: bpy.props.BoolProperty(
        name="Weld Vertices",
        description="Weld adjacent coplanar vertices into manifold topology",
        default=True,
    )

    origin_centered: bpy.props.BoolProperty(
        name="Center Origin",
        description="Center mesh bounds around world origin (0, 0, 0)",
        default=True,
    )

    def execute(self, context):
        if not bridge.is_debug_world_available():
            self.report({"ERROR"}, "libmtk_py debug world capability is unavailable")
            return {"CANCELLED"}

        try:
            obj, stats = bridge.create_debug_world_object(
                context=context,
                name="MTK_Debug_World",
                enable_ao=self.enable_ao,
                mesh_fluids=self.mesh_fluids,
                weld_vertices=self.weld_vertices,
                origin_centered=self.origin_centered,
            )
            poly_count = stats.get("polygon_count", stats.get("quad_count", 0))
            mat_count = stats.get("materials_count", len(obj.data.materials) if obj and obj.data else 0)
            elapsed_ms = stats.get("meshing_time_ms", stats.get("elapsed_ms", 0.0))

            self.report(
                {"INFO"},
                f"Loaded Debug World: {poly_count:,} faces, {stats['vertex_count']:,} verts, {mat_count} materials in {elapsed_ms:.1f}ms",
            )
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, f"Failed to load debug world: {e}")
            return {"CANCELLED"}
