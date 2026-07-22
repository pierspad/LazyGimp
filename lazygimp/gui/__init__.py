"""PySide6 (Qt for Python) GUI engine for LazyGimp."""
from __future__ import annotations

import sys

from ..util import _self_destruct_if_ephemeral


def launch_gui():
    try:
        from PySide6.QtWidgets import QApplication, QMainWindow
    except ImportError:
        print("[fail] The LazyGimp GUI requires PySide6:\n"
              "         pip install -r requirements.txt\n"
              "       (or install PySide6 directly: pip install PySide6)", file=sys.stderr)
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


# Backwards compatibility alias
launch_gui = launch_gui
