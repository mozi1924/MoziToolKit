import sys
import zipfile
import tempfile
from pathlib import Path
import unittest

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from utils.system.dependencies import ensure_wheels_in_sys_path
ensure_wheels_in_sys_path()

import bpy
from utils.materials.resource_pack import ZipResourcePack
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
            zf.writestr('assets/minecraft/textures/entity/chest/normal.png', png_16)

        cls.pack = ZipResourcePack(cls.tmp_jar)

    def test_importer_matching_benchmark(self):
        test_materials = [
            # JMC2OBJ
            ('jmc2obj standard block', 'minecraft_block-grass_block_top', 'tex/minecraft/block/grass_block_top.png'),
            ('jmc2obj stone bricks', 'minecraft_block-stone_bricks', 'tex/minecraft/block/stone_bricks.png'),
            ('jmc2obj prefix jmc2obj', 'jmc2obj_block-stone', None),
            ('jmc2obj chest', 'minecraft_entity-chest-normal', 'tex/minecraft/entity/chest/normal.png'),
            ('jmc2obj plain grass', 'grass_block_top', 'tex/minecraft/block/grass_block_top.png'),
            # Mineways
            ('mineways grass top tile', 'grass_block_top_y', 'tex/grass_block_top_y.png'),
            ('mineways grass side tile', 'grass_block_side_y', 'tex/grass_block_side_y.png'),
            ('mineways stone bricks', 'Stone_Bricks', 'tex/Stone_Bricks.png'),
            ('mineways oak planks', 'Oak_Planks', 'tex/Oak_Planks.png'),
            ('mineways oak log', 'Oak_Log', 'tex/Oak_Log.png'),
            ('mineways water', 'Stationary_Water', 'tex/Stationary_Water.png'),
            ('mineways red carpet', 'Red_Carpet', 'tex/Red_Carpet.png'),
            ('mineways poppy', 'Poppy', 'tex/Poppy.png'),
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
            params={'zip_path': self.tmp_jar, 'material_mode': 'STANDALONE'},
            target_objects=[cube]
        )
        self.assertTrue(res.is_success, f"Standalone pipeline failed: {res.message} - {pctx.reports}")

        # 2. Atlas mode replacement
        res2, pctx2 = run_preset_pipeline(
            'replace_material',
            bpy.context,
            params={'zip_path': self.tmp_jar, 'material_mode': 'ATLAS'},
            target_objects=[cube]
        )
        self.assertTrue(res2.is_success, f"Atlas pipeline failed: {res2.message} - {pctx2.reports}")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
