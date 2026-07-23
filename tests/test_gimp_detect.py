"""Unit tests for lazygimp.gimp_detect module."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from lazygimp.gimp_detect import (
    find_gimp_binary,
    find_gimp_command,
    gimp_version_dirs,
)


class GimpDetectTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="lazygimp_test_detect_")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_find_gimp_command_native(self):
        with patch("lazygimp.gimp_detect.find_gimp_binary", return_value="/usr/bin/gimp"):
            cmd = find_gimp_command()
            self.assertEqual(cmd, ["/usr/bin/gimp"])

    def test_find_gimp_command_flatpak_fallback(self):
        with patch("lazygimp.gimp_detect.find_gimp_binary", return_value=None), \
             patch("lazygimp.gimp_detect.flatpak_gimp_installed", return_value=True):
            cmd = find_gimp_command()
            self.assertEqual(cmd, ["flatpak", "run", "org.gimp.GIMP"])

    def test_find_gimp_command_none(self):
        with patch("lazygimp.gimp_detect.find_gimp_binary", return_value=None), \
             patch("lazygimp.gimp_detect.flatpak_gimp_installed", return_value=False):
            self.assertIsNone(find_gimp_command())

    def test_find_gimp_binary_windows_program_files(self):
        fake_pf = os.path.join(self.tmp_dir, "ProgramFiles")
        fake_gimp = os.path.join(fake_pf, "GIMP 3", "bin", "gimp-3.0.exe")
        os.makedirs(os.path.dirname(fake_gimp), exist_ok=True)
        with open(fake_gimp, "w") as fh:
            fh.write("binary")

        import lazygimp.gimp_detect as gimp_detect_mod
        with patch("shutil.which", return_value=None), \
             patch.object(gimp_detect_mod.sys, "platform", "win32"), \
             patch.dict(os.environ, {"ProgramFiles": fake_pf}):
            binary = find_gimp_binary()
            self.assertEqual(binary, fake_gimp)

    def test_gimp_version_dirs_sorting(self):
        base_dir = os.path.join(self.tmp_dir, "GIMP")
        os.makedirs(os.path.join(base_dir, "2.10"), exist_ok=True)
        os.makedirs(os.path.join(base_dir, "3.0"), exist_ok=True)
        os.makedirs(os.path.join(base_dir, "3.2"), exist_ok=True)

        with patch("lazygimp.gimp_detect.gimp_config_base", return_value=base_dir):
            dirs = gimp_version_dirs()
            dir_names = [os.path.basename(d) for d in dirs]
            self.assertIn("2.10", dir_names)
            self.assertIn("3.0", dir_names)
            self.assertIn("3.2", dir_names)
            self.assertEqual(dir_names.index("2.10") < dir_names.index("3.0") < dir_names.index("3.2"), True)


if __name__ == "__main__":
    unittest.main()
