"""Constructs one of every gui widget/dialog inside a QApplication and
confirms nothing raises. Not a UI test (no display needed) — run with:

    QT_QPA_PLATFORM=offscreen python3 -m lazygimp.gui._smoke_test

This only proves the widgets *build*; it says nothing about visual
correctness (there's no display to compare against in CI/sandbox
environments). A human should eyeball the real window once a display is
available before this foundation is trusted for the page ports.
"""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget

    from lazygimp.gui import theme, widgets, icons, dialogs

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(theme.build_stylesheet())

    window = QMainWindow()
    central = QWidget()
    layout = QVBoxLayout(central)
    window.setCentralWidget(central)

    # -- theme --------------------------------------------------------------
    assert theme.qfont(theme.F_BODY) is not None
    assert isinstance(theme.build_stylesheet(), str) and "QPushButton" not in ""  # sanity no-op
    assert theme.TONE_COLORS["info"][0].startswith("#")

    # -- icons ----------------------------------------------------------------
    for kind in ("check", "x", "spinner", "info", "warn", "install", "trash", "refresh", "link", "box",
                 "gear", "gimp", "photogimp", "linux", "bolt", "folder", "undo"):
        pix = icons.render_icon_pixmap(kind, theme.TEXT, size=20)
        assert not pix.isNull(), f"icon '{kind}' produced a null pixmap"
    ic = icons.render_icon("check", theme.ACCENT, size=18)
    assert ic is not None
    lbl = icons.icon_label(central, "info", color=theme.ACCENT, size=20)
    layout.addWidget(lbl)

    # -- widgets --------------------------------------------------------------
    btn = widgets.RoundedButton(central, "Install", variant="primary", icon="install",
                                 command=lambda: None)
    layout.addWidget(btn)
    btn.start_loading("Working")
    btn.stop_loading()
    btn.set_variant("danger")
    btn.set_text("Removed")
    btn.set_enabled(False)
    btn.set_enabled(True)

    blocked = {"hit": False}
    blocked_btn = widgets.RoundedButton(central, "Locked", variant="secondary",
                                         on_blocked=lambda: blocked.__setitem__("hit", True))
    blocked_btn.set_enabled(False)
    layout.addWidget(blocked_btn)

    card = widgets.RoundedCard(central, command=lambda: None)
    card_layout = QVBoxLayout(card.body)
    from PySide6.QtWidgets import QLabel
    card_layout.addWidget(QLabel("card content", card.body))
    card.finalize()
    layout.addWidget(card)

    pbar = widgets.ProgressBar(central)
    pbar.set_fraction(0.42)
    layout.addWidget(pbar)

    var = widgets.BoolVar(False)
    cb = widgets.ModernCheckbox(central, variable=var, text="Enable thing")
    layout.addWidget(cb)
    cb.setChecked(True)
    assert var.get() is True

    scroll = widgets.ScrollableFrame(central)
    from PySide6.QtWidgets import QVBoxLayout as _QVL
    inner_layout = _QVL(scroll.inner)
    inner_layout.addWidget(QLabel("scrolled content", scroll.inner))
    layout.addWidget(scroll)
    scroll.page_down()
    scroll.page_up()

    clicked = {"hit": False}
    widgets.bind_click_recursive(card, lambda: clicked.__setitem__("hit", True))

    hdr = widgets.page_header(central, "Test Page")
    assert hdr.text() == "Test Page"

    callout_card = widgets.callout(central, "Heads up, this is a callout.", tone="warn")
    assert callout_card is not None

    # -- dialogs (constructed, not exec'd — exec() would block forever
    #    waiting for user input with no display attached) --------------------
    d = dialogs._ThemedDialogBase(window)
    assert d is not None

    pw_prompt = dialogs.QPasswordPrompt(window)
    assert pw_prompt is not None

    window.show()
    app.processEvents()

    print("SMOKE TEST OK — every gui widget constructed without error.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
