"""Unit tests for material-slot chunk-id fallback and pruning helpers."""

from __future__ import annotations

import numpy as np

from MoziToolKit.utils.materials.builder.world_binding import (
    face_chunk_ids,
    prune_internal_chunk_attribute,
)


class _Elem:
    def __init__(self, value):
        self.value = value


class _AttrData(list):
    def foreach_get(self, key, out):
        for i, elem in enumerate(self):
            out[i] = getattr(elem, key)


class _Attr:
    def __init__(self, values):
        self.data = _AttrData(_Elem(v) for v in values)

    def __len__(self):
        return len(self.data)


class _Attributes(dict):
    def get(self, name, default=None):
        return super().get(name, default)

    def remove(self, attr):
        for name, value in list(self.items()):
            if value is attr:
                del self[name]
                return


class _Polygons(list):
    def foreach_get(self, key, out):
        for i, poly in enumerate(self):
            out[i] = getattr(poly, key)


class _Poly:
    def __init__(self, material_index):
        self.material_index = material_index


class _Mat:
    def __init__(self, chunk_id=None):
        self._chunk = chunk_id

    def get(self, key, default=None):
        if key == "mtk_atlas_chunk_id":
            return self._chunk
        return default


class _Mesh:
    def __init__(self, material_indices, materials, chunk_ids=None):
        self.polygons = _Polygons(_Poly(i) for i in material_indices)
        self.materials = [_Mat(c) for c in materials]
        self.attributes = _Attributes()
        if chunk_ids is not None:
            self.attributes["mtk_atlas_chunk_id"] = _Attr(chunk_ids)


def test_face_chunk_ids_prefers_attribute():
    mesh = _Mesh([0, 1, 0], [5, 7], chunk_ids=[9, 9, 9])
    assert list(face_chunk_ids(mesh)) == [9, 9, 9]


def test_face_chunk_ids_falls_back_to_material_slots():
    mesh = _Mesh([0, 1, 0], [5, 7])
    assert list(face_chunk_ids(mesh)) == [5, 7, 5]


def test_prune_only_when_every_slot_has_chunk_id():
    mesh = _Mesh([0, 1], [5, None], chunk_ids=[5, 0])
    assert prune_internal_chunk_attribute(mesh) is False
    assert "mtk_atlas_chunk_id" in mesh.attributes

    mesh = _Mesh([0, 1], [5, 7], chunk_ids=[5, 7])
    assert prune_internal_chunk_attribute(mesh) is True
    assert "mtk_atlas_chunk_id" not in mesh.attributes


def test_face_chunk_ids_after_prune_is_stable():
    mesh = _Mesh([0, 0, 1], [5, 7], chunk_ids=[5, 5, 7])
    before = list(face_chunk_ids(mesh))
    assert prune_internal_chunk_attribute(mesh)
    assert list(face_chunk_ids(mesh)) == before
