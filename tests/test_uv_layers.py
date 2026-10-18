"""
Unit tests for multi-UV layer management and atlas layout hashing.

These run without Blender by using lightweight fake UV collections.
"""

from __future__ import annotations

import array
import unittest

from utils.materials.uv_layers import (
    ATLAS_LAYOUT_HASH_PROP,
    ATLAS_UV_LAYER_NAME,
    ATLAS_UV_LAYER_PROP,
    LOCAL_UV_LAYER_PROP,
    compute_atlas_layout_hash,
    detect_legacy_atlas_mesh,
    get_stored_layout_hash,
    read_uv_layer,
    resolve_uv_layers,
    set_stored_layout_hash,
)


class _FakeUVData:
    def __init__(self, uvs):
        self.uvs = list(uvs)

    def foreach_get(self, attr, out):
        out[:] = array.array("f", self.uvs[:len(out)])

    def foreach_set(self, attr, values):
        self.uvs = list(values)


class _FakeUVLayer:
    def __init__(self, name, uvs):
        self.name = name
        self.data = _FakeUVData(uvs)


class _FakeUVLayers:
    def __init__(self, loop_count):
        self._layers = []
        self._active_index = 0
        self._loop_count = loop_count

    def __len__(self):
        return len(self._layers)

    def __getitem__(self, index):
        return self._layers[index]

    def __iter__(self):
        return iter(self._layers)

    def new(self, name):
        layer = _FakeUVLayer(name, [0.0] * (self._loop_count * 2))
        self._layers.append(layer)
        return layer

    def get(self, name):
        for layer in self._layers:
            if layer.name == name:
                return layer
        return None

    def find(self, name):
        for index, layer in enumerate(self._layers):
            if layer.name == name:
                return index
        return -1

    @property
    def active(self):
        return self._layers[self._active_index] if self._layers else None

    @active.setter
    def active(self, layer):
        index = self.find(layer.name)
        if index >= 0:
            self._active_index = index

    @property
    def active_index(self):
        return self._active_index

    @active_index.setter
    def active_index(self, value):
        self._active_index = value

    @property
    def active_render(self):
        return self.active

    @active_render.setter
    def active_render(self, layer):
        self.active = layer


class _FakeMesh:
    def __init__(self, loop_count=8):
        self.loops = [0] * loop_count
        self.uv_layers = _FakeUVLayers(loop_count)
        self.attributes = {}
        self._props = {}

    def __getitem__(self, key):
        return self._props[key]

    def __setitem__(self, key, value):
        self._props[key] = value

    def get(self, key, default=None):
        return self._props.get(key, default)

    def __contains__(self, key):
        return key in self._props


def _mapping():
    return {
        "chunks": [
            {
                "chunk_id": 0,
                "category": "blocks",
                "category_chunk_index": 1,
                "is_animated": False,
                "width": 1024,
                "height": 1024,
                "has_normal": True,
                "has_specular": False,
                "has_overlay": False,
            }
        ],
        "sprites": {
            "minecraft:block/stone": {
                "texture_id": 1,
                "chunk_id": 0,
                "uv_bounds": [0.0, 0.0, 0.25, 0.25],
                "frame_0_uv_bounds": [0.0, 0.0, 0.25, 0.25],
                "local_uv_bounds": [0.0, 0.0, 1.0, 1.0],
                "frame_uv_step": [0.0, 0.0],
                "frame_size": [16, 16],
                "frame_count": 1,
                "is_animated": False,
                "pixel_rect": [0, 0, 16, 16],
            }
        },
        "anim_sprites": {},
    }


