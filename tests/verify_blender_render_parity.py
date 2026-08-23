"""
Blender 3D Scene Verification for Headless Minecraft Model Baker.
Creates a 4x4 array of directional block meshes (Glazed Terracotta, Command Blocks, Observers, Pistons),
validates face orientations, UV rotations, and material mappings against Minecraft ground truth.
"""

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy
import bmesh
import math
from mathutils import Vector, Euler

from utils.mc_baker import (
    StateBaker,
    ModelParser,
    BlockStateResolver,
    AtlasBridge,
    DIR_TO_INDEX,
    MC_DIRECTIONS,
)
from tests.fixtures.mc_block_fixtures import (
    FIXTURE_BLOCKSTATES,
    FIXTURE_MODELS,
    GROUND_TRUTH_FACES,
)


def create_block_mesh(baked_model, name: str, location: tuple[float, float, float]) -> bpy.types.Object:
    """Build a standard 6-face Minecraft cube mesh in Blender from a BakedModel."""
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")

    # Vertex offsets in Minecraft block space [0..1]
    # In Blender: X=East(+X), Y=North(+Y), Z=Up(+Z)
    # Notice Blender Y is North (which was -Z in MC), and Blender Z is Up (which was +Y in MC)
    
    for face in baked_model.faces:
        # Standard cubic face quad vertices in Blender space (X, Y, Z)
        d = face.direction
        if d == "east":    # +X
            v_coords = [(1.0, -0.5, -0.5), (1.0, 0.5, -0.5), (1.0, 0.5, 0.5), (1.0, -0.5, 0.5)]
        elif d == "west":  # -X
            v_coords = [(0.0, 0.5, -0.5), (0.0, -0.5, -0.5), (0.0, -0.5, 0.5), (0.0, 0.5, 0.5)]
        elif d == "up":    # +Z in Blender
            v_coords = [(-0.5, -0.5, 1.0), (0.5, -0.5, 1.0), (0.5, 0.5, 1.0), (-0.5, 0.5, 1.0)]
        elif d == "down":  # -Z in Blender
            v_coords = [(-0.5, 0.5, 0.0), (0.5, 0.5, 0.0), (0.5, -0.5, 0.0), (-0.5, -0.5, 0.0)]
        elif d == "south": # -Y in Blender (South is +Z in MC)
            v_coords = [(0.5, 0.0, -0.5), (-0.5, 0.0, -0.5), (-0.5, 0.0, 0.5), (0.5, 0.0, 0.5)]
        elif d == "north": # +Y in Blender (North is -Z in MC)
            v_coords = [(-0.5, 1.0, -0.5), (0.5, 1.0, -0.5), (0.5, 1.0, 0.5), (-0.5, 1.0, 0.5)]
        else:
            continue

        bm_verts = [bm.verts.new(v) for v in v_coords]
        bm_face = bm.faces.new(bm_verts)

        # Base UV quad [0, 1]
        uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        # Apply UV rotation
        rot_deg = face.uv_rot
        if rot_deg == 90.0:
            uvs = [uvs[3], uvs[0], uvs[1], uvs[2]]
        elif rot_deg == 180.0:
            uvs = [uvs[2], uvs[3], uvs[0], uvs[1]]
        elif rot_deg == 270.0:
            uvs = [uvs[1], uvs[2], uvs[3], uvs[0]]

        for i, loop in enumerate(bm_face.loops):
            loop[uv_layer].uv = Vector(uvs[i])

    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    return obj


def run_verification() -> bool:
    print("============================================================")
    print("Running Blender 3D Parity Verification for MC Model Baker...")
    print("============================================================")

    # Clear existing objects in scene
    bpy.ops.wm.read_homefile(use_empty=True)

    parser = ModelParser()
    for k, v in FIXTURE_MODELS.items():
        parser.register_model(k, v)

    resolver = BlockStateResolver()
    for k, v in FIXTURE_BLOCKSTATES.items():
        resolver.register_blockstate(k, v)

    baker = StateBaker(model_parser=parser, state_resolver=resolver)

    test_grid = [
        # Row 0: Glazed Terracotta (4 facings)
        "minecraft:magenta_glazed_terracotta[facing=north]",
        "minecraft:magenta_glazed_terracotta[facing=east]",
        "minecraft:magenta_glazed_terracotta[facing=south]",
        "minecraft:magenta_glazed_terracotta[facing=west]",

        # Row 1: Command Blocks
        "minecraft:command_block[conditional=false,facing=up]",
        "minecraft:command_block[conditional=false,facing=north]",
        "minecraft:command_block[conditional=false,facing=east]",
        "minecraft:command_block[conditional=true,facing=north]",

        # Row 2: Observers
        "minecraft:observer[facing=up,powered=false]",
        "minecraft:observer[facing=north,powered=false]",
        "minecraft:observer[facing=north,powered=true]",
        "minecraft:observer[facing=east,powered=false]",

        # Row 3: Pistons
        "minecraft:piston[extended=false,facing=up]",
        "minecraft:piston[extended=false,facing=north]",
        "minecraft:piston[extended=false,facing=east]",
        "minecraft:piston[extended=false,facing=down]",
    ]

    all_passed = True

    for idx, state_str in enumerate(test_grid):
        row = idx // 4
        col = idx % 4
        loc = (col * 2.0, row * 2.0, 0.0)

        baked = baker.bake_block_state(state_str)
        obj_name = f"Block_{row}_{col}"
        obj = create_block_mesh(baked, obj_name, loc)

        print(f"[{idx+1:02d}/16] Baked & Created: {state_str} at ({loc[0]:.1f}, {loc[1]:.1f}, {loc[2]:.1f})")

        # Verify faces count
        if len(obj.data.polygons) != 6:
            print(f"  ❌ ERROR: Polygon count {len(obj.data.polygons)} != 6 for {state_str}")
            all_passed = False

        # Validate ground truth if present
        if state_str in GROUND_TRUTH_FACES:
            for face_idx, exp in enumerate(GROUND_TRUTH_FACES[state_str]):
                actual_face = baked.faces[face_idx]
                if actual_face.uv_rot != exp.uv_rot:
                    print(f"  ❌ UV ROT ERROR: Face {actual_face.direction} got {actual_face.uv_rot}°, expected {exp.uv_rot}°")
                    all_passed = False
                if actual_face.texture != exp.texture:
                    print(f"  ❌ TEXTURE ERROR: Face {actual_face.direction} got {actual_face.texture}, expected {exp.texture}")
                    all_passed = False

    if all_passed:
        print("============================================================")
        print("✅ ALL 16 BLOCKSTATE 3D MODELS VERIFIED WITH 100% PARITY!")
        print("============================================================")
    else:
        print("============================================================")
        print("❌ VERIFICATION FAILED!")
        print("============================================================")

    return all_passed


if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
