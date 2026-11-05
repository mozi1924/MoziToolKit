"""
Unit tests for MTK mesh attribute sanitization and obsolete attribute cleanup.
"""

from __future__ import annotations

import unittest

import bpy

from MoziToolKit.bridge.mesh.attribute_schema import (
    ACTIVE_ATTRIBUTE_NAMES,
    ATTR_ANIM_FRAME_SIZE,
    ATTR_ANIM_TIMING,
    ATTR_BLOCK_X,
    ATTR_BLOCK_Y,
    ATTR_BLOCK_Z,
    RETIRED_ATTRIBUTE_NAMES,
)
from MoziToolKit.bridge.mesh.attributes import inject_custom_attributes
from MoziToolKit.utils.materials.cleaner import (
    clean_obsolete_mesh_attributes,
    prune_optional_mesh_attributes,
)
from MoziToolKit.utils.materials.constants import (
    ATTR_ATLAS_CHUNK_ID,
    ATTR_BIOME_TINT_COLOR,
    ATTR_UV_TRANSFORM,
)


def _make_real_mesh(face_count=4, name="TestAttrMesh"):
    mesh = bpy.data.meshes.new(name)
    verts = []
    faces = []
    for i in range(face_count):
        base = i * 4
        verts.extend([(float(i), 0.0, 0.0), (float(i + 1), 0.0, 0.0), (float(i + 1), 1.0, 0.0), (float(i), 1.0, 0.0)])
        faces.append((base, base + 1, base + 2, base + 3))
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