class TestUVLayerResolution(unittest.TestCase):
    def test_creates_atlas_and_preserves_local(self):
        mesh = _FakeMesh(loop_count=4)
        local = mesh.uv_layers.new("UVMap")
        local.data.uvs = [0.25, 0.75] * 4

        local_layer, atlas_layer, created = resolve_uv_layers(mesh)
        self.assertIs(local_layer, local)
        self.assertIsNotNone(atlas_layer)
        self.assertTrue(created)
        self.assertEqual(atlas_layer.name, ATLAS_UV_LAYER_NAME)
        self.assertEqual(mesh.uv_layers.active, atlas_layer)
        self.assertEqual(mesh[LOCAL_UV_LAYER_PROP], "UVMap")
        self.assertEqual(mesh[ATLAS_UV_LAYER_PROP], ATLAS_UV_LAYER_NAME)
        # Creation copies the local layout into the atlas map before re-mapping.
        self.assertEqual(atlas_layer.data.uvs, local.data.uvs)

        local_layer_2, atlas_layer_2, created_2 = resolve_uv_layers(mesh)
        self.assertIs(local_layer_2, local)
        self.assertIs(atlas_layer_2, atlas_layer)
        self.assertFalse(created_2)
        self.assertEqual(len(mesh.uv_layers), 2)
        self.assertEqual(local.data.uvs, [0.25, 0.75] * 4)

    def test_legacy_atlas_detection_and_resolution(self):
        mesh = _FakeMesh()
        layer = mesh.uv_layers.new("UVMap")
        mesh.attributes = {
            "mtk_source_texture_key": object(),
            "mtk_atlas_chunk_id": object(),
        }
        self.assertTrue(detect_legacy_atlas_mesh(mesh))

        local_layer, atlas_layer, created = resolve_uv_layers(mesh, legacy_atlas=True)
        self.assertIsNone(local_layer)
        self.assertIs(atlas_layer, layer)
        self.assertFalse(created)
        self.assertEqual(mesh[ATLAS_UV_LAYER_PROP], "UVMap")
        self.assertNotIn(LOCAL_UV_LAYER_PROP, mesh)
        self.assertEqual(len(mesh.uv_layers), 1)

    def test_no_layers_creates_local_uvmap(self):
        mesh = _FakeMesh()
        local, atlas, created = resolve_uv_layers(mesh)
        self.assertIsNotNone(local)
        self.assertEqual(local.name, "UVMap")
        self.assertIsNotNone(atlas)
        self.assertTrue(created)
        self.assertEqual(len(mesh.uv_layers), 2)

    def test_read_and_store_layout_hash(self):
        mesh = _FakeMesh()
        self.assertEqual(get_stored_layout_hash(mesh), "")
        set_stored_layout_hash(mesh, "v1:abc")
        self.assertEqual(get_stored_layout_hash(mesh), "v1:abc")
        self.assertEqual(mesh[ATLAS_LAYOUT_HASH_PROP], "v1:abc")

        uv = read_uv_layer(mesh.uv_layers.new("UVMap"), 4)
        self.assertEqual(len(uv), 8)


class TestAtlasLayoutHash(unittest.TestCase):
    def test_stable_across_mapping_order(self):
        first = _mapping()
        second = _mapping()
        second["sprites"] = dict(reversed(list(second["sprites"].items())))
        second["chunks"] = list(reversed(second["chunks"]))
        self.assertEqual(
            compute_atlas_layout_hash(first),
            compute_atlas_layout_hash(second),
        )

    def test_uv_bounds_change_changes_hash(self):
        base = _mapping()
        changed = _mapping()
        changed["sprites"]["minecraft:block/stone"]["uv_bounds"] = [0.5, 0.5, 0.75, 0.75]
        self.assertNotEqual(
            compute_atlas_layout_hash(base),
            compute_atlas_layout_hash(changed),
        )

    def test_pixel_only_change_keeps_hash(self):
        base = _mapping()
        changed = _mapping()
        # Pixel rects are not part of the UV layout contract.
        changed["sprites"]["minecraft:block/stone"]["pixel_rect"] = [32, 32, 16, 16]
        self.assertEqual(
            compute_atlas_layout_hash(base),
            compute_atlas_layout_hash(changed),
        )

    def test_added_sprite_changes_hash(self):
        base = _mapping()
        changed = _mapping()
        changed["sprites"]["minecraft:block/dirt"] = dict(changed["sprites"]["minecraft:block/stone"])
        changed["sprites"]["minecraft:block/dirt"]["texture_id"] = 2
        changed["sprites"]["minecraft:block/dirt"]["uv_bounds"] = [0.25, 0.0, 0.5, 0.25]
        self.assertNotEqual(
            compute_atlas_layout_hash(base),
            compute_atlas_layout_hash(changed),
        )

    def test_empty_mapping(self):
        self.assertEqual(compute_atlas_layout_hash(None), "")
        self.assertTrue(compute_atlas_layout_hash({}).startswith("v1:"))


if __name__ == "__main__":
    unittest.main()
