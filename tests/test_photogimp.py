"""Unit tests for lazygimp.photogimp module."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from lazygimp.job import Job
from lazygimp.photogimp import (
    PHOTOGIMP_MANIFEST,
    _photogimp_apply,
    photogimp_installed,
    repair_desktop_integration,
)


class PhotoGimpTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="lazygimp_test_photogimp_")
        self.job = Job()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_photogimp_apply_sanitizes_sessionrc(self):
        payload_dir = os.path.join(self.tmp_dir, "payload")
        target_dir = os.path.join(self.tmp_dir, "target")
        os.makedirs(payload_dir, exist_ok=True)

        sessionrc_content = (
            "(sessionrc-version 1)\n"
            "  (monitor 1)\n"
            "  (hide-docks yes)\n"
            "  (single-window-mode yes)\n"
        )
        sessionrc_path = os.path.join(payload_dir, "sessionrc")
        with open(sessionrc_path, "w", encoding="utf-8") as fh:
            fh.write(sessionrc_content)

        count = _photogimp_apply(payload_dir, target_dir, self.job)
        self.assertEqual(count, 1)

        manifest_path = os.path.join(target_dir, PHOTOGIMP_MANIFEST)
        self.assertTrue(os.path.isfile(manifest_path))

        target_sessionrc = os.path.join(target_dir, "sessionrc")
        self.assertTrue(os.path.isfile(target_sessionrc))

        with open(target_sessionrc, encoding="utf-8") as fh:
            result_lines = fh.read()

        self.assertNotIn("monitor", result_lines)
        self.assertNotIn("hide-docks", result_lines)
        self.assertIn("single-window-mode yes", result_lines)

    def test_photogimp_installed_detection(self):
        target_dir = os.path.join(self.tmp_dir, "3.0")
        os.makedirs(target_dir, exist_ok=True)

        with patch("lazygimp.photogimp.gimp_version_dirs", return_value=[target_dir]):
            self.assertFalse(photogimp_installed())
            manifest_path = os.path.join(target_dir, PHOTOGIMP_MANIFEST)
            with open(manifest_path, "w", encoding="utf-8") as fh:
                fh.write("sessionrc\n")
            self.assertTrue(photogimp_installed())

    def test_repair_desktop_integration_repairs_broken_exec(self):
        apps_dir = os.path.join(self.tmp_dir, "applications")
        os.makedirs(apps_dir, exist_ok=True)

        real_desktop = os.path.join(apps_dir, "org.gimp.GIMP.desktop")
        real_content = (
            "[Desktop Entry]\n"
            "Name=PhotoGIMP\n"
            "Icon=photogimp\n"
            "Exec=flatpak %U\n"
            "StartupWMClass=gimp-3.0\n"
        )
        with open(real_desktop, "w", encoding="utf-8") as fh:
            fh.write(real_content)

        with patch("lazygimp.photogimp.XDG_DATA_HOME", self.tmp_dir), \
             patch("lazygimp.photogimp.find_gimp_command", return_value=["/usr/bin/gimp"]), \
             patch("sys.platform", "linux"):
            res = repair_desktop_integration(self.job)
            self.assertTrue(res)

            with open(real_desktop, encoding="utf-8") as fh:
                updated_real = fh.read()
            self.assertIn("Exec=/usr/bin/gimp %U", updated_real)

            shadow_desktop = os.path.join(apps_dir, "gimp.desktop")
            self.assertTrue(os.path.isfile(shadow_desktop))
            with open(shadow_desktop, encoding="utf-8") as fh:
                updated_shadow = fh.read()
            self.assertIn("Exec=/usr/bin/gimp %U", updated_shadow)
            self.assertIn("NoDisplay=true", updated_shadow)


if __name__ == "__main__":
    unittest.main()
