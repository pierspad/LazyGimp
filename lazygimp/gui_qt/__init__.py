"""PySide6 (Qt for Python) GUI engine — parallel implementation living
next to the CustomTkinter engine in ``lazygimp/gui``.

Phase 3 wires this all the way up: ``launch_gui_qt()`` below is the Qt
counterpart of ``lazygimp/gui/__init__.py``'s ``launch_gui()``. It is
opt-in — reached via ``installer.py --qt`` / ``LAZYGIMP_GUI=qt`` (see
``lazygimp/cli.py``) — while the Tk GUI stays the default so a human can
A/B the two before any swap-over. See ``lazygimp/gui_qt/README.md`` for
the old (Tk) -> new (Qt) API table the foundation/page modules were
built against.

Only this __init__ is safe to import headless: PySide6 is imported
lazily, inside launch_gui_qt(), so ``python3 installer.py status``
keeps working on a box without PySide6 installed (same contract
``lazygimp/gui/__init__.py`` keeps for Tk).
"""
from __future__ import annotations

import sys

from ..util import _self_destruct_if_ephemeral


def launch_gui_qt():
    try:
        from PySide6.QtWidgets import QApplication, QMainWindow
    except ImportError:
        print("[fail] The --qt GUI needs the PySide6 package:\n"
              "         pip install -r requirements-qt.txt\n"
              "       (the prebuilt lazygimp-linux-x86_64 binary ships it already; the\n"
              "       default GUI (no --qt) and the CLI both work without it: "
              "python3 installer.py --help)", file=sys.stderr)
        sys.exit(1)

    from . import theme
    from .app import LazyGimpApp

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(theme.build_stylesheet())

    window = QMainWindow()
    LazyGimpApp(window)
    window.show()
    try:
        app.exec()
    finally:
        _self_destruct_if_ephemeral()
