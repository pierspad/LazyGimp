"""Top-level integration smoke test for the PySide6 GUI: builds the full
``lazygimp.gui_qt.app.LazyGimpApp`` (landing + uninstall + wizard +
install-progress mixins composed together, exactly as ``installer.py
--qt`` does it) under ``QT_QPA_PLATFORM=offscreen`` and walks it through
several screens, confirming the pieces built/smoke-tested independently
in earlier phases (each page module has its own
``pages/_smoke_test_*.py`` with a stubbed-out host) actually compose
correctly once real app.py plumbing (status bar, background-job runner,
global keyboard shortcuts, log pump) sits underneath all four of them at
once.

Skips itself (not a failure) if PySide6 isn't installed — this file is
picked up by the same ``python -m unittest discover -s tests`` the rest
of the suite uses, which must keep passing on boxes without PySide6,
the same way the CustomTkinter GUI's ``tests/gui_smoke.py`` is Tk-only
and run explicitly (not part of the default discover). See
``.github/workflows/ci.yml``'s ``qt-gui-smoke`` job for where this
actually runs for real, with PySide6 installed and
``QT_QPA_PLATFORM=offscreen`` set.
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PySide6  # noqa: F401
    _PYSIDE6_OK = True
except ImportError:
    _PYSIDE6_OK = False


@unittest.skipUnless(_PYSIDE6_OK, "PySide6 not installed — see requirements-qt.txt")
class QtAppIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qapp = QApplication.instance() or QApplication(sys.argv)

    def _build_app(self):
        from PySide6.QtWidgets import QMainWindow

        from lazygimp.gui_qt import theme
        from lazygimp.gui_qt.app import LazyGimpApp

        self.qapp.setStyleSheet(theme.build_stylesheet())
        window = QMainWindow()
        app = LazyGimpApp(window)
        window.show()
        self.qapp.processEvents()
        return window, app

    def test_full_walk_landing_wizard_back_uninstall(self):
        window, app = self._build_app()
        self.addCleanup(window.close)

        # -- landing ----------------------------------------------------
        self.assertEqual(app.current_screen, "landing")
        self.assertIsNotNone(app.root_frame.layout())
        self.assertGreaterEqual(app.root_frame.layout().count(), 1)

        # -- into the wizard, a couple of steps --------------------------
        app.show_wizard()
        self.qapp.processEvents()
        self.assertEqual(app.current_screen, "wizard")
        self.assertTrue(app.wizard_steps, "no wizard steps were built")
        first_key = app.wizard_steps[0].key

        if first_key == "gimp":
            app._wizard_pick_gimp_method("appimage")
            self.qapp.processEvents()
            self.assertEqual(app.wizard_index, 1, "picking a GIMP method should auto-advance")

        self.assertEqual(app.wizard_steps[app.wizard_index].key, "components")
        self.assertIn("photogimp", app._wizard_cards)
        was_queued = app.plan.has("photogimp:install")
        app._wizard_cards["photogimp"]()
        self.assertNotEqual(app.plan.has("photogimp:install"), was_queued)
        app._wizard_cards["photogimp"]()  # toggle back to original state

        app._wizard_advance()
        self.qapp.processEvents()
        self.assertEqual(app.wizard_steps[app.wizard_index].key, "sam")
        self.assertTrue(app._sam_family_cards)
        self.assertIsNotNone(app._pytorch_combo)

        app._wizard_advance()
        self.qapp.processEvents()
        self.assertEqual(app.wizard_steps[app.wizard_index].key, "review")

        # -- back to landing, discarding whatever got queued -------------
        app.plan.clear()
        app._current_wizard_frame = None
        app.show_landing()
        self.qapp.processEvents()
        self.assertEqual(app.current_screen, "landing")
        self.assertGreaterEqual(app.root_frame.layout().count(), 1)

        # -- uninstall screen ---------------------------------------------
        app.show_uninstall_confirm()
        self.qapp.processEvents()
        self.assertEqual(app.current_screen, "uninstall")
        self.assertTrue(hasattr(app, "status_label"),
                         "uninstall screen should have built a status bar")

        # -- back to landing again, once more --------------------------
        app.show_landing()
        self.qapp.processEvents()
        self.assertEqual(app.current_screen, "landing")

    def test_run_in_background_updates_status_bar(self):
        """Exercises the real background-job runner + cross-thread bridge
        + status-bar log pump end to end (not stubbed, unlike the
        per-page smoke tests) — the integration path none of
        pages/*.py's own smoke tests can cover on their own, since none
        of them build a real app.py."""
        window, app = self._build_app()
        self.addCleanup(window.close)

        app.show_uninstall_confirm()  # only screen that builds a status bar
        self.qapp.processEvents()

        done = {"called": False}

        def task(job):
            job.log("hello from a real background thread")

        def on_done():
            done["called"] = True

        app.run_in_background(task, on_done=on_done)

        deadline = time.monotonic() + 5.0
        while not done["called"] and time.monotonic() < deadline:
            self.qapp.processEvents()
            time.sleep(0.01)
        self.assertTrue(done["called"], "run_in_background's on_done never fired")
        self.assertFalse(app.busy)

        deadline = time.monotonic() + 2.0
        while ("hello from a real background thread" not in app.status_label.text()
               and time.monotonic() < deadline):
            self.qapp.processEvents()
            time.sleep(0.01)
        self.assertIn("hello from a real background thread", app.status_label.text())

    def test_busy_guard_rejects_concurrent_background_jobs(self):
        """run_in_background's busy guard normally surfaces a blocking
        themed_info() modal (real QDialog.exec()) when a second job is
        attempted — correct, user-facing behavior, but not something an
        unattended offscreen test can click through. themed_info is
        patched out here (module-local import in gui_qt/app.py) purely
        so this test can observe "second job was rejected, not run"
        without hanging forever waiting for a dialog nobody will close."""
        import lazygimp.gui_qt.app as app_module

        window, app = self._build_app()
        self.addCleanup(window.close)

        busy_dialog_calls = []
        original_themed_info = app_module.themed_info
        app_module.themed_info = lambda *a, **kw: busy_dialog_calls.append((a, kw))
        self.addCleanup(setattr, app_module, "themed_info", original_themed_info)

        release = {"go": False}
        started = {"go": False}

        def slow_task(job):
            started["go"] = True
            while not release["go"]:
                time.sleep(0.01)

        app.run_in_background(slow_task)
        deadline = time.monotonic() + 2.0
        while not started["go"] and time.monotonic() < deadline:
            self.qapp.processEvents()
            time.sleep(0.01)
        self.assertTrue(app.busy)

        second_ran = {"go": False}
        app.run_in_background(lambda job: second_ran.__setitem__("go", True))
        self.qapp.processEvents()
        self.assertFalse(second_ran["go"], "a second job must not start while busy")
        self.assertEqual(len(busy_dialog_calls), 1, "busy guard should have surfaced exactly one dialog")

        release["go"] = True
        deadline = time.monotonic() + 2.0
        while app.busy and time.monotonic() < deadline:
            self.qapp.processEvents()
            time.sleep(0.01)
        self.assertFalse(app.busy)

    def test_global_key_filter_does_not_crash_on_keypress(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent

        import lazygimp.gui_qt.pages.wizard as wizard_module

        window, app = self._build_app()
        self.addCleanup(window.close)

        # Backspace from wizard step 0 with a non-empty plan opens a
        # blocking themed_confirm() modal (real QDialog.exec()) asking
        # "discard your selections?" — correct real-app behavior, but an
        # unattended offscreen test has no one to click it. Patched out
        # here (as "yes, discard") purely so the keypress path can be
        # driven all the way through without hanging on that dialog.
        original_confirm = wizard_module.themed_confirm
        wizard_module.themed_confirm = lambda *a, **kw: True
        self.addCleanup(setattr, wizard_module, "themed_confirm", original_confirm)

        # Deliberately NOT testing "2" here: on the landing screen that's
        # start_quick_setup(), which hands a REAL plan straight to
        # show_install_progress() and immediately starts executing it on
        # a background thread (package-manager installs, sudo, network
        # downloads...) — not something any automated test should ever
        # trigger for real. "1" (open wizard) and Backspace (navigate
        # back, only ever queuing/discarding PlannedAction metadata) are
        # both safe to drive through the real filter.
        for key in (Qt.Key_1, Qt.Key_Backspace):
            ev = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
            self.qapp.sendEvent(window, ev)
            self.qapp.processEvents()

        # "1" on the landing screen opens the wizard, then Backspace
        # from step 0 (confirmed above) returns to landing — confirm it
        # landed somewhere sane and nothing raised through the filter.
        self.assertIn(app.current_screen, ("landing", "wizard"))


if __name__ == "__main__":
    unittest.main()
