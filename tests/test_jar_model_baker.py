"""
Direct JAR Model Baker Verification Test.
Loads assets directly from real Minecraft Client JAR (/Users/jaxlocke/26.2-Fabric.jar)
and verifies 3D model baking for non-full blocks (stairs, slabs, fences, lanterns, chains, doors)
and directional blocks.
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import bpy
from utils.mc_baker import StateBaker, build_blender_mesh_from_baked_model
from utils.live_sync.template_catalog import (
    ensure_baked_block_template,
    get_or_create_template_collection,
)

JAR_PATH = "/Users/jaxlocke/26.2-Fabric.jar"


class TestJarModelBaker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Path(JAR_PATH).exists():
            raise unittest.SkipTest(f"Client JAR not found at {JAR_PATH}")
        cls.baker = StateBaker(jar_path=JAR_PATH)

    def test_bake_stairs_elements(self):
        """Oak stairs should have 2 distinct elements (base slab + step box)."""
        baked = self.baker.bake_block_state("minecraft:oak_stairs[facing=east,half=bottom,shape=straight]")
        self.assertFalse(baked.is_cube)
        self.assertGreaterEqual(len(baked.elements), 2)

        # Build Blender mesh and check geometry
        mesh = build_blender_mesh_from_baked_model(baked, "Test_Oak_Stairs")
        self.assertGreater(len(mesh.polygons), 6)  # Non-cubic, more than 6 faces
        self.assertIn("UVMap", mesh.uv_layers)
        bpy.data.meshes.remove(mesh)

    def test_bake_slabs(self):
        """Bottom slab vs Top slab vs Double slab."""
        baked_bottom = self.baker.bake_block_state("minecraft:stone_slab[type=bottom]")
        self.assertFalse(baked_bottom.is_cube)
        self.assertEqual(len(baked_bottom.elements), 1)
        # Height of slab from 0 to 8
        elem = baked_bottom.elements[0]
        self.assertEqual(elem.from_pos, (0.0, 0.0, 0.0))
        self.assertEqual(elem.to_pos, (16.0, 8.0, 16.0))

        # Top slab from 8 to 16
        baked_top = self.baker.bake_block_state("minecraft:stone_slab[type=top]")
        elem_top = baked_top.elements[0]
        self.assertEqual(elem_top.from_pos, (0.0, 8.0, 0.0))
        self.assertEqual(elem_top.to_pos, (16.0, 16.0, 16.0))

    def test_bake_multipart_fence(self):
        """Fence evaluates multipart: post + connected side arms."""
        # 1-way connected fence
        baked_2way = self.baker.bake_block_state(
            "minecraft:oak_fence[east=false,north=true,south=true,waterlogged=false,west=false]"
        )
        # Should have post elements + north arm + south arm
        self.assertGreater(len(baked_2way.elements), 1)

        # 4-way cross connected fence
        baked_4way = self.baker.bake_block_state(
            "minecraft:oak_fence[east=true,north=true,south=true,waterlogged=false,west=true]"
        )
        self.assertGreater(len(baked_4way.elements), len(baked_2way.elements))

    def test_bake_lantern_and_chain(self):
        """Lantern and Chain non-full multi-element models."""
        baked_lantern = self.baker.bake_block_state("minecraft:lantern[hanging=false]")
        self.assertFalse(baked_lantern.is_cube)
        self.assertGreater(len(baked_lantern.elements), 0)

        baked_chain = self.baker.bake_block_state("minecraft:iron_chain[axis=y,waterlogged=false]")
        self.assertFalse(baked_chain.is_cube)
        self.assertGreater(len(baked_chain.elements), 0)

    def test_bake_jar_directional_blocks(self):
        """Verify Glazed Terracotta, Command Block, Observer directly from JAR."""
        baked_terra = self.baker.bake_block_state("minecraft:magenta_glazed_terracotta[facing=east]")
        # In vanilla: facing=east has y=270, so UV rotation is 270 deg
        self.assertEqual(baked_terra.faces[2].uv_rot, 270.0)

        baked_observer = self.baker.bake_block_state("minecraft:observer[facing=north,powered=false]")
        self.assertIsNotNone(baked_observer)

    def test_extracted_state_template_uses_actual_stair_mesh_and_uvs(self):
        """Live Sync template generation must retain the JAR model, not use its placeholder stair."""
        state = "minecraft:oak_stairs[facing=east,half=bottom,shape=straight]"
        baked = self.baker.bake_block_state(state)
        template = ensure_baked_block_template(get_or_create_template_collection(), state, baked)

        self.assertIsNotNone(template)
        self.assertEqual(template.get("yefira:model_source"), "minecraft_json")
        self.assertEqual(len(template.data.polygons), sum(len(e.faces) for e in baked.elements))
        self.assertIn("UVMap", template.data.uv_layers)
        self.assertIn("yefira_local_face_id", template.data.attributes)
        self.assertIn("yefira_local_uv", template.data.attributes)


if __name__ == "__main__":
    unittest.main(argv=["dummy"])
