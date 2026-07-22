"""Builds landing.py's and uninstall.py's top-level screens inside a real
(offscreen) QApplication and confirms nothing raises. Companion to
``lazygimp/gui/_smoke_test.py`` (which only covers the foundation
widgets) — this one exercises the two ported page mixins themselves.

Run with:

    QT_QPA_PLATFORM=offscreen python3 -m lazygimp.gui.pages._smoke_test_landing_uninstall

Uses a minimal FakeApp that composes LandingPage + UninstallPage the same
way LazyGimpApp will (see gui/app.py), stubbing out only what the real
app.py / the other two page mixins (wizard.py, progress.py — being
ported in parallel, not present yet) would otherwise provide:
show_wizard, show_install_progress, run_in_background, _build_status_bar.
Everything else (self.root, self.root_frame, self.busy, self.hw,
show_landing, show_uninstall_confirm, launch_gimp_and_close,
start_quick_setup, on_confirm_uninstall) is the real code under test.

Deliberately never invokes run_in_background's `fn` (it's just recorded,
not called) and never clicks the destructive uninstall buttons — this
proves the widget trees build cleanly, not that installs/removals work
(those are exercised elsewhere, by the backend's own logic, not by this
GUI smoke test).
"""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QWidget

    from lazygimp.gui import theme
    from lazygimp.gui.pages.landing import LandingPage
    from lazygimp.gui.pages.uninstall import UninstallPage
    from lazygimp.hardware import detect_hardware

    class FakeApp(LandingPage, UninstallPage):
        def __init__(self, root, root_frame):
            self.root = root
            self.root_frame = root_frame
            self.current_screen = "landing"
            self.busy = False
            self.hw = detect_hardware()
            self.calls = []

        # -- stand-ins for the sibling mixins/app.py, not under test here --
        def show_wizard(self):
            self.calls.append("show_wizard")

        def show_install_progress(self, actions):
            self.calls.append(("show_install_progress", len(actions)))

        def run_in_background(self, fn, on_done=None):
            self.calls.append(("run_in_background", fn, on_done))

        def _build_status_bar(self, parent):
            layout = parent.layout()
            bar = QLabel("status bar stub", parent)
            if layout is not None:
                layout.addWidget(bar)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(theme.build_stylesheet())

    window = QMainWindow()
    root_frame = QWidget()
    window.setCentralWidget(root_frame)

    fake = FakeApp(window, root_frame)

    # -- landing ------------------------------------------------------------
    fake.show_landing()
    assert root_frame.layout() is not None, "show_landing() didn't give root_frame a layout"
    assert root_frame.layout().count() >= 1, "landing screen produced no widgets"
    assert fake._landing_frame is not None

    # start_quick_setup(): builds the plan from real (read-only) detection
    # calls and hands it to show_install_progress — stubbed here, so this
    # never touches the filesystem.
    fake.start_quick_setup()
    assert any(isinstance(c, tuple) and c[0] == "show_install_progress" for c in fake.calls)

    # re-entering show_landing with a _preserve widget (the wizard's
    # landing<->wizard transition hook) must not destroy it.
    keep_widget = QWidget(root_frame)
    root_frame.layout().addWidget(keep_widget)
    fake.show_landing(_preserve=keep_widget)
    assert keep_widget.parent() is root_frame, "_preserve widget was destroyed by show_landing()"

    # ephemeral checkbox toggle shouldn't raise
    ephemeral_checkboxes = [w for w in root_frame.findChildren(QWidget)
                             if type(w).__name__ == "ModernCheckbox"]
    assert ephemeral_checkboxes, "ephemeral ModernCheckbox not found in landing tree"
    ephemeral_checkboxes[0].setChecked(not ephemeral_checkboxes[0].isChecked())

    # -- uninstall ------------------------------------------------------------
    fake.show_uninstall_confirm()
    assert root_frame.layout().count() >= 1, "uninstall screen produced no widgets"

    fake.on_confirm_uninstall([])  # no-op branch, must not touch run_in_background
    calls_before = len(fake.calls)
    fake.on_confirm_uninstall(["photogimp", "sam"])  # wiring only; run_in_background is stubbed
    assert len(fake.calls) == calls_before + 1

    window.show()
    app.processEvents()

    print("SMOKE TEST OK — landing.py and uninstall.py built without error.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
