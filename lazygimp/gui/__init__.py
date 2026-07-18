"""The optional Tkinter GUI, as a package:

    theme.py     design tokens — every color, font, ttk style
    icons.py     vector icons (Pillow-antialiased when available)
    helpers.py   drawing/layout primitives
    widgets.py   RoundedButton, RoundedCard, ProgressBar, … (incremental
                 rendering: itemconfig/coords, never delete-all-and-redraw)
    dialogs.py   themed dialogs, snackbar, sudo password prompt
    state.py     "what's installed" in the uninstall screen's vocabulary
    app.py       LazyGimpApp — plumbing + page mixins composition
    pages/       one module per screen (landing/uninstall/wizard/progress)

Only this __init__ is safe to import headless: the submodules assume a
working Tk and are imported lazily by launch_gui(), so `python3 lazygimp.py
status` keeps working on a box with no python3-tk at all.
"""
from __future__ import annotations

import sys

from ..compat import _TK_OK, tk
from ..util import _self_destruct_if_ephemeral


def launch_gui():
    if not _TK_OK:
        print("[fail] Tkinter is not available in this Python — install python3-tk (or the equivalent "
              "package for your distro) to use the graphical installer, or use the CLI: "
              "python3 lazygimp.py --help", file=sys.stderr)
        sys.exit(1)
    from .app import LazyGimpApp
    root = tk.Tk()
    LazyGimpApp(root)
    try:
        root.mainloop()
    finally:
        _self_destruct_if_ephemeral()
