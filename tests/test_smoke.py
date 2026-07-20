"""Smoke tests for the lazygimp package — stdlib only, no network, no root,
no Tk required (the GUI module must import cleanly even headless)."""

import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class ImportTests(unittest.TestCase):
    def test_every_module_imports(self):
        import importlib

        for mod in ("constants", "gimpsam_dep", "models", "hardware", "distro",
                    "gimp_detect", "job", "plan", "gimp_install", "photogimp",
                    "plugins", "sam_backend", "sam3", "util", "compat", "cli", "gui"):
            importlib.import_module(f"lazygimp.{mod}")

    def test_gui_is_optional(self):
        """gui must import (not crash) even when Tk is unavailable."""
        from lazygimp import compat, gui  # noqa: F401
        self.assertIsInstance(compat._TK_OK, bool)


class ModelRegistryTests(unittest.TestCase):
    def test_registry_is_consistent(self):
        from lazygimp.models import MODEL_BY_KEY, MODEL_REGISTRY

        self.assertGreater(len(MODEL_REGISTRY), 0)
        self.assertEqual(len(MODEL_BY_KEY), len(MODEL_REGISTRY))
        for spec in MODEL_REGISTRY:
            self.assertTrue(spec.key)
            self.assertIs(MODEL_BY_KEY[spec.key], spec)

    def test_recommended_model_exists(self):
        from lazygimp.hardware import detect_hardware, recommended_model_key
        from lazygimp.models import MODEL_BY_KEY

        self.assertIn(recommended_model_key(detect_hardware()), MODEL_BY_KEY)


class GimpsamDepTests(unittest.TestCase):
    def test_backend_dir_agrees_with_gimpsam(self):
        """Both packages must point at the same on-disk backend, or an
        upgrade would orphan already-downloaded multi-GB models."""
        from lazygimp.constants import BACKEND_DIR
        from lazygimp.gimpsam_dep import load

        self.assertEqual(BACKEND_DIR, load().constants.BACKEND_DIR)

    def test_shims_reexport_gimpsam_objects(self):
        from lazygimp import models
        from lazygimp.gimpsam_dep import load

        self.assertIs(models.MODEL_REGISTRY, load().models.MODEL_REGISTRY)


class CliTests(unittest.TestCase):
    def test_arg_parser_builds(self):
        from lazygimp.cli import build_arg_parser

        parser = build_arg_parser()
        with self.assertRaises(SystemExit) as ctx, \
                contextlib.redirect_stdout(io.StringIO()):
            parser.parse_args(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_launcher_and_module_entrypoints(self):
        for cmd in ([sys.executable, str(ROOT / "installer.py"), "--help"],
                    [sys.executable, "-m", "lazygimp", "--help"]):
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("PhotoGIMP", proc.stdout)

    def test_status_runs_headless(self):
        proc = subprocess.run(
            [sys.executable, "-m", "lazygimp", "status"],
            capture_output=True, text=True, cwd=ROOT,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("PhotoGIMP", proc.stdout)


if __name__ == "__main__":
    unittest.main()
