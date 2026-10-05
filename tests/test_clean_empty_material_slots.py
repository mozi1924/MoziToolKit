"""
Unit tests for cleaning empty and unused material slots on Blender mesh objects.
"""

import unittest
from pathlib import Path
try:
    import numpy as np
except ImportError:
    np = None

try:
    from unittest.mock import MagicMock
    import bpy
    HAS_BPY = (
        bpy is not None
        and not isinstance(bpy, MagicMock)
        and hasattr(bpy, "data")
        and hasattr(bpy.data, "meshes")
        and not isinstance(bpy.data, MagicMock)
        and hasattr(bpy, "app")
        and hasattr(bpy.app, "version")
    )
except ImportError:
    bpy = None
    HAS_BPY = False



from utils.materials.cleaner import (
    compact_mesh_material_slots,
    clean_object_material_slots,
    clean_scene_material_slots,
)


class TestCleanEmptyMaterialSlots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAS_BPY:
            raise unittest.SkipTest("bpy is required for material slot cleaner tests")

    def setUp(self):
        # Create unique mesh & object for each test
        self.mesh = bpy.data.meshes.new("TestCleanMesh")
        verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0), (2.0, 0.0, 0.0), (2.0, 1.0, 0.0)]
        faces = [(0, 1, 2, 3), (1, 4, 5, 2)]
        self.mesh.from_pydata(verts, [], faces)
        self.mesh.update()

        self.obj = bpy.data.objects.new("TestCleanObj", self.mesh)
        bpy.context.scene.collection.objects.link(self.obj)


    def tearDown(self):
        if self.obj:
            bpy.data.objects.remove(self.obj)
        if self.mesh:
            bpy.data.meshes.remove(self.mesh)

    def test_clean_empty_none_slots(self):
        """Verify that None/empty slots are removed and polygon indices remapped correctly."""
        mat_a = bpy.data.materials.new("Mat_A")
        mat_b = bpy.data.materials.new("Mat_B")

        # Slots: [None, Mat_A, None, Mat_B, None]
        self.mesh.materials.append(None)
        self.mesh.materials.append(mat_a)
        self.mesh.materials.append(None)
        self.mesh.materials.append(mat_b)
        self.mesh.materials.append(None)

        # Polygon 0 -> Slot 1 (Mat_A), Polygon 1 -> Slot 3 (Mat_B)
        self.mesh.polygons[0].material_index = 1
        self.mesh.polygons[1].material_index = 3

        self.assertEqual(len(self.obj.material_slots), 5)

        res = clean_object_material_slots(self.obj, remove_unused=False)

        self.assertTrue(res["success"])
        self.assertEqual(res["removed_slots"], 3)
        self.assertEqual(res["remaining_slots"], 2)
        self.assertEqual(len(self.mesh.materials), 2)
        self.assertEqual(self.mesh.materials[0], mat_a)
        self.assertEqual(self.mesh.materials[1], mat_b)

        # Polygons must now point to slots 0 and 1
        self.assertEqual(self.mesh.polygons[0].material_index, 0)
        self.assertEqual(self.mesh.polygons[1].material_index, 1)

        # Cleanup test materials
        bpy.data.materials.remove(mat_a)
        bpy.data.materials.remove(mat_b)

    def test_clean_unused_slots_when_requested(self):
        """Verify that slots with materials not used by any polygon are removed if remove_unused=True."""
        mat_used = bpy.data.materials.new("Mat_Used")
        mat_unused = bpy.data.materials.new("Mat_Unused")

        self.mesh.materials.append(mat_unused)  # Slot 0
        self.mesh.materials.append(mat_used)    # Slot 1

        # Both polygons use Slot 1
        self.mesh.polygons[0].material_index = 1
        self.mesh.polygons[1].material_index = 1

        # Without remove_unused: keep both
        res_no_unused = clean_object_material_slots(self.obj, remove_unused=False)
        self.assertEqual(res_no_unused["removed_slots"], 0)
        self.assertEqual(len(self.mesh.materials), 2)

        # With remove_unused=True: remove slot 0
        res_unused = clean_object_material_slots(self.obj, remove_unused=True)
        self.assertEqual(res_unused["removed_slots"], 1)
        self.assertEqual(len(self.mesh.materials), 1)
        self.assertEqual(self.mesh.materials[0], mat_used)
        self.assertEqual(self.mesh.polygons[0].material_index, 0)
        self.assertEqual(self.mesh.polygons[1].material_index, 0)

        bpy.data.materials.remove(mat_used)
        bpy.data.materials.remove(mat_unused)

    def test_scene_batch_cleaning(self):
        """Verify clean_scene_material_slots processes all mesh objects."""
        mat = bpy.data.materials.new("BatchMat")
        self.mesh.materials.append(None)
        self.mesh.materials.append(mat)
        self.mesh.polygons[0].material_index = 1
        self.mesh.polygons[1].material_index = 1

        res = clean_scene_material_slots(scene=bpy.context.scene, selected_only=False, remove_unused=False)
        self.assertTrue(res["success"])
        self.assertGreaterEqual(res["cleaned_objects"], 1)
        self.assertGreaterEqual(res["total_removed_slots"], 1)
        self.assertEqual(len(self.mesh.materials), 1)
        self.assertEqual(self.mesh.materials[0], mat)

        bpy.data.materials.remove(mat)


if __name__ == "__main__":
    unittest.main()
