"""
Unit tests for MoziToolKit Native Status Bar Progress Bar and Progress Manager.
"""

from __future__ import annotations

import unittest
import bpy
from pipeline.progress import (
    ProgressUpdate,
    ProgressBar,
    draw_statusbar_progress,
    register_progress_header,
    unregister_progress_header,
)


class TestStatusBarProgress(unittest.TestCase):
    """Test suite covering the native status bar ProgressBar manager."""

    def setUp(self):
        ProgressBar.end()
        register_progress_header()

    def tearDown(self):
        ProgressBar.end()

    def test_progress_update_fraction_normalization(self):
        update = ProgressUpdate(current=25, total=100, message="Loading")
        self.assertEqual(update.fraction, 0.25)
        self.assertEqual(update.message, "Loading")

        # Zero or negative total safeguard
        update_zero = ProgressUpdate(current=10, total=0)
        self.assertEqual(update_zero.fraction, 0.0)

        # Clamping above 1.0 or below 0.0
        update_overflow = ProgressUpdate(current=150, total=100)
        self.assertEqual(update_overflow.fraction, 1.0)
        update_underflow = ProgressUpdate(current=-10, total=100)
        self.assertEqual(update_underflow.fraction, 0.0)

    def test_progress_bar_lifecycle(self):
        self.assertFalse(ProgressBar.is_active())

        # 1. Begin
        ProgressBar.begin(title="Live Sync", total=50.0, message="Connecting...")
        self.assertTrue(ProgressBar.is_active())
        self.assertEqual(ProgressBar.get_fraction(), 0.0)
        self.assertIn("Live Sync: Connecting... (0%)", ProgressBar.get_display_text())

        # 2. Update
        ProgressBar.update(current=25.0, message="Loading chunks")
        self.assertTrue(ProgressBar.is_active())
        self.assertAlmostEqual(ProgressBar.get_fraction(), 0.5)
        self.assertIn("Live Sync: Loading chunks (50%)", ProgressBar.get_display_text())

        # 3. Step
        ProgressBar.step(delta=10.0, message="More chunks")
        self.assertAlmostEqual(ProgressBar.get_fraction(), 0.7)
        self.assertIn("Live Sync: More chunks (70%)", ProgressBar.get_display_text())

        # 4. Finish
        ProgressBar.finish(message="Ready", auto_dismiss_delay=0.0)
        self.assertFalse(ProgressBar.is_active())

    def test_progress_bar_cancel(self):
        ProgressBar.begin(title="Pipeline", total=100.0, message="Working")
        self.assertTrue(ProgressBar.is_active())
        ProgressBar.cancel(message="Cancelled by user")
        self.assertFalse(ProgressBar.is_active())

    def test_draw_statusbar_progress_execution(self):
        """Verify that draw_statusbar_progress executes cleanly without crashing."""
        class DummyLayout:
            def __init__(self):
                self.rendered_items = []

            def row(self, align=True):
                return self

            def progress(self, factor=0.0, text="", type="BAR"):
                self.rendered_items.append((factor, text, type))

        class DummyHeader:
            def __init__(self):
                self.layout = DummyLayout()

        header = DummyHeader()

        # Inactive state: should render nothing
        ProgressBar.end()
        draw_statusbar_progress(header, None)
        self.assertEqual(len(header.layout.rendered_items), 0)

        # Active state: should render native progress bar
        ProgressBar.begin(title="Atlas Generator", total=10.0, message="Baking textures")
        ProgressBar.update(current=5.0)
        draw_statusbar_progress(header, None)
        self.assertEqual(len(header.layout.rendered_items), 1)
        factor, text, bar_type = header.layout.rendered_items[0]
        self.assertAlmostEqual(factor, 0.5)
        self.assertEqual(bar_type, "BAR")
        self.assertIn("50%", text)

        ProgressBar.end()


if __name__ == '__main__':
    unittest.main()
