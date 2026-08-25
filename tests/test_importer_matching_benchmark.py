import sys
import zipfile
import tempfile
from pathlib import Path
import unittest

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

# Bootstrap MoziToolKit package so top-level pipeline/operators/ui imports resolve
from tests._bootstrap import bootstrap_environment  # noqa: E402
bootstrap_environment()

import bpy
from utils.materials.pack.resource_pack import ZipResourcePack
from utils.materials.matching import extract_material_texture_keys, get_importer_adapter
from pipeline.presets import run_preset_pipeline


class TestImporterModelMatching(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from io import BytesIO
        from PIL import Image

        buf = BytesIO()
        Image.new("RGBA", (16, 16), (128, 128, 128, 255)).save(buf, format="PNG")
        png_16 = buf.getvalue()

        cls.tmp_jar = tempfile.NamedTemporaryFile(suffix='.jar', delete=False).name
        with zipfile.ZipFile(cls.tmp_jar, 'w') as zf:
            zf.writestr('assets/minecraft/textures/block/stone.png', png_16)
            zf.writestr('assets/minecraft/textures/block/stone_bricks.png', png_16)
            zf.writestr('assets/minecraft/textures/block/grass_block_top.png', png_16)
            zf.writestr('assets/minecraft/textures/block/grass_block_side.png', png_16)
            zf.writestr('assets/minecraft/textures/block/oak_log.png', png_16)
            zf.writestr('assets/minecraft/textures/block/oak_log_top.png', png_16)
            zf.writestr('assets/minecraft/textures/block/oak_planks.png', png_16)
            zf.writestr('assets/minecraft/textures/block/water_still.png', png_16)
            zf.writestr('assets/minecraft/textures/block/short_grass.png', png_16)
            zf.writestr('assets/minecraft/textures/block/poppy.png', png_16)
            zf.writestr('assets/minecraft/textures/block/red_wool.png', png_16)
            zf.writestr('assets/minecraft/textures/block/redstone_dust_line0.png', png_16)
            zf.writestr('assets/minecraft/textures/block/redstone_dust_line1.png', png_16)
            zf.writestr('assets/minecraft/textures/block/redstone_dust_dot.png', png_16)
            zf.writestr('assets/minecraft/textures/block/redstone_dust_overlay.png', png_16)
            zf.writestr('assets/minecraft/textures/block/torch.png', png_16)
            zf.writestr('assets/minecraft/textures/block/redstone_torch_off.png', png_16)
            zf.writestr('assets/minecraft/textures/block/iron_chain.png', png_16)
            zf.writestr('assets/minecraft/textures/block/smooth_stone_slab_side.png', png_16)
            zf.writestr('assets/minecraft/textures/block/acacia_shelf.png', png_16)
            zf.writestr('assets/minecraft/textures/block/oak_shelf.png', png_16)
            zf.writestr('assets/minecraft/textures/entity/chest/normal.png', png_16)
            zf.writestr('assets/minecraft/textures/entity/chest/normal_left.png', png_16)
            zf.writestr('assets/minecraft/textures/entity/chest/normal_right.png', png_16)
            zf.writestr('assets/minecraft/textures/entity/chest/ender.png', png_16)
            zf.writestr('assets/minecraft/textures/entity/chest/trapped.png', png_16)
            zf.writestr('assets/minecraft/textures/entity/chest/copper.png', png_16)
            zf.writestr('assets/minecraft/textures/entity/chest/copper_exposed.png', png_16)
            zf.writestr('assets/minecraft/textures/entity/bed/red.png', png_16)
            zf.writestr('assets/minecraft/textures/entity/bed/white.png', png_16)
            zf.writestr('assets/minecraft/textures/entity/decorated_pot/decorated_pot_base.png', png_16)

        cls.pack = ZipResourcePack(cls.tmp_jar)

    def test_importer_matching_benchmark(self):
        test_materials = [
            # JMC2OBJ
            ('jmc2obj standard block', 'minecraft_block-grass_block_top', 'tex/minecraft/block/grass_block_top.png'),
            ('jmc2obj stone bricks', 'minecraft_block-stone_bricks', 'tex/minecraft/block/stone_bricks.png'),
            ('jmc2obj prefix jmc2obj', 'jmc2obj_block-stone', None),
            ('jmc2obj chest', 'minecraft_entity-chest-normal', 'tex/minecraft/entity/chest/normal.png'),
            ('jmc2obj plain grass', 'grass_block_top', 'tex/minecraft/block/grass_block_top.png'),
            # Mineways standard
            ('mineways grass top tile', 'grass_block_top_y', 'tex/grass_block_top_y.png'),
            ('mineways grass side tile', 'grass_block_side_y', 'tex/grass_block_side_y.png'),
            ('mineways stone bricks', 'Stone_Bricks', 'tex/Stone_Bricks.png'),
            ('mineways oak planks', 'Oak_Planks', 'tex/Oak_Planks.png'),
            ('mineways oak log', 'Oak_Log', 'tex/Oak_Log.png'),
            ('mineways water', 'Stationary_Water', 'tex/Stationary_Water.png'),
            ('mineways red carpet', 'Red_Carpet', 'tex/Red_Carpet.png'),
            ('mineways poppy', 'Poppy', 'tex/Poppy.png'),
            # Mineways chest parts
            ('mineways chest front', 'MWO_chest_front', 'tex/MWO_chest_front.png'),
            ('mineways chest latch', 'MWO_chest_latch', 'tex/MWO_chest_latch.png'),
            ('mineways double chest left', 'MWO_double_chest_front_left', 'tex/MWO_double_chest_front_left.png'),
            ('mineways double chest right', 'MWO_double_chest_front_right', 'tex/MWO_double_chest_front_right.png'),
            ('mineways ender chest latch', 'MWO_ender_chest_latch', 'tex/MWO_ender_chest_latch.png'),
            ('mineways ender chest top', 'MWO_ender_chest_top', 'tex/MWO_ender_chest_top.png'),
            ('mineways ender chest front', 'MWO_ender_chest_front', 'tex/MWO_ender_chest_front.png'),
            ('mineways trapped chest top', 'MWO_trapped_chest_top', 'tex/MWO_trapped_chest_top.png'),
            ('mineways copper chest front', 'MWO_copper_chest_front', 'tex/MWO_copper_chest_front.png'),
            ('mineways exposed copper chest', 'MWO_exposed_copper_chest_top', 'tex/MWO_exposed_copper_chest_top.png'),
            # Mineways redstone dust variations
            ('mineways redstone dust line0 off', 'MWO_redstone_dust_line0_off', 'tex/MWO_redstone_dust_line0_off.png'),
            ('mineways redstone dust line1 off', 'MWO_redstone_dust_line1_off', 'tex/MWO_redstone_dust_line1_off.png'),
            ('mineways redstone dust dot off', 'MWO_redstone_dust_dot_off', 'tex/MWO_redstone_dust_dot_off.png'),
            ('mineways redstone dust angled', 'MWO_redstone_dust_angled', 'tex/MWO_redstone_dust_angled.png'),
            ('mineways redstone dust three way', 'MWO_redstone_dust_three_way', 'tex/MWO_redstone_dust_three_way.png'),
            ('mineways redstone dust four way off', 'MWO_redstone_dust_four_way_off', 'tex/MWO_redstone_dust_four_way_off.png'),
            # Mineways shelves, beds, torches, chains, slabs, pots
            ('mineways acacia shelf front', 'MWO_acacia_shelf_front', 'tex/MWO_acacia_shelf_front.png'),
            ('mineways oak shelf shelf back', 'MWO_oak_shelf_shelf_back', 'tex/MWO_oak_shelf_shelf_back.png'),
            ('mineways bed feet top', 'MW_bed_feet_top', 'tex/MW_bed_feet_top.png'),
            ('mineways bed head end', 'MW_bed_head_end', 'tex/MW_bed_head_end.png'),
            ('mineways white bed feet side', 'white_bed_feet_side', 'tex/white_bed_feet_side.png'),
            ('mineways torch top', 'MWO_flattened_torch_top', 'tex/MWO_flattened_torch_top.png'),
            ('mineways redstone torch top off', 'MWO_flattened_redstone_torch_top_off', 'tex/MWO_flattened_redstone_torch_top_off.png'),
            ('mineways chain', 'chain', 'tex/chain.png'),
            ('mineways stone slab side', 'stone_slab_side', 'tex/stone_slab_side.png'),
            ('mineways decorated pot base', 'MW_decorated_pot_base1', 'tex/MW_decorated_pot_base1.png'),
        ]

        for label, mat_name, img_path in test_materials:
            mat = bpy.data.materials.new(name=mat_name)
            mat.use_nodes = True
            if img_path:
                node = mat.node_tree.nodes.new('ShaderNodeTexImage')
                img = bpy.data.images.new(name=img_path.split('/')[-1], width=16, height=16)
                img.filepath = img_path
                node.image = img

            ns, cands = extract_material_texture_keys(mat)
            matched = None
            for cand in cands:
                info = self.pack.get_texture_info(cand, ns)
                if info:
                    matched = (cand, info['texture_key'])
                    break

            self.assertIsNotNone(
                matched,
                f"Failed to match material '{mat_name}' (label: {label}, namespace: {ns}, candidates: {cands})"
            )

    def test_pipeline_cross_mode_replacement_with_importers(self):
        bpy.ops.mesh.primitive_cube_add()
        cube = bpy.context.active_object
        mat1 = bpy.data.materials.new('minecraft_block-grass_block_top')
        mat2 = bpy.data.materials.new('Stone_Bricks')
        cube.data.materials.clear()
        cube.data.materials.append(mat1)
        cube.data.materials.append(mat2)
        cube.data.polygons[0].material_index = 0
        cube.data.polygons[1].material_index = 1

        # 1. Standalone mode replacement
        res, pctx = run_preset_pipeline(
            'replace_material',
            bpy.context,
            params={'zip_path': self.tmp_jar, 'material_mode': 'STANDALONE', 'pack_textures': False, 'use_cache': True},
            target_objects=[cube]
        )
        self.assertTrue(res.is_success, f"Standalone pipeline failed: {res.message} - {pctx.reports}")

        # 2. Atlas mode replacement
        res2, pctx2 = run_preset_pipeline(
            'replace_material',
            bpy.context,
            params={'zip_path': self.tmp_jar, 'material_mode': 'ATLAS', 'pack_textures': False, 'use_cache': True},
            target_objects=[cube]
        )
        self.assertTrue(res2.is_success, f"Atlas pipeline failed: {res2.message} - {pctx2.reports}")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
