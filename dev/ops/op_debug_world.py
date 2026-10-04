"""
MoziToolKit Dev Operator: Load Embedded Debug World.
"""

import bpy
from ... import bridge


class MOZI_OT_dev_load_debug_world(bpy.types.Operator):
    """Mesh and load canonical embedded Minecraft debug world into the active scene"""

    bl_idname = "mozi.dev_load_debug_world"
    bl_label = "Load Debug World"
    bl_description = "Mesh and load canonical embedded Minecraft debug world into the active scene"
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

    def execute(self, context):
        if not bridge.is_debug_world_available():
            self.report({"ERROR"}, "libmtk_py debug world capability is unavailable")
            return {"CANCELLED"}

        try:
            import libmtk_py
            config = libmtk_py.MesherConfig(
                enable_ao=self.enable_ao,
                mesh_fluids=self.mesh_fluids,
                origin_centered=True,
                weld_vertices=self.weld_vertices,
                z_up_coordinates=True,
            )
        except Exception:
            config = None

        try:
            obj, stats = bridge.create_debug_world_object(
                context=context,
                name="MTK_Debug_World",
                config=config,
            )
            self.report(
                {"INFO"},
                f"Loaded Debug World: {stats['quad_count']} quads, {stats['vertex_count']} verts in {stats['elapsed_ms']:.1f}ms",
            )
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, f"Failed to load debug world: {e}")
            return {"CANCELLED"}
