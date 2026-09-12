"""
Tests for MoziToolKit Bridge and Material Presets.
"""

import unittest
from unittest.mock import MagicMock
import array

from bridge.mesh import (
    BLENDER_TO_MTK_DOMAIN,
    BLENDER_TO_MTK_TYPE,
    MTK_TO_BLENDER_DOMAIN,
    MTK_TO_BLENDER_TYPE,
    extract_mesh_data,
    inject_mesh_data,
)
from utils.materials.matching.presets.registry import (
    build_matching_context,
    build_material_alias_map,
    detect_material_origin,
    generate_candidates_for_name,
)
from utils.materials.matching.presets.mineways import build_mineways_grid_spec
from utils.materials.matching.presets.mineways_table import MINEWAYS_TILES_TABLE


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
    def __init__(self, vertices, material_index=0):
        self.vertices = vertices
        self.material_index = material_index


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


if __name__ == "__main__":
    unittest.main()
