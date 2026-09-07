"""
Unit tests for Forge/NeoForge Composite and Separate-Transforms model loader support in ModelParser and StateBaker.
"""

from __future__ import annotations

import unittest
from typing import Any

from utils.mc_baker.model_parser import ModelParser
from utils.mc_baker.state_baker import StateBaker
from utils.mc_baker.blockstate_resolver import BlockStateResolver, VariantMatch


class TestCompositeLoader(unittest.TestCase):

    def setUp(self):
        self.parser = ModelParser()

        # Register standard submodels for testing
        self.parser.register_model("create:block/gearbox_casing", {
            "textures": {
                "casing": "create:block/brass_casing",
                "particle": "#casing",
            },
            "elements": [
                {
                    "from": [0, 0, 0],
                    "to": [16, 16, 16],
                    "faces": {
                        "up": {"texture": "#casing", "cullface": "up"},
                        "down": {"texture": "#casing", "cullface": "down"},
                        "north": {"texture": "#casing", "cullface": "north"},
                        "south": {"texture": "#casing", "cullface": "south"},
                        "west": {"texture": "#casing", "cullface": "west"},
                        "east": {"texture": "#casing", "cullface": "east"},
                    },
                }
            ]
        })

        self.parser.register_model("create:block/gearbox_shaft", {
            "textures": {
                "shaft": "create:block/axis",
            },
            "elements": [
                {
                    "from": [6, 6, 0],
                    "to": [10, 10, 16],
                    "faces": {
                        "north": {"texture": "#shaft"},
                        "south": {"texture": "#shaft"},
                        "west": {"texture": "#shaft"},
                        "east": {"texture": "#shaft"},
                    },
                }
            ]
        })

        self.parser.register_model("create:block/gearbox_gear", {
            "textures": {
                "gear": "create:block/gear",
            },
            "elements": [
                {
                    "from": [4, 4, 7],
                    "to": [12, 12, 9],
                    "faces": {
                        "north": {"texture": "#gear"},
                        "south": {"texture": "#gear"},
                    },
                }
            ]
        })

    def test_basic_composite_model_merging(self):
        """Test standard forge:composite combining casing and shaft."""
        self.parser.register_model("create:block/gearbox", {
            "loader": "forge:composite",
            "children": {
                "casing": {"parent": "create:block/gearbox_casing"},
                "shaft": {"parent": "create:block/gearbox_shaft"},
            }
        })

        res = self.parser.resolve_model("create:block/gearbox")
        self.assertEqual(res["model_id"], "create:block/gearbox")
        self.assertEqual(len(res["elements"]), 2)
        self.assertEqual(res["elements"][0]["from"], [0, 0, 0])
        self.assertEqual(res["elements"][1]["from"], [6, 6, 0])
        self.assertIn("casing", res["textures"])
        self.assertIn("shaft", res["textures"])
        self.assertEqual(res["textures"]["casing"], "create:block/brass_casing")
        self.assertEqual(res["textures"]["shaft"], "create:block/axis")

    def test_composite_visibility_and_ordering(self):
        """Test visibility filtering and ordering via parts."""
        self.parser.register_model("create:block/composite_ordered", {
            "loader": "neoforge:composite",
            "children": {
                "gear": {"parent": "create:block/gearbox_gear"},
                "casing": {"parent": "create:block/gearbox_casing"},
                "shaft": {"parent": "create:block/gearbox_shaft"},
            },
            "parts": ["casing", "gear", "shaft"],
            "visibility": {
                "shaft": False,
                "gear": True,
            }
        })

        res = self.parser.resolve_model("create:block/composite_ordered")
        # shaft is hidden, so only casing and gear appear
        self.assertEqual(len(res["elements"]), 2)
        # Verify ordering respects parts: casing first, gear second
        self.assertEqual(res["elements"][0]["from"], [0, 0, 0])  # casing
        self.assertEqual(res["elements"][1]["from"], [4, 4, 7])  # gear

    def test_composite_parent_visibility_override(self):
        """Test child model overriding parent composite model's visibility."""
        # Parent composite: shaft disabled by default
        self.parser.register_model("create:block/gearbox_base", {
            "loader": "forge:composite",
            "children": {
                "casing": {"parent": "create:block/gearbox_casing"},
                "shaft": {"parent": "create:block/gearbox_shaft"},
            },
            "visibility": {
                "shaft": False,
            }
        })

        # Child model enables shaft
        self.parser.register_model("create:block/gearbox_with_shaft", {
            "parent": "create:block/gearbox_base",
            "visibility": {
                "shaft": True,
            }
        })

        res_base = self.parser.resolve_model("create:block/gearbox_base")
        self.assertEqual(len(res_base["elements"]), 1)
        self.assertEqual(res_base["elements"][0]["from"], [0, 0, 0])

        res_active = self.parser.resolve_model("create:block/gearbox_with_shaft")
        self.assertEqual(len(res_active["elements"]), 2)

    def test_composite_texture_variable_passthrough(self):
        """Test root composite model injecting textures into child models."""
        self.parser.register_model("create:block/generic_frame", {
            "textures": {
                "frame": "#frame_material",
            },
            "elements": [
                {
                    "from": [0, 0, 0],
                    "to": [16, 2, 16],
                    "faces": {
                        "up": {"texture": "#frame"},
                    }
                }
            ]
        })

        self.parser.register_model("create:block/copper_frame_machine", {
            "loader": "forge:composite",
            "textures": {
                "frame_material": "create:block/copper_casing",
                "particle": "create:block/copper_casing",
            },
            "children": {
                "frame": {"parent": "create:block/generic_frame"}
            }
        })

        res = self.parser.resolve_model("create:block/copper_frame_machine")
        self.assertEqual(len(res["elements"]), 1)
        up_face = res["elements"][0]["faces"]["up"]
        self.assertEqual(up_face["texture"], "create:block/copper_casing")

    def test_composite_mixed_json_and_obj(self):
        """Test composite model combining a standard JSON element and an OBJ submodel."""
        obj_text = (
            "v 0.0 0.0 0.0\n"
            "v 1.0 0.0 0.0\n"
            "v 1.0 1.0 0.0\n"
            "v 0.0 1.0 0.0\n"
            "vt 0.0 0.0\n"
            "vt 1.0 0.0\n"
            "vt 1.0 1.0\n"
            "vt 0.0 1.0\n"
            "usemtl [0]create:block/metal_cog\n"
            "f 1/1 2/2 3/3 4/4\n"
        )

        self.parser.register_model("create:block/cog.obj", {
            "_is_obj": True,
            "_raw_obj": obj_text,
        })

        self.parser.register_model("create:block/hybrid_machine", {
            "loader": "forge:composite",
            "children": {
                "casing": {"parent": "create:block/gearbox_casing"},
                "cog": {
                    "loader": "forge:obj",
                    "model": "create:block/cog.obj",
                }
            }
        })

        res = self.parser.resolve_model("create:block/hybrid_machine")
        self.assertEqual(len(res["elements"]), 2)
        # First element is json cuboid
        self.assertEqual(res["elements"][0]["from"], [0, 0, 0])
        # Second element is obj mesh
        self.assertTrue(res["elements"][1].get("_is_obj_element"))

        # End-to-end baking test with StateBaker
        resolver = BlockStateResolver()
        resolver.register_blockstate("create:hybrid_machine", {
            "variants": {
                "": {"model": "create:block/hybrid_machine", "y": 90}
            }
        })
        state_baker = StateBaker(state_resolver=resolver, model_parser=self.parser)
        baked = state_baker.bake_block_state("create:hybrid_machine")
        self.assertIsNotNone(baked)
        self.assertEqual(len(baked.elements), 2)
        # Verify OBJ faces survived variant rotation intact
        obj_baked_elem = baked.elements[1]
        self.assertIn("south", obj_baked_elem.faces)
        south_face = obj_baked_elem.faces["south"]
        self.assertEqual(south_face.texture, "create:block/metal_cog")

    def test_separate_transforms_loader(self):
        """Test forge:separate-transforms resolves base model geometry."""
        self.parser.register_model("create:block/separate_model", {
            "loader": "forge:separate-transforms",
            "base": {
                "parent": "create:block/gearbox_casing",
            },
            "perspectives": {
                "gui": {"rotation": [30, 45, 0]},
            }
        })

        res = self.parser.resolve_model("create:block/separate_model")
        self.assertEqual(res["model_id"], "create:block/separate_model")
        self.assertEqual(len(res["elements"]), 1)
        self.assertEqual(res["elements"][0]["from"], [0, 0, 0])
        self.assertEqual(res["textures"]["casing"], "create:block/brass_casing")

    def test_nested_composite_and_shorthand_references(self):
        """Test nested composite models and string child shorthand."""
        # Child 1: shorthand string reference
        # Child 2: inline nested composite
        self.parser.register_model("create:block/super_composite", {
            "loader": "forge:composite",
            "children": {
                "direct_casing": "create:block/gearbox_casing",
                "nested_part": {
                    "loader": "forge:composite",
                    "children": {
                        "sub_shaft": "create:block/gearbox_shaft",
                        "sub_gear": "create:block/gearbox_gear",
                    }
                }
            }
        })

        res = self.parser.resolve_model("create:block/super_composite")
        self.assertEqual(res["model_id"], "create:block/super_composite")
        # 1 from direct_casing + 1 from sub_shaft + 1 from sub_gear = 3 elements
        self.assertEqual(len(res["elements"]), 3)
        self.assertIn("casing", res["textures"])
        self.assertIn("shaft", res["textures"])
        self.assertIn("gear", res["textures"])


if __name__ == "__main__":
    unittest.main()
