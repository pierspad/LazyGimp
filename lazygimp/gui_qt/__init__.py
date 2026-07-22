"""PySide6 (Qt for Python) GUI engine — parallel implementation living
next to the CustomTkinter engine in ``lazygimp/gui``.

This package is Phase 1 of a staged rewrite: theming + the reusable
widget library only (no page modules yet). Nothing here is wired into
``lazygimp/cli.py`` or ``lazygimp/gui/app.py`` — the Tk GUI remains the
one actually shipped/launched until the Qt port reaches parity and is
deliberately swapped in.

See ``lazygimp/gui_qt/README.md`` for the old-symbol -> new-symbol API
table used by the page-porting agents that build on top of this.
"""
from __future__ import annotations
