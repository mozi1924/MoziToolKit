"""
Unit tests for Yefira Selection Ingestion (utils.save.selection).
"""

import json
from pathlib import Path
import tempfile
import unittest

from MoziToolKit.utils.save.selection import (
    YEFIRA_SELECTION_FILENAME,
    YefiraSelection,
    load_yefira_selection,
    normalize_dimension,
    resolve_world_directory,
)


class TestYefiraSelection(unittest.TestCase):
    def test_normalize_dimension(self):
        self.assertEqual(normalize_dimension("minecraft:overworld"), "overworld")
        self.assertEqual(normalize_dimension("overworld"), "overworld")
        self.assertEqual(normalize_dimension("minecraft:the_nether"), "the_nether")
        self.assertEqual(normalize_dimension("the_nether"), "the_nether")
        self.assertEqual(normalize_dimension("nether"), "the_nether")
        self.assertEqual(normalize_dimension("minecraft:the_end"), "the_end")
        self.assertEqual(normalize_dimension("the_end"), "the_end")
        self.assertEqual(normalize_dimension(None), "overworld")
        self.assertEqual(normalize_dimension(""), "overworld")
        self.assertEqual(normalize_dimension("custom_dim"), "overworld")

    def test_load_yefira_selection_success(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            json_file = tmp_path / YEFIRA_SELECTION_FILENAME
            content = {
                "pos1": {"x": 50, "y": 128, "z": -10},
                "pos2": {"x": -20, "y": 64, "z": 40},
                "dimension": "minecraft:the_nether",
            }
            json_file.write_text(json.dumps(content), encoding="utf-8")

            sel = load_yefira_selection(tmp_path)
            self.assertIsNotNone(sel)
            self.assertIsInstance(sel, YefiraSelection)
            self.assertEqual(sel.pos1, (50, 128, -10))
            self.assertEqual(sel.pos2, (-20, 64, 40))
            self.assertEqual(sel.min_coord, (-20, 64, -10))
            self.assertEqual(sel.max_coord, (50, 128, 40))
            self.assertEqual(sel.dimension, "the_nether")
            self.assertEqual(sel.raw_dimension, "minecraft:the_nether")
            self.assertEqual(sel.size, (71, 65, 51))
            self.assertEqual(sel.volume, 71 * 65 * 51)

    def test_load_yefira_selection_from_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            json_file = tmp_path / YEFIRA_SELECTION_FILENAME
            content = {
                "pos1": {"x": 0, "y": 0, "z": 0},
                "pos2": {"x": 15, "y": 255, "z": 15},
                "dimension": "minecraft:overworld",
            }
            json_file.write_text(json.dumps(content), encoding="utf-8")

            # Point to a child folder like region/
            region_dir = tmp_path / "region"
            region_dir.mkdir()

            sel = load_yefira_selection(region_dir)
            self.assertIsNotNone(sel)
            self.assertEqual(sel.min_coord, (0, 0, 0))
            self.assertEqual(sel.max_coord, (15, 255, 15))
            self.assertEqual(sel.dimension, "overworld")

    def test_load_yefira_selection_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            sel = load_yefira_selection(Path(tmp_dir))
            self.assertIsNone(sel)

    def test_load_yefira_selection_corrupted_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            json_file = tmp_path / YEFIRA_SELECTION_FILENAME
            json_file.write_text("{broken json...", encoding="utf-8")

            sel = load_yefira_selection(tmp_path)
            self.assertIsNone(sel)

    def test_load_yefira_selection_invalid_structure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            json_file = tmp_path / YEFIRA_SELECTION_FILENAME
            json_file.write_text(json.dumps({"pos1": "invalid"}), encoding="utf-8")

            sel = load_yefira_selection(tmp_path)
            self.assertIsNone(sel)


if __name__ == "__main__":
    unittest.main()
