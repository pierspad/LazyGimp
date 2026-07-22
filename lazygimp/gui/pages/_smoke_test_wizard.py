"""Builds wizard.py's screen inside a real (offscreen) QApplication and
steps it through several pages, confirming nothing raises. Companion to
``lazygimp/gui/_smoke_test.py`` (foundation widgets) and
``lazygimp/gui/pages/_smoke_test_landing_uninstall.py`` /
``_smoke_test_progress.py`` (the sibling page ports) — this one exercises
``WizardPages``.

Run with:

    QT_QPA_PLATFORM=offscreen python3 -m lazygimp.gui.pages._smoke_test_wizard

Uses a minimal FakeApp that composes WizardPages the same way LazyGimpApp
will (see gui/app.py), stubbing out only what the real app.py / the other
page mixins would otherwise provide: show_landing, show_install_progress,
run_in_background. Everything else (self.root, self.root_frame, self.hw,
show_wizard and every _wizard_* method under test) is the real code.

Deliberately never invokes run_in_background's `fn` (it's just recorded)
and never lets a PlannedAction.run actually execute — clicking cards only
ever queues/dequeues PlannedAction objects (metadata), it never calls
their `.run`, exactly like the Tk original; the only place `.run` would
fire is inside the shared plan executor (progress.py), which this test
stubs out. So this proves the widget trees + step navigation build/behave
correctly, not that installs/removals work.
"""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

    from lazygimp.gui import theme
    from lazygimp.gui.pages.wizard import WizardPages
    from lazygimp.hardware import detect_hardware
    from lazygimp.models import MODEL_REGISTRY

    class FakeApp(WizardPages):
        def __init__(self, root, root_frame):
            self.root = root
            self.root_frame = root_frame
            self.current_screen = "landing"
            self.busy = False
            self.hw = detect_hardware()
            self.calls = []

        # -- stand-ins for the sibling mixins/app.py, not under test here --
        def show_landing(self):
            self.calls.append("show_landing")

        def show_install_progress(self, actions):
            self.calls.append(("show_install_progress", list(actions)))

        def run_in_background(self, fn, on_done=None):
            self.calls.append(("run_in_background", fn, on_done))

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(theme.build_stylesheet())

    window = QMainWindow()
    root_frame = QWidget()
    window.setCentralWidget(root_frame)

    fake = FakeApp(window, root_frame)

    # -- open the wizard ------------------------------------------------
    fake.show_wizard()
    assert root_frame.layout() is not None, "show_wizard() didn't give root_frame a layout"
    assert root_frame.layout().count() >= 1, "wizard screen produced no widgets"
    assert fake.wizard_steps, "no wizard steps were built"
    first_step_key = fake.wizard_steps[0].key
    print(f"steps: {[s.key for s in fake.wizard_steps]}")

    # -- GIMP step (only present if GIMP isn't already detected) --------
    if first_step_key == "gimp":
        from lazygimp.distro import detect_distro
        # show_wizard() preselects "gimp_install_pm" automatically when a
        # distro is detected (mirrors the Tk original) — so Next is only
        # gated when no distro was detected at all.
        distro_detected = detect_distro() is not None
        assert fake._wizard_can_advance() is (True if distro_detected else False)
        assert fake._wizard_next_btn is not None
        assert fake._wizard_next_btn.isEnabled() == fake._wizard_can_advance()
        # Explicitly (re)pick AppImage regardless, exercising the click
        # path either way. This only queues a PlannedAction —
        # install_gimp_appimage() itself is never called here.
        fake._wizard_pick_gimp_method("appimage")
        assert fake.plan.has("gimp_install_appimage")
        assert not fake.plan.has("gimp_install_pm"), "picking a method must clear the other one"
        assert fake.wizard_index == 1, "picking a GIMP method should auto-advance to the next step"

    assert fake.wizard_steps[fake.wizard_index].key == "components"

    # -- components step: toggle PhotoGIMP/G'MIC/Batcher cards in place -
    assert "photogimp" in fake._wizard_cards
    assert "gmic" in fake._wizard_cards
    from lazygimp.photogimp import photogimp_installed
    pg_key = "photogimp:remove" if photogimp_installed() else "photogimp:install"
    photogimp_was_queued = fake.plan.has(pg_key)
    fake._wizard_cards["photogimp"]()  # toggle it (advance=False, so we stay on this step)
    assert fake.wizard_steps[fake.wizard_index].key == "components", "advance=False toggle must not navigate"
    assert fake.plan.has(pg_key) != photogimp_was_queued, "toggle didn't flip plan membership"
    fake._wizard_cards["photogimp"]()  # toggle back to original state

    # go back one step, then forward again, exercising cached-page reuse
    if fake.wizard_index > 0:
        fake._wizard_back()
        fake._wizard_advance()
    assert fake.wizard_steps[fake.wizard_index].key == "components"

    fake._wizard_advance()  # -> sam
    assert fake.wizard_steps[fake.wizard_index].key == "sam"

    # -- SAM step: family cards + PyTorch combo + model toggle ----------
    assert set(fake._sam_family_cards.keys()) == {"SAM1", "SAM2", "SAM3"}
    assert fake._pytorch_combo is not None
    sample_spec = MODEL_REGISTRY[0]
    toggle_key = f"sam_model:{sample_spec.key}"
    assert toggle_key in fake._wizard_cards, f"{toggle_key} handler missing"
    was_queued = fake.plan.has(f"sam_model:{sample_spec.key}:install")
    fake._wizard_cards[toggle_key]()
    now_queued = fake.plan.has(f"sam_model:{sample_spec.key}:install")
    assert now_queued != was_queued, "SAM model toggle didn't flip plan membership"

    # SAM 3 token field: typing should feed hf_token_var without raising.
    assert fake._hf_token_entry is not None
    fake._hf_token_entry.setText("hf_dummy_token_123")
    assert fake.hf_token_var.get() == "hf_dummy_token_123"

    # switching families should not raise (rebuild-in-place path).
    fake._show_sam_category("SAM2")
    assert fake._sam_expanded_family == "SAM2"
    fake._show_sam_category("SAM1")

    # -- review step ------------------------------------------------------
    fake._wizard_advance()
    assert fake.wizard_steps[fake.wizard_index].key == "review"
    assert len(fake.plan) > 0, "plan should have preselected defaults queued"
    assert fake._review_rows_discard_commands, "review page produced no discardable rows"

    # discarding a row must not raise and must shrink the plan.
    plan_len_before = len(fake.plan)
    fake._review_rows_discard_commands[0]()
    assert len(fake.plan) == plan_len_before - 1 or len(fake.plan) < plan_len_before

    # -- proceed to install: must hand the plan to show_install_progress,
    #    never execute any PlannedAction.run itself. --------------------
    fake._wizard_start_install()
    assert any(isinstance(c, tuple) and c[0] == "show_install_progress" for c in fake.calls)

    # -- back-to-landing path (index 0, empty-ish plan branch already
    #    covered by _wizard_back's confirm gate above; re-open fresh and
    #    go back immediately with a non-empty plan pending confirm) -----
    fake2 = FakeApp(window, root_frame)
    fake2.show_wizard()
    fake2.wizard_index = 0
    # themed_confirm would block on exec() waiting for a user click with
    # no display attached, so we don't call _wizard_back() on a non-empty
    # plan here (that path is a real modal QDialog — outside what a
    # headless smoke test can safely drive). Empty-plan back requires no
    # confirmation at all, so exercise that branch instead.
    fake2.plan.clear()
    fake2._wizard_back()
    assert "show_landing" in fake2.calls

    window.show()
    app.processEvents()

    print("SMOKE TEST OK — wizard.py built and navigated without error.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
