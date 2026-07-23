"""End-to-end integration smoke tests for LazyGimpApp (PySide6 GUI engine).

Exercises ``lazygimp.gui.app.LazyGimpApp`` (landing + uninstall + wizard +
progress screens, navigation, global shortcut filter, background job runner,
status bar pump, busy guard) inside a real QApplication event loop.

Run headless with:
    QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_gui_qt_app -v
"""
from __future__ import annotations

import sys
import time
import unittest

import importlib.util
_PYSIDE_OK = importlib.util.find_spec("PySide6") is not None


@unittest.skipUnless(_PYSIDE_OK, "PySide6 not installed — see requirements.txt")
class QtAppIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qapp = QApplication.instance() or QApplication(sys.argv)

    def _build_app(self):
        from PySide6.QtWidgets import QMainWindow

        from lazygimp.gui import theme
        from lazygimp.gui.app import LazyGimpApp

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
            app._wizard_pick_gimp_method("flatpak")
            self.qapp.processEvents()
            self.assertEqual(app.wizard_index, 1, "picking a GIMP method should auto-advance")

        self.assertEqual(app.wizard_steps[app.wizard_index].key, "components")
        self.assertIn("photogimp", app._wizard_cards)
        
        # Check plan membership flips when card clicked (install or remove depending on current status)
        from lazygimp.photogimp import photogimp_installed
        action_key = "photogimp:remove" if photogimp_installed() else "photogimp:install"
        was_queued = app.plan.has(action_key)
        app._wizard_cards["photogimp"]()
        self.assertNotEqual(app.plan.has(action_key), was_queued)
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
        import lazygimp.gui.app as app_module

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

        import lazygimp.gui.pages.wizard as wizard_module

        window, app = self._build_app()
        self.addCleanup(window.close)

        original_confirm = wizard_module.themed_confirm
        wizard_module.themed_confirm = lambda *a, **kw: True
        self.addCleanup(setattr, wizard_module, "themed_confirm", original_confirm)

        for key in (Qt.Key_1, Qt.Key_Backspace):
            ev = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
            self.qapp.sendEvent(window, ev)
            self.qapp.processEvents()

        self.assertIn(app.current_screen, ("landing", "wizard"))


if __name__ == "__main__":
    unittest.main()