class TestMeshAttributeCleanup(unittest.TestCase):
    def test_clean_obsolete_mesh_attributes_removes_excluded(self):
        mesh = _make_real_mesh(face_count=10)
        self.addCleanup(lambda: bpy.data.meshes.remove(mesh) if mesh.name in bpy.data.meshes else None)
        mesh.attributes.new(name=ATTR_ATLAS_CHUNK_ID, type="INT", domain="FACE")
        mesh.attributes.new(name=ATTR_UV_TRANSFORM, type="FLOAT_COLOR", domain="FACE")
        mesh.attributes.new(name=ATTR_BIOME_TINT_COLOR, type="FLOAT_COLOR", domain="FACE")

        # Add obsolete attributes
        for name in (
            "mtk_colormap_uv",
            "mtk_material_slot",
            "mtk_atlas_texture_id",
            "mtk_uv_mode",
            "mtk_face_dir",
            "mtk_emission",
            "mtk_anim_total_frames",
            "mtk_material_props",
        ):
            mesh.attributes.new(name=name, type="FLOAT" if "emission" in name or "uv" in name else "INT", domain="FACE")

        removed = clean_obsolete_mesh_attributes(mesh)

        for name in (
            "mtk_colormap_uv",
            "mtk_material_slot",
            "mtk_atlas_texture_id",
            "mtk_uv_mode",
            "mtk_face_dir",
            "mtk_emission",
            "mtk_anim_total_frames",
            "mtk_material_props",
        ):
            self.assertIn(name, removed)
            self.assertNotIn(name, mesh.attributes)

        # Canonical attributes must NOT be removed
        self.assertIn(ATTR_ATLAS_CHUNK_ID, mesh.attributes)
        self.assertIn(ATTR_UV_TRANSFORM, mesh.attributes)
        self.assertIn(ATTR_BIOME_TINT_COLOR, mesh.attributes)

    def test_clean_obsolete_mesh_attributes_purges_retired_source_texture_key(self):
        mesh = _make_real_mesh(face_count=4)
        self.addCleanup(lambda: bpy.data.meshes.remove(mesh) if mesh.name in bpy.data.meshes else None)
        mesh.attributes.new(name="mtk_source_texture_key", type="STRING", domain="FACE")
        mesh.attributes.new(name="mtk_source_texture_idx", type="INT", domain="FACE")
        mesh["mtk_source_textures"] = ["stone", "dirt"]

        removed = clean_obsolete_mesh_attributes(mesh)
        self.assertIn("mtk_source_texture_key", removed)
        self.assertNotIn("mtk_source_texture_key", mesh.attributes)
        self.assertIn("mtk_source_texture_idx", mesh.attributes)
        self.assertIn("mtk_source_textures", mesh)

    def test_resolve_source_texture_keys_ignores_retired_string(self):
        from MoziToolKit.bridge.mesh.attributes import (
            resolve_source_texture_keys,
            resolve_source_texture_keys_paletted,
        )

        mesh = _make_real_mesh(face_count=3)
        self.addCleanup(lambda: bpy.data.meshes.remove(mesh) if mesh.name in bpy.data.meshes else None)
        mesh.attributes.new(name="mtk_source_texture_key", type="STRING", domain="FACE")

        self.assertEqual(resolve_source_texture_keys(mesh), [])

        pal, idx = resolve_source_texture_keys_paletted(mesh)
        self.assertEqual(pal, [])
        self.assertEqual(list(idx), [])

    def test_inject_custom_attributes_skips_excluded(self):
        from types import SimpleNamespace

        mesh = _make_real_mesh(face_count=4)
        self.addCleanup(lambda: bpy.data.meshes.remove(mesh) if mesh.name in bpy.data.meshes else None)

        mock_mesh_data = SimpleNamespace(
            attribute_names=lambda: [
                "mtk_atlas_chunk_id",
                "mtk_uv_transform",
                "mtk_colormap_uv",
                "mtk_material_slot",
                "mtk_atlas_texture_id",
                "mtk_anim_total_frames",
            ],
            attribute_info=lambda name: {
                "mtk_atlas_chunk_id": ("face", "int32", 4),
                "mtk_uv_transform": ("face", "float4", 4),
                "mtk_colormap_uv": ("face", "float3", 4),
                "mtk_material_slot": ("face", "int32", 4),
                "mtk_atlas_texture_id": ("face", "uint32", 4),
                "mtk_anim_total_frames": ("face", "float", 4),
            }.get(name),
            attribute_memoryview=lambda name: None,
        )

        inject_custom_attributes(mesh, mock_mesh_data)

        # Canonical attributes must be injected
        self.assertIn("mtk_atlas_chunk_id", mesh.attributes)
        self.assertIn("mtk_uv_transform", mesh.attributes)

        # Excluded attributes must NOT be injected
        self.assertNotIn("mtk_colormap_uv", mesh.attributes)
        self.assertNotIn("mtk_material_slot", mesh.attributes)
        self.assertNotIn("mtk_atlas_texture_id", mesh.attributes)
        self.assertNotIn("mtk_anim_total_frames", mesh.attributes)

    def test_prune_optional_attributes_by_context(self):
        mesh = _make_real_mesh(face_count=4)
        self.addCleanup(lambda: bpy.data.meshes.remove(mesh) if mesh.name in bpy.data.meshes else None)
        for name in (
            ATTR_ANIM_TIMING,
            ATTR_ANIM_FRAME_SIZE,
            ATTR_BLOCK_X,
            ATTR_BLOCK_Y,
            ATTR_BLOCK_Z,
        ):
            mesh.attributes.new(name=name, type="FLOAT_VECTOR" if "anim" in name else "INT", domain="FACE")

        removed = prune_optional_mesh_attributes(
            mesh,
            keep_animation=False,
            keep_block_coords=True,
        )
        self.assertIn(ATTR_ANIM_TIMING, removed)
        self.assertIn(ATTR_ANIM_FRAME_SIZE, removed)
        self.assertNotIn(ATTR_BLOCK_X, removed)
        self.assertIn(ATTR_BLOCK_X, mesh.attributes)

        removed = prune_optional_mesh_attributes(
            mesh,
            keep_animation=False,
            keep_block_coords=False,
        )
        self.assertIn(ATTR_BLOCK_X, removed)
        self.assertNotIn(ATTR_BLOCK_X, mesh.attributes)

    def test_active_and_retired_disjoint(self):
        # The native schema must never declare the same attribute as active and retired.
        overlap = ACTIVE_ATTRIBUTE_NAMES.intersection(RETIRED_ATTRIBUTE_NAMES)
        self.assertEqual(len(overlap), 0, f"Overlap between active and retired: {overlap}")


if __name__ == "__main__":
    unittest.main()
