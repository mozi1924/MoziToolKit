"""
Unit tests verifying that:
1. Overlay texture is never the active/selected image node in Blender (Albedo is always active).
2. Materials do not have fake user protection (mat.use_fake_user is False).
"""

import json
import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Extract bundled Pillow wheel if needed
wheels_dir = PROJECT_DIR / "wheels"
if wheels_dir.exists():
    unpack_dir = Path(tempfile.gettempdir()) / "mozitoolkit_test_wheels"
    unpack_dir.mkdir(parents=True, exist_ok=True)
    if str(unpack_dir) not in sys.path:
        sys.path.insert(0, str(unpack_dir))
    if not (unpack_dir / "PIL").exists():
        import zipfile
        for whl in wheels_dir.glob("pillow*.whl"):
            with zipfile.ZipFile(whl, 'r') as z:
                z.extractall(unpack_dir)

from PIL import Image
import PIL.PngImagePlugin
Image.init()

import bpy

from utils.materials.nodes.builder import rebuild_material, repair_material_nodes
from utils.materials.atlas.builder import build_atlas_chunk_materials, build_atlas_material
from utils.materials.yefira.atlas_integration import get_or_create_atlas_material


class TestOverlaySolidModeAndFakeUser(unittest.TestCase):
    """Test suite ensuring Albedo priority in Solid Mode and absence of fake users on materials."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="mtk_test_solid_overlay_"))
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for mat in list(bpy.data.materials):
            bpy.data.materials.remove(mat, do_unlink=True)
        for mesh in list(bpy.data.meshes):
            bpy.data.meshes.remove(mesh, do_unlink=True)

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_standalone_material_overlay_active_node_and_fake_user(self):
        """Standalone material with overlay (e.g. grass_block_side) must set Albedo as active and fake_user=False."""
        base_path = self.temp_dir / "grass_block_side.png"
        overlay_path = self.temp_dir / "grass_block_side_overlay.png"
        norm_path = self.temp_dir / "grass_block_side_n.png"
        spec_path = self.temp_dir / "grass_block_side_s.png"

        Image.new("RGBA", (16, 16), (128, 64, 32, 255)).save(base_path)
        Image.new("RGBA", (16, 16), (200, 200, 200, 255)).save(overlay_path)
        Image.new("RGBA", (16, 16), (128, 128, 255, 255)).save(norm_path)
        Image.new("RGBA", (16, 16), (0, 0, 0, 255)).save(spec_path)

        mat = bpy.data.materials.new("TestGrassSideMat")
        texture_info = {
            "namespace": "minecraft",
            "texture_name": "grass_block_side",
            "albedo": base_path,
            "overlay": overlay_path,
            "normal": norm_path,
            "specular": spec_path,
        }
        success = rebuild_material(mat, texture_info)
        self.assertTrue(success)

        # 1. Fake user must be False
        self.assertFalse(mat.use_fake_user, "Material should not have fake user protection")

        # 2. Active node in node tree must be the Albedo texture node, NOT Overlay/Normal/Specular
        nodes = mat.node_tree.nodes
        active_node = nodes.active
        self.assertIsNotNone(active_node, "Material must have an active node")
        self.assertEqual(active_node.bl_idname, "ShaderNodeTexImage")
        self.assertEqual(active_node.name, "Tex Static (Albedo)", f"Active node was {active_node.name} instead of Tex Static (Albedo)")
        self.assertTrue(active_node.select)

        # Ensure overlay, normal, specular nodes are not selected
        for name in ("Tex Static (Overlay)", "Tex Static (Normal)", "Tex Static (Specular)"):
            n = nodes.get(name)
            if n:
                self.assertFalse(n.select, f"Node {name} should not be selected")

    def test_standalone_animated_material_active_node_and_fake_user(self):
        """Standalone animated material with PBR must set Tex Current (Albedo) as active and fake_user=False."""
        albedo_path = self.temp_dir / "sea_lantern.png"
        norm_path = self.temp_dir / "sea_lantern_n.png"
        Image.new("RGBA", (16, 80), (200, 200, 200, 255)).save(albedo_path)
        Image.new("RGBA", (16, 80), (128, 128, 255, 255)).save(norm_path)

        mat = bpy.data.materials.new("TestSeaLanternMat")
        texture_info = {
            "namespace": "minecraft",
            "texture_name": "sea_lantern",
            "albedo": albedo_path,
            "normal": norm_path,
            "albedo_mcmeta": {"frametime": 2},
        }
        success = rebuild_material(mat, texture_info)
        self.assertTrue(success)

        self.assertFalse(mat.use_fake_user)
        nodes = mat.node_tree.nodes
        active_node = nodes.active
        self.assertIsNotNone(active_node)
        self.assertEqual(active_node.name, "Tex Current (Albedo)")
        self.assertTrue(active_node.select)

    def test_repair_material_nodes_active_node_and_fake_user(self):
        """repair_material_nodes must clear fake user and set Albedo node as active."""
        mat = bpy.data.materials.new("TestRepairMat")
        mat.use_nodes = True
        mat.use_fake_user = True
        nodes = mat.node_tree.nodes

        tex_spec = nodes.new("ShaderNodeTexImage")
        tex_spec.name = "Tex Static (Specular)"

        tex_alb = nodes.new("ShaderNodeTexImage")
        tex_alb.name = "Tex Static (Albedo)"

        tex_overlay = nodes.new("ShaderNodeTexImage")
        tex_overlay.name = "Tex Static (Overlay)"
        # tex_overlay became active because it was created last
        nodes.active = tex_overlay

        success = repair_material_nodes(mat)
        self.assertTrue(success)
        self.assertFalse(mat.use_fake_user)
        self.assertEqual(nodes.active, tex_alb)
        self.assertTrue(tex_alb.select)
        self.assertFalse(tex_overlay.select)

    def test_chunk_atlas_material_overlay_active_node_and_fake_user(self):
        """Chunk atlas materials with overlay and normal/specular must set Albedo as active and fake_user=False."""
        atlas_dir = self.temp_dir / "atlas_out"
        atlas_dir.mkdir(parents=True, exist_ok=True)

        alb_file = atlas_dir / "blocks_chunk_000_albedo.png"
        overlay_file = atlas_dir / "blocks_chunk_000_overlay.png"
        norm_file = atlas_dir / "blocks_chunk_000_normal.png"
        spec_file = atlas_dir / "blocks_chunk_000_specular.png"

        Image.new("RGBA", (64, 64), (100, 100, 100, 255)).save(alb_file)
        Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(overlay_file)
        Image.new("RGBA", (64, 64), (128, 128, 255, 255)).save(norm_file)
        Image.new("RGBA", (64, 64), (0, 0, 0, 255)).save(spec_file)

        mapping_data = {
            "atlas_width": 64,
            "atlas_height": 64,
            "tile_size": 16,
            "chunks": [
                {
                    "chunk_id": 0,
                    "kind": "static",
                    "category": "blocks",
                    "width": 64,
                    "height": 64,
                    "tile_size": 16,
                    "has_overlay": True,
                    "files": {
                        "albedo": alb_file.name,
                        "overlay": overlay_file.name,
                        "normal": norm_file.name,
                        "specular": spec_file.name,
                    },
                }
            ]
        }

        with open(atlas_dir / "atlas_mapping.json", "w", encoding="utf-8") as f:
            json.dump(mapping_data, f)

        materials = build_atlas_chunk_materials(atlas_dir, pack_textures=False)
        self.assertIn(0, materials)
        mat = materials[0]

        # 1. Fake user must be False
        self.assertFalse(mat.use_fake_user, "Atlas chunk material should not have fake user")

        # 2. Active node in node tree must be the Albedo texture node
        nodes = mat.node_tree.nodes
        active_node = nodes.active
        self.assertIsNotNone(active_node)
        self.assertEqual(active_node.bl_idname, "ShaderNodeTexImage")
        self.assertEqual(active_node.name, "Atlas Chunk 000 Static (Albedo)", f"Active node was {active_node.name}")
        self.assertTrue(active_node.select)

        # 3. Overlay, Normal, Specular are not selected
        for name in ("Atlas Chunk 000 Static (Overlay)", "Atlas Chunk 000 Static (Normal)", "Atlas Chunk 000 Static (Specular)"):
            n = nodes.get(name)
            if n:
                self.assertFalse(n.select, f"Node {name} should not be selected")

    def test_simple_atlas_material_active_node_and_fake_user(self):
        """build_atlas_material must set Albedo as active and fake_user=False."""
        atlas_dir = self.temp_dir / "simple_atlas"
        atlas_dir.mkdir(parents=True, exist_ok=True)

        alb_file = atlas_dir / "atlas_albedo.png"
        overlay_file = atlas_dir / "atlas_overlay.png"
        mapping_file = atlas_dir / "atlas_mapping.json"

        Image.new("RGBA", (64, 64), (100, 100, 100, 255)).save(alb_file)
        Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(overlay_file)

        mapping_data = {
            "atlas_width": 64,
            "atlas_height": 64,
            "tile_size": 16,
            "static_material_columns": 1,
        }
        with open(mapping_file, "w", encoding="utf-8") as f:
            json.dump(mapping_data, f)

        mat = build_atlas_material(atlas_dir, pack_textures=False)
        self.assertIsNotNone(mat)
        self.assertFalse(mat.use_fake_user)

        nodes = mat.node_tree.nodes
        active_node = nodes.active
        self.assertIsNotNone(active_node)
        self.assertEqual(active_node.name, "Atlas Albedo")
        self.assertTrue(active_node.select)

        overlay_node = nodes.get("Atlas Overlay")
        if overlay_node:
            self.assertFalse(overlay_node.select)

    def test_master_atlas_material_active_node_and_fake_user(self):
        """get_or_create_atlas_material must set Albedo as active and fake_user=False."""
        mat = get_or_create_atlas_material()
        self.assertIsNotNone(mat)
        self.assertFalse(mat.use_fake_user)

        nodes = mat.node_tree.nodes
        active_node = nodes.active
        self.assertIsNotNone(active_node)
        self.assertEqual(active_node.name, "Atlas Albedo")
        self.assertTrue(active_node.select)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
