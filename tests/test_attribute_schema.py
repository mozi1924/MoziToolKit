# -*- coding: utf-8 -*-
"""
Validity and parity tests for the generated mesh attribute schema.

`bridge/mesh/_attribute_schema_generated.py` must mirror
`mtk-core::attributes::{MESH_ATTRIBUTE_SPECS, RETIRED_MESH_ATTRIBUTES}` exactly.
"""

import unittest

from MoziToolKit.bridge.mesh import attribute_schema
from MoziToolKit.bridge.mesh import _attribute_schema_generated as generated


class TestAttributeSchema(unittest.TestCase):
    def test_generated_schema_is_internally_consistent(self):
        self.assertTrue(generated.ATTRIBUTE_SPECS)
        names = [spec[0] for spec in generated.ATTRIBUTE_SPECS]
        self.assertEqual(len(names), len(set(names)), "duplicate active attribute names")

        for name, domain, data_type, role in generated.ATTRIBUTE_SPECS:
            self.assertTrue(name.startswith("mtk_"), name)
            self.assertIn(domain, ("point", "corner", "face", "mesh"))
            self.assertTrue(data_type)
            self.assertIn(role, ("material", "metadata"))
            self.assertNotIn(name, generated.RETIRED_ATTRIBUTE_NAMES)

        self.assertEqual(len(generated.RETIRED_ATTRIBUTE_NAMES), len(set(generated.RETIRED_ATTRIBUTE_NAMES)))

    def test_schema_exposes_expected_active_contract(self):
        self.assertIn("mtk_uv_transform", attribute_schema.ATTRIBUTE_SPECS)
        self.assertIn("mtk_source_texture_idx", attribute_schema.METADATA_ATTRIBUTE_NAMES)
        self.assertIn("mtk_source_textures", attribute_schema.METADATA_ATTRIBUTE_NAMES)
        self.assertIn("mtk_biome_tint_color", attribute_schema.MATERIAL_ATTRIBUTE_NAMES)
        self.assertIn("mtk_colormap_uv", attribute_schema.RETIRED_ATTRIBUTE_NAMES)
        self.assertIn("mtk_face_dir", attribute_schema.RETIRED_ATTRIBUTE_NAMES)
        self.assertIn("mtk_source_texture_key", attribute_schema.RETIRED_ATTRIBUTE_NAMES)

    def test_attribute_constants_cover_every_active_name(self):
        for name in attribute_schema.ACTIVE_ATTRIBUTE_NAMES:
            constant_name = "ATTR_" + name[len("mtk_"):].upper()
            self.assertEqual(getattr(attribute_schema, constant_name), name)

    def test_mirror_matches_live_native_schema(self):
        from MoziToolKit.bridge.engine import get_libmtk

        mtk = get_libmtk()
        if mtk is None:
            self.skipTest("libmtk_py is not available")
        if not hasattr(mtk, "mesh_attribute_schema") or not hasattr(mtk, "retired_mesh_attributes"):
            self.fail(
                "libmtk_py does not expose the attribute schema; rebuild it with "
                "'cargo build-py' (the addon mirror is generated from it)"
            )

        live_specs = tuple(tuple(item) for item in mtk.mesh_attribute_schema())
        self.assertEqual(
            live_specs,
            generated.ATTRIBUTE_SPECS,
            "Generated attribute schema is stale; run 'python tools/sync_attribute_schema.py'",
        )
        self.assertEqual(
            frozenset(mtk.retired_mesh_attributes()),
            generated.RETIRED_ATTRIBUTE_NAMES,
            "Generated retired-attribute list is stale; run 'python tools/sync_attribute_schema.py'",
        )


if __name__ == "__main__":
    unittest.main()
