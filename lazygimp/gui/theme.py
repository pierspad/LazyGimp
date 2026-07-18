"""Design tokens — every color, font and ttk style in one place.

Restyling the whole app (palette swap, font change) is an edit to THIS
file only: no other gui module hardcodes a color or a font tuple.
"""
from __future__ import annotations

from ..compat import tk, ttk

# --- dark palette ----------------------------------------------------------
BG = "#1b1d21"
CARD_BG = "#26282e"
CARD_BORDER = "#35373e"
TEXT = "#e7e8ea"
TEXT_MUTED = "#9a9da4"
ACCENT = "#4dc3f0"
ACCENT_HOVER = "#6fd0f5"
ACCENT_TEXT = "#08222b"
SUCCESS = "#3fbf7f"
SUCCESS_HOVER = "#57cf93"
SUCCESS_TEXT = "#08210f"
DANGER = "#ee5a5f"
DANGER_HOVER = "#f27478"
DANGER_TEXT = "#2b0b0c"
WARNING = "#f2a93c"
DISABLED_BG = "#34363c"
DISABLED_TEXT = "#6d7076"

FIELD_BG = "#303237"          # entries / comboboxes
SCROLLBAR = "#4a4d54"
LOG_BG = "#101114"            # install-progress log panel
SECONDARY_HOVER = "#3f424a"   # hover fill of secondary buttons

# tone colors for callouts / snackbars: tone -> (background, foreground)
TONE_COLORS = {
    "info": ("#16303a", "#7fd0f0"),
    "warn": ("#3a2e14", WARNING),
    "error": ("#3a1414", DANGER),
    "ok": ("#123522", SUCCESS),
}

# --- fonts -----------------------------------------------------------------
FONT_FAMILY = "Sans"
F_HERO = (FONT_FAMILY, 28, "bold")          # landing title
F_H1 = (FONT_FAMILY, 20, "bold")            # screen titles
F_H2 = (FONT_FAMILY, 18, "bold")            # page headers
F_H3 = (FONT_FAMILY, 16, "bold")            # wizard step title
F_CARD_TITLE = (FONT_FAMILY, 14, "bold")
F_DIALOG_TITLE = (FONT_FAMILY, 13, "bold")
F_ITEM_TITLE = (FONT_FAMILY, 12, "bold")
F_SECTION = (FONT_FAMILY, 11, "bold")
F_SUBTITLE = (FONT_FAMILY, 11)
F_BODY_B = (FONT_FAMILY, 10, "bold")
F_BODY = (FONT_FAMILY, 10)
F_SMALL_B = (FONT_FAMILY, 9, "bold")
F_SMALL = (FONT_FAMILY, 9)
F_MONO = ("Monospace", 10)


def apply_style(root) -> None:
    """Configure the ttk styles + option database for the dark theme."""
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TEntry", fieldbackground=FIELD_BG, foreground=TEXT, insertcolor=TEXT,
                    bordercolor=FIELD_BG, lightcolor=FIELD_BG, darkcolor=FIELD_BG,
                    borderwidth=0, relief="flat", padding=6)
    style.configure("TCombobox", fieldbackground=FIELD_BG, background=FIELD_BG, foreground=TEXT,
                    arrowcolor=TEXT, bordercolor=FIELD_BG, lightcolor=FIELD_BG, darkcolor=FIELD_BG,
                    borderwidth=0, relief="flat", padding=6)
    style.map("TCombobox", fieldbackground=[("readonly", FIELD_BG)], foreground=[("readonly", TEXT)],
              background=[("readonly", FIELD_BG)])
    style.layout("Modern.Vertical.TScrollbar", [
        ("Vertical.Scrollbar.trough", {"children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"}),
        ], "sticky": "ns"}),
    ])
    style.configure("Modern.Vertical.TScrollbar", gripcount=0, background=SCROLLBAR,
                    troughcolor=BG, bordercolor=BG, lightcolor=SCROLLBAR, darkcolor=SCROLLBAR,
                    relief="flat", width=8, arrowsize=0)
    style.configure("TSeparator", background=CARD_BORDER)
    root.option_add("*TCombobox*Listbox.background", FIELD_BG)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", ACCENT_TEXT)
