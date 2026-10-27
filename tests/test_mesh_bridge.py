"""
Tests for MoziToolKit Bridge and Material Presets.
"""

import _mesh_arrays as ma
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock
import array
import ctypes
import numpy as np

PROJECT_DIR = Path(__file__).parent.parent.resolve()
PARENT_DIR = PROJECT_DIR.parent
libmtk_release_path = PROJECT_DIR.parent / "libmozitoolkit" / "target" / "release"

for p in [str(libmtk_release_path), str(PROJECT_DIR), str(PARENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

if "bpy" not in sys.modules:
    sys.modules["bpy"] = MagicMock()
if "mathutils" not in sys.modules:
    sys.modules["mathutils"] = MagicMock()


import bpy

HAS_BPY = not isinstance(bpy, MagicMock) and hasattr(bpy, "data") and hasattr(bpy.data, "meshes")

from MoziToolKit.bridge.engine import get_libmtk
from MoziToolKit.bridge.mesh import (
    BLENDER_TO_MTK_DOMAIN,
    BLENDER_TO_MTK_TYPE,
    MTK_TO_BLENDER_DOMAIN,
    MTK_TO_BLENDER_TYPE,
    extract_mesh_data,
    inject_mesh_data,
    resolve_source_texture_keys,
    inject_face_source_texture_keys,
)
from MoziToolKit.utils.materials.matching.presets.registry import (
    build_matching_context,
    build_material_alias_map,
    clean_mtk_material_name,
    detect_material_origin,
    generate_candidates_for_name,
)
from MoziToolKit.utils.materials.matching.presets.mineways import build_mineways_grid_spec
from MoziToolKit.utils.materials.matching.presets.mineways_table import MINEWAYS_TILES_TABLE


class TestMaterialPresets(unittest.TestCase):
    def test_mineways_table_integrity(self):
        self.assertGreater(len(MINEWAYS_TILES_TABLE), 1200)
        self.assertEqual(MINEWAYS_TILES_TABLE[0][2], "grass_block_top")
        self.assertEqual(MINEWAYS_TILES_TABLE[1][2], "stone")

    def test_mineways_spec_generation(self):
        spec = build_mineways_grid_spec()
        if isinstance(spec, dict):
            self.assertIn("swatch_size", spec)
            self.assertIn("tile_size", spec)
            self.assertIn("swatch_to_candidates", spec)
            self.assertEqual(spec["swatch_size"], 18.0)
            self.assertEqual(spec["tile_size"], 16.0)
            self.assertGreater(len(spec["swatch_to_candidates"]), 1200)
        else:
            self.assertEqual(spec.swatch_size, 18.0)
            self.assertEqual(spec.tile_size, 16.0)

    def test_preset_registry(self):
        self.assertEqual(detect_material_origin("mineways_stone"), "mineways")
        self.assertEqual(detect_material_origin("minecraft_block_stone"), "jmc2obj")
        self.assertEqual(detect_material_origin("ice_cube_dirt"), "ice_cube")
        self.assertEqual(detect_material_origin("mtk:minecraft:grass_block_top:8d09ec43b668"), "mtk")

        # Test clean_mtk_material_name
        self.assertEqual(clean_mtk_material_name("mtk:minecraft:bell_side:8d09ec43b668"), "minecraft:bell_side")
        self.assertEqual(clean_mtk_material_name("MTK:minecraft:grass_block_top:8d09ec43b668"), "minecraft:grass_block_top")

        # Test generate_candidates_for_name for MTK materials
        candidates = generate_candidates_for_name("mtk:minecraft:bell_side:8d09ec43b668")
        self.assertIn("minecraft:bell_side", candidates)
        self.assertIn("bell_side", candidates)
        self.assertIn("block/bell_side", candidates)
        self.assertIn("minecraft:block/bell_side", candidates)

        alias_map, grid_spec = build_matching_context(["mineways_stone"], origin="mineways")
        self.assertIn("mineways_stone", alias_map)
        self.assertIsNotNone(grid_spec)
        if isinstance(grid_spec, dict):
            self.assertEqual(grid_spec["swatch_size"], 18.0)
        else:
            self.assertEqual(grid_spec.swatch_size, 18.0)



class MockBlenderCollection:
    def __init__(self, data_list, attr_map=None):
        self._data = data_list
        self._attr_map = attr_map or {}

    def __len__(self):
        return len(self._data)

    def __getitem__(self, idx):
        return self._data[idx]

    def foreach_get(self, attr_name, target_array):
        # Flattened extraction
        for i, item in enumerate(self._data):
            val = getattr(item, attr_name, None)
            if val is None and isinstance(item, dict):
                val = item.get(attr_name)
            if isinstance(val, (list, tuple)):
                for comp_idx, c_val in enumerate(val):
                    target_array[i * len(val) + comp_idx] = c_val
            else:
                target_array[i] = val

    def foreach_set(self, attr_name, source_array):
        for i, item in enumerate(self._data):
            if hasattr(item, attr_name):
                setattr(item, attr_name, source_array[i])


class MockMeshVertex:
    def __init__(self, co, normal):
        self.co = co
        self.normal = normal


class MockMeshPolygon:
    def __init__(self, vertices, material_index=0, loop_start=0):
        self.vertices = vertices
        self.material_index = material_index
        self.loop_total = len(vertices)
        self.loop_start = loop_start


class MockMeshLoopTriangle:
    def __init__(self, vertices, material_index=0):
        self.vertices = vertices
        self.material_index = material_index


class MockMeshLoop:
    def __init__(self, vertex_index):
        self.vertex_index = vertex_index


class MockMeshUVLoop:
    def __init__(self, uv):
        self.uv = uv


class MockUVLayer:
    def __init__(self, name="UVMap", uvs=None):
        self.name = name
        self.data = MockBlenderCollection([MockMeshUVLoop(uv) for uv in (uvs or [])])


class MockMesh:
    def __init__(self):
        # 4 vertices for a single quad (2 triangles)
        self.vertices = MockBlenderCollection([
            MockMeshVertex([0.0, 0.0, 0.0], [0.0, 1.0, 0.0]),
            MockMeshVertex([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]),
            MockMeshVertex([1.0, 0.0, 1.0], [0.0, 1.0, 0.0]),
            MockMeshVertex([0.0, 0.0, 1.0], [0.0, 1.0, 0.0]),
        ])
        self.loops = MockBlenderCollection([
            MockMeshLoop(0),
            MockMeshLoop(1),
            MockMeshLoop(2),
            MockMeshLoop(3),
        ])
        self.polygons = MockBlenderCollection([
            MockMeshPolygon([0, 1, 2, 3], material_index=1)
        ])
        self.loop_triangles = MockBlenderCollection([
            MockMeshLoopTriangle([0, 1, 2], material_index=1),
            MockMeshLoopTriangle([0, 2, 3], material_index=1),
        ])
class MockUVLayers(list):
    def __init__(self, layers):
        super().__init__(layers)
        self.active = layers[0] if layers else None

    def get(self, name):
        for l in self:
            if l.name == name:
                return l
        return None

    def new(self, name="UVMap"):
        layer = MockUVLayer(name, [])
        self.append(layer)
        self.active = layer
        return layer


class MockMesh:
    def __init__(self):
        # 4 vertices for a single quad (2 triangles)
        self.vertices = MockBlenderCollection([
            MockMeshVertex([0.0, 0.0, 0.0], [0.0, 1.0, 0.0]),
            MockMeshVertex([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]),
            MockMeshVertex([1.0, 0.0, 1.0], [0.0, 1.0, 0.0]),
            MockMeshVertex([0.0, 0.0, 1.0], [0.0, 1.0, 0.0]),
        ])
        self.loops = MockBlenderCollection([
            MockMeshLoop(0),
            MockMeshLoop(1),
            MockMeshLoop(2),
            MockMeshLoop(3),
        ])
        self.polygons = MockBlenderCollection([
            MockMeshPolygon([0, 1, 2, 3], material_index=1)
        ])
        self.loop_triangles = MockBlenderCollection([
            MockMeshLoopTriangle([0, 1, 2], material_index=1),
            MockMeshLoopTriangle([0, 2, 3], material_index=1),
        ])
        self.uv_layers = MockUVLayers([
            MockUVLayer("UVMap", [
                [0.0, 0.0],
                [1.0, 0.0],
                [1.0, 1.0],
                [0.0, 1.0],
            ])
        ])
        self.attributes = []

    def calc_loop_triangles(self):
        pass

    def clear_geometry(self):
        pass

    def from_pydata(self, verts, edges, faces):
        pass

    def update(self):
        self.updated = True


class TestMeshBridge(unittest.TestCase):
    def test_domain_mappings(self):
        self.assertEqual(BLENDER_TO_MTK_DOMAIN["POINT"], "point")
        self.assertEqual(BLENDER_TO_MTK_DOMAIN["CORNER"], "corner")
        self.assertEqual(BLENDER_TO_MTK_DOMAIN["FACE"], "face")
        self.assertEqual(MTK_TO_BLENDER_DOMAIN["point"], "POINT")
        self.assertEqual(MTK_TO_BLENDER_DOMAIN["corner"], "CORNER")
        self.assertEqual(MTK_TO_BLENDER_DOMAIN["face"], "FACE")

    def test_type_mappings(self):
        self.assertEqual(BLENDER_TO_MTK_TYPE["FLOAT"][0], "float")
        self.assertEqual(BLENDER_TO_MTK_TYPE["FLOAT_VECTOR"][0], "float3")
        self.assertEqual(MTK_TO_BLENDER_TYPE["Float"][0], "FLOAT")
        self.assertEqual(MTK_TO_BLENDER_TYPE["Float3"][0], "FLOAT_VECTOR")

    def test_mock_mesh_update(self):
        mock_mesh = MockMesh()
        self.assertEqual(len(mock_mesh.vertices), 4)
        self.assertEqual(len(mock_mesh.loop_triangles), 2)
        mock_mesh.update()
        self.assertTrue(mock_mesh.updated)

    def test_extract_mesh_data_quads(self):
        mock_mesh = MockMesh()
        mesh_data = extract_mesh_data(mock_mesh)
        self.assertEqual(mesh_data.vertex_count, 4)
        self.assertEqual(mesh_data.triangle_count, 2)
        indices = ma.indices(mesh_data)
        self.assertEqual(len(indices), 6)
        self.assertEqual(mesh_data.uv_layout, "per_loop")
        self.assertEqual(len(ma.loop_uvs(mesh_data)), 8)
        face_mats = ma.face_materials(mesh_data)
        self.assertEqual(len(face_mats), 1)
        self.assertEqual(face_mats[0], 1)


class TestDualMeshApi(unittest.TestCase):
    """Verifies strict separation and functionality of Universal Python vs Blender Direct Pointer APIs."""

    def setUp(self):
        mtk = get_libmtk()
        if mtk is None or not hasattr(mtk, "MeshData"):
            self.skipTest("libmtk MeshData not available")
        self.mesh = ma.unit_quad()

    def test_universal_python_zero_copy_api(self):
        """Suite B: Universal Python memoryview & buffer protocol API."""
        pos_mv = self.mesh.positions_memoryview()
        self.assertIsInstance(pos_mv, memoryview)
        pos_arr = np.frombuffer(pos_mv, dtype=np.float32).reshape(-1, 3)
        self.assertEqual(len(pos_arr), 4)

        idx_mv = self.mesh.indices_memoryview()
        self.assertIsInstance(idx_mv, memoryview)
        idx_arr = np.frombuffer(idx_mv, dtype=np.uint32)
        self.assertEqual(len(idx_arr), 6)

        quad_mv = self.mesh.quad_indices_memoryview()
        self.assertIsNotNone(quad_mv)
        quad_arr = np.frombuffer(quad_mv, dtype=np.uint32)
        self.assertEqual(len(quad_arr), 4)

        uv_mv = self.mesh.uvs_memoryview()
        self.assertIsInstance(uv_mv, memoryview)

    def test_blender_direct_pointer_api(self):
        """Suite A: standalone Blender DNA adapter writes typed core views."""
        from MoziToolKit.bridge.engine import get_libmtk_dna

        dna = get_libmtk_dna()
        if dna is None or not hasattr(dna, "copy_f32"):
            self.skipTest("libmtk_blender_dna is not available")
        self.assertFalse(hasattr(self.mesh, "blender_direct"))

        buf = (ctypes.c_float * 12)()
        ptr = ctypes.addressof(buf)
        src = memoryview(self.mesh.positions_memoryview()).cast("B")
        written = dna.copy_f32(src, ptr, 12, max_bytes=48)
        self.assertEqual(written, 48)


    def test_source_texture_palette_indices(self):
        """Rust builds palette + u32 indices without materializing per-face strings."""
        if not hasattr(self.mesh, "source_texture_palette_indices"):
            self.skipTest("source_texture_palette_indices not available in this libmtk build")
        keys = [
            "minecraft:block/grass_block_top",
            "minecraft:block/dirt",
            "minecraft:block/grass_block_top",
        ]
        mesh = ma.unit_quads(3)
        mesh.add_string_attribute("mtk_source_texture_key", "face", keys)

        palette, indices = mesh.source_texture_palette_indices()
        self.assertEqual(palette, ["minecraft:block/grass_block_top", "minecraft:block/dirt"])
        self.assertEqual(np.frombuffer(indices, dtype=np.uint32).tolist(), [0, 1, 0])


class TestPaletteSourceTextureKeys(unittest.TestCase):
    def test_resolve_from_palette_int(self):
        class MockAttrData:
            def __init__(self, values):
                self._values = values
            def __len__(self):
                return len(self._values)
            def foreach_get(self, attr_name, target):
                for i, v in enumerate(self._values):
                    target[i] = v

        class MockAttr:
            def __init__(self, values):
                self.data = MockAttrData(values)

        class MockMeshObj:
            def __init__(self):
                self.polygons = [object(), object(), object(), object()]
                self.attributes = {"mtk_source_texture_idx": MockAttr([0, 1, 0, 2])}
                self["mtk_source_textures"] = ["stone", "grass_block_top", "dirt"]

            def __contains__(self, key):
                return key in self.__dict__

            def __getitem__(self, key):
                return self.__dict__[key]

            def __setitem__(self, key, value):
                self.__dict__[key] = value

            def keys(self):
                return self.__dict__.keys()

        mesh = MockMeshObj()
        resolved = resolve_source_texture_keys(mesh)
        self.assertEqual(resolved, ["stone", "grass_block_top", "stone", "dirt"])



@unittest.skipUnless(HAS_BPY, "Requires real Blender bpy")
class TestPaletteProvenanceParity(unittest.TestCase):
    """Save imports and Live Sync must expose identical palette provenance."""

    def test_skip_string_flag_does_not_change_provenance(self):
        keys = ["minecraft:block/grass_block_top", "minecraft:block/dirt"]
        resolved_by_mode = {}
        for skip in (False, True):
            mtk = get_libmtk()
            mesh_data = ma.unit_quads(2)
            mesh_data.add_string_attribute("mtk_source_texture_key", "face", keys)

            name = f"mtk_palette_parity_{int(skip)}"
            b_mesh = bpy.data.meshes.new(name)
            obj = bpy.data.objects.new(name, b_mesh)
            bpy.context.scene.collection.objects.link(obj)
            try:
                inject_mesh_data(
                    mesh_data,
                    b_mesh,
                    update_topology=True,
                    update_normals=True,
                    skip_string_attributes=skip,
                )
                self.assertIn("mtk_source_textures", b_mesh)
                self.assertIn("mtk_source_texture_idx", b_mesh.attributes)
                resolved_by_mode[skip] = resolve_source_texture_keys(b_mesh)
            finally:
                bpy.data.objects.remove(obj, do_unlink=True)
                bpy.data.meshes.remove(b_mesh)

        self.assertEqual(resolved_by_mode[False], keys)
        self.assertEqual(resolved_by_mode[True], keys)


class TestColorAttributeInjection(unittest.TestCase):
    def test_inject_color_attributes_standard_sets_active_color(self):
        from MoziToolKit.bridge.mesh.standard import inject_color_attributes_standard

        class MockColorAttrData:
            def __init__(self, size):
                self.size = size
                self.values = None

            def __len__(self):
                return self.size

            def foreach_set(self, attr_name, array_data):
                self.values = list(array_data)

        class MockColorAttr:
            def __init__(self, name, domain, size):
                self.name = name
                self.domain = domain
                self.data = MockColorAttrData(size)

        class MockColorAttributes:
            def __init__(self, loop_count):
                self.attrs = {}
                self.active_color = None
                self.loop_count = loop_count

            def get(self, name, default=None):
                return self.attrs.get(name, default)

            def new(self, name, type, domain):
                attr = MockColorAttr(name, domain, self.loop_count)
                self.attrs[name] = attr
                return attr

            def __contains__(self, name):
                return name in self.attrs

        class MockMesh:
            def __init__(self, loop_count=4):
                self.loops = [object()] * loop_count
                self.vertices = [object()] * 4
                self.color_attributes = MockColorAttributes(loop_count)

        mesh = MockMesh(loop_count=4)
        colors_f32 = np.array([
            0.5, 0.2, 0.1, 1.0,
            0.5, 0.2, 0.1, 1.0,
            0.5, 0.2, 0.1, 1.0,
            0.5, 0.2, 0.1, 1.0,
        ], dtype=np.float32)

        class MockMeshData:
            def colors_memoryview(self):
                return memoryview(colors_f32)

        inject_color_attributes_standard(mesh, MockMeshData())

        self.assertIn("color", mesh.color_attributes.attrs)
        col_attr = mesh.color_attributes.get("color")
        self.assertIsNotNone(col_attr)
        self.assertEqual(mesh.color_attributes.active_color, col_attr)
        self.assertEqual(len(col_attr.data.values), 16)
        self.assertAlmostEqual(col_attr.data.values[0], 0.5, places=5)
        self.assertAlmostEqual(col_attr.data.values[1], 0.2, places=5)

    def test_inject_color_attributes_dna_sets_active_color(self):
        from unittest.mock import MagicMock, patch
        from MoziToolKit.bridge.mesh.dna import inject_color_attributes_dna

        class MockColorAttr:
            def __init__(self, name, domain, size):
                self.name = name
                self.domain = domain
                self.data = [MagicMock()] * size

        class MockColorAttributes:
            def __init__(self, loop_count):
                self.attrs = {}
                self.active_color = None
                self.loop_count = loop_count

            def get(self, name, default=None):
                return self.attrs.get(name, default)

            def new(self, name, type, domain):
                attr = MockColorAttr(name, domain, self.loop_count)
                self.attrs[name] = attr
                return attr

            def __contains__(self, name):
                return name in self.attrs

        class MockMesh:
            def __init__(self, loop_count=4):
                self.loops = [object()] * loop_count
                self.vertices = [object()] * 4
                self.color_attributes = MockColorAttributes(loop_count)

        mesh = MockMesh(loop_count=4)
        colors_f32 = np.array([
            0.5, 0.2, 0.1, 1.0,
            0.5, 0.2, 0.1, 1.0,
            0.5, 0.2, 0.1, 1.0,
            0.5, 0.2, 0.1, 1.0,
        ], dtype=np.float32)

        class MockMeshData:
            def colors_memoryview(self):
                return memoryview(colors_f32)

        mock_dna = MagicMock()
        mock_dna.copy_f32.return_value = None

        with patch("MoziToolKit.bridge.mesh.dna.get_libmtk_dna", return_value=mock_dna), \
             patch("MoziToolKit.bridge.mesh.dna.is_dna_available", return_value=True), \
             patch("MoziToolKit.bridge.mesh.dna.resolve_colors_ptr", return_value=0x12345678):
            result = inject_color_attributes_dna(mesh, MockMeshData())

        self.assertTrue(result)
        self.assertIn("color", mesh.color_attributes.attrs)
        col_attr = mesh.color_attributes.get("color")
        self.assertIsNotNone(col_attr)
        self.assertEqual(mesh.color_attributes.active_color, col_attr)
        mock_dna.copy_f32.assert_called_once()

    def test_inject_face_materials_standard_triangulated_quad_expansion(self):
        """Regression test: triangulated quad meshes should repeat face material slots across both triangles."""
        from MoziToolKit.bridge.mesh.standard import inject_face_materials_standard

        class MockPolygons:
            def __init__(self, count):
                self.count = count
                self.slots = None

            def __len__(self):
                return self.count

            def foreach_set(self, attr, arr):
                if attr == "material_index":
                    self.slots = list(arr)

        class MockMesh:
            def __init__(self, poly_count=2):
                self.polygons = MockPolygons(poly_count)

        # 1 quad face with material 3, but triangulated into 2 triangles
        mesh = MockMesh(poly_count=2)
        mats_u16 = np.array([3], dtype=np.uint16)

        class MockMeshData:
            def face_materials_memoryview(self):
                return memoryview(mats_u16)

        inject_face_materials_standard(mesh, MockMeshData())
        self.assertEqual(mesh.polygons.slots, [3, 3])

    def test_inject_color_attributes_standard_triangulated_quad_expansion(self):
        """Regression test: triangulated quad meshes expand 4 quad corners to 6 triangle loop corners."""
        from MoziToolKit.bridge.mesh.standard import inject_color_attributes_standard

        class MockColorAttrData:
            def __init__(self, size):
                self.size = size
                self.values = []

            def foreach_set(self, attr, arr):
                self.values = list(arr)

            def __len__(self):
                return self.size

        class MockColorAttr:
            def __init__(self, name, domain, size):
                self.name = name
                self.domain = domain
                self.data = MockColorAttrData(size)

        class MockColorAttributes:
            def __init__(self, loop_count):
                self.attrs = {}
                self.active_color = None
                self.loop_count = loop_count

            def get(self, name, default=None):
                return self.attrs.get(name, default)

            def new(self, name, type, domain):
                attr = MockColorAttr(name, domain, self.loop_count)
                self.attrs[name] = attr
                return attr

            def __contains__(self, name):
                return name in self.attrs

        class MockMesh:
            def __init__(self, loop_count=6):
                self.loops = [object()] * loop_count
                self.vertices = [object()] * 4
                self.color_attributes = MockColorAttributes(loop_count)

        # 1 quad face with 4 distinct corner colors, triangulated into 2 triangles (6 loops)
        mesh = MockMesh(loop_count=6)
        colors_f32 = np.array([
            1.0, 0.0, 0.0, 1.0,  # Corner 0
            0.0, 1.0, 0.0, 1.0,  # Corner 1
            0.0, 0.0, 1.0, 1.0,  # Corner 2
            1.0, 1.0, 0.0, 1.0,  # Corner 3
        ], dtype=np.float32)

        class MockMeshData:
            def colors_memoryview(self):
                return memoryview(colors_f32)

        inject_color_attributes_standard(mesh, MockMeshData())

        col_attr = mesh.color_attributes.get("color")
        self.assertIsNotNone(col_attr)
        self.assertEqual(len(col_attr.data.values), 24)  # 6 corners * 4 floats
        # Tri 1: corners 0, 1, 2
        self.assertEqual(col_attr.data.values[0:4], [1.0, 0.0, 0.0, 1.0])
        self.assertEqual(col_attr.data.values[4:8], [0.0, 1.0, 0.0, 1.0])
        self.assertEqual(col_attr.data.values[8:12], [0.0, 0.0, 1.0, 1.0])
        # Tri 2: corners 0, 2, 3
        self.assertEqual(col_attr.data.values[12:16], [1.0, 0.0, 0.0, 1.0])
        self.assertEqual(col_attr.data.values[16:20], [0.0, 0.0, 1.0, 1.0])
        self.assertEqual(col_attr.data.values[20:24], [1.0, 1.0, 0.0, 1.0])


if __name__ == "__main__":
    if "--" in sys.argv:
        argv = [sys.argv[0]] + sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = [sys.argv[0]]
    unittest.main(argv=argv)

