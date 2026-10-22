"""
Unit tests for MTK mesh attribute sanitization and obsolete attribute cleanup.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from MoziToolKit.bridge.mesh.attribute_schema import (
    ACTIVE_ATTRIBUTE_NAMES,
    RETIRED_ATTRIBUTE_NAMES,
)
from MoziToolKit.bridge.mesh.attributes import inject_custom_attributes
from MoziToolKit.utils.materials.cleaner import clean_obsolete_mesh_attributes
from MoziToolKit.utils.materials.constants import (
    ATTR_ATLAS_CHUNK_ID,
    ATTR_BIOME_TINT_COLOR,
    ATTR_UV_TRANSFORM,
)


class MockAttributeData:
    def __init__(self, name: str, count: int = 4):
        self.name = name
        self.data = [MagicMock() for _ in range(count)]
        self.data_type = "FLOAT"
        self.domain = "FACE"

    def foreach_set(self, key, values):
        pass


class MockAttributesCollection:
    def __init__(self):
        self._attrs: dict[str, MockAttributeData] = {}

    def get(self, name, default=None):
        return self._attrs.get(name, default)

    def __contains__(self, name):
        return name in self._attrs

    def __getitem__(self, name):
        return self._attrs[name]

    def __setitem__(self, name, value):
        self._attrs[name] = value

    def __iter__(self):
        return iter(self._attrs.values())

    def remove(self, attr):
        name_to_del = None
        for k, v in self._attrs.items():
            if v == attr or k == getattr(attr, "name", None):
                name_to_del = k
                break
        if name_to_del:
            del self._attrs[name_to_del]

    def new(self, name, type, domain):
        attr = MockAttributeData(name)
        attr.data_type = type
        attr.domain = domain
        self._attrs[name] = attr
        return attr


class MockMesh:
    def __init__(self, face_count: int = 4):
        self.attributes = MockAttributesCollection()
        self.polygons = [MagicMock() for _ in range(face_count)]
        self.custom_props = {}

    def __contains__(self, item):
        return item in self.custom_props

    def __setitem__(self, key, value):
        self.custom_props[key] = value

    def __getitem__(self, key):
        return self.custom_props[key]

    def get(self, key, default=None):
        return self.custom_props.get(key, default)


class TestMeshAttributeCleanup(unittest.TestCase):
    def test_clean_obsolete_mesh_attributes_removes_excluded(self):
        mesh = MockMesh(face_count=10)
        # Populate mesh with some canonical and some obsolete attributes
        mesh.attributes[ATTR_ATLAS_CHUNK_ID] = MockAttributeData(ATTR_ATLAS_CHUNK_ID, 10)
        mesh.attributes[ATTR_UV_TRANSFORM] = MockAttributeData(ATTR_UV_TRANSFORM, 10)
        mesh.attributes[ATTR_BIOME_TINT_COLOR] = MockAttributeData(ATTR_BIOME_TINT_COLOR, 10)

        # Add obsolete attributes
        mesh.attributes["mtk_colormap_uv"] = MockAttributeData("mtk_colormap_uv", 10)
        mesh.attributes["mtk_material_slot"] = MockAttributeData("mtk_material_slot", 10)
        mesh.attributes["mtk_atlas_texture_id"] = MockAttributeData("mtk_atlas_texture_id", 10)
        mesh.attributes["mtk_uv_mode"] = MockAttributeData("mtk_uv_mode", 10)
        mesh.attributes["mtk_face_dir"] = MockAttributeData("mtk_face_dir", 10)
        mesh.attributes["mtk_emission"] = MockAttributeData("mtk_emission", 10)
        mesh.attributes["mtk_anim_total_frames"] = MockAttributeData("mtk_anim_total_frames", 10)
        mesh.attributes["mtk_material_props"] = MockAttributeData("mtk_material_props", 10)

        removed = clean_obsolete_mesh_attributes(mesh)

        self.assertIn("mtk_colormap_uv", removed)
        self.assertIn("mtk_material_slot", removed)
        self.assertIn("mtk_atlas_texture_id", removed)
        self.assertIn("mtk_uv_mode", removed)
        self.assertIn("mtk_face_dir", removed)
        self.assertIn("mtk_emission", removed)
        self.assertIn("mtk_anim_total_frames", removed)
        self.assertIn("mtk_material_props", removed)

        # Canonical attributes must NOT be removed
        self.assertIn(ATTR_ATLAS_CHUNK_ID, mesh.attributes)
        self.assertIn(ATTR_UV_TRANSFORM, mesh.attributes)
        self.assertIn(ATTR_BIOME_TINT_COLOR, mesh.attributes)

    def test_clean_obsolete_mesh_attributes_preserves_source_texture_key(self):
        mesh = MockMesh(face_count=300)
        mesh.attributes["mtk_source_texture_key"] = MockAttributeData("mtk_source_texture_key", 300)
        mesh.attributes["mtk_source_texture_idx"] = MockAttributeData("mtk_source_texture_idx", 300)
        mesh["mtk_source_textures"] = ["stone", "dirt"]

        removed = clean_obsolete_mesh_attributes(mesh)
        self.assertNotIn("mtk_source_texture_key", removed)
        self.assertIn("mtk_source_texture_key", mesh.attributes)

    def test_resolve_source_texture_keys_string_fallback(self):
        from MoziToolKit.bridge.mesh.attributes import (
            resolve_source_texture_keys,
            resolve_source_texture_keys_paletted,
        )

        mesh = MockMesh(face_count=3)
        # Populate ONLY mtk_source_texture_key without mtk_source_textures custom property
        class MockStringElem:
            def __init__(self, val):
                self.value = val

        attr_str = MagicMock()
        attr_str.data = [MockStringElem("minecraft:block/stone"), MockStringElem("minecraft:block/dirt"), MockStringElem("minecraft:block/stone")]
        mesh.attributes["mtk_source_texture_key"] = attr_str

        keys = resolve_source_texture_keys(mesh)
        self.assertEqual(keys, ["minecraft:block/stone", "minecraft:block/dirt", "minecraft:block/stone"])

        pal, idx = resolve_source_texture_keys_paletted(mesh)
        self.assertEqual(pal, ["minecraft:block/stone", "minecraft:block/dirt"])
        self.assertEqual(list(idx), [0, 1, 0])

    def test_inject_custom_attributes_skips_excluded(self):
        mesh = MockMesh(face_count=4)

        # Mock MeshData with both canonical and dead attributes
        mock_mesh_data = MagicMock()
        mock_mesh_data.attribute_names.return_value = [
            "mtk_atlas_chunk_id",
            "mtk_uv_transform",
            "mtk_colormap_uv",
            "mtk_material_slot",
            "mtk_atlas_texture_id",
            "mtk_anim_total_frames",
        ]
        mock_mesh_data.attribute_info.side_effect = lambda name: {
            "mtk_atlas_chunk_id": ("face", "int32", 4),
            "mtk_uv_transform": ("face", "float4", 4),
            "mtk_colormap_uv": ("face", "float3", 4),
            "mtk_material_slot": ("face", "int32", 4),
            "mtk_atlas_texture_id": ("face", "uint32", 4),
            "mtk_anim_total_frames": ("face", "float", 4),
        }.get(name)

        mock_mesh_data.attribute_memoryview.return_value = None

        inject_custom_attributes(mesh, mock_mesh_data)

        # Canonical attributes must be injected
        self.assertIn("mtk_atlas_chunk_id", mesh.attributes)
        self.assertIn("mtk_uv_transform", mesh.attributes)

        # Excluded attributes must NOT be injected
        self.assertNotIn("mtk_colormap_uv", mesh.attributes)
        self.assertNotIn("mtk_material_slot", mesh.attributes)
        self.assertNotIn("mtk_atlas_texture_id", mesh.attributes)
        self.assertNotIn("mtk_anim_total_frames", mesh.attributes)

    def test_active_and_retired_disjoint(self):
        # The native schema must never declare the same attribute as active and retired.
        overlap = ACTIVE_ATTRIBUTE_NAMES.intersection(RETIRED_ATTRIBUTE_NAMES)
        self.assertEqual(len(overlap), 0, f"Overlap between active and retired: {overlap}")


if __name__ == "__main__":
    unittest.main()
