"""Reusable widgets — CustomTkinter engine behind the SAME API the pages
already use (RoundedButton, RoundedCard, ProgressBar, ModernCheckbox,
ScrollableFrame). The pages didn't have to change when the engine did:
that's the point of the facade.

Plain tk.Label/tk.Frame children keep working inside these widgets as
long as their bg matches the card color — the theme guarantees it.
"""
from __future__ import annotations

from ..compat import ctk, tk
from .helpers import autowrap_label
from .icons import icon_canvas
from .theme import (
    ACCENT, ACCENT_HOVER, ACCENT_TEXT, BG, CARD_BG, CARD_BORDER, DANGER, DANGER_HOVER,
    DANGER_TEXT, DISABLED_BG, DISABLED_TEXT, F_BODY_B, F_H2, F_SMALL, SECONDARY_HOVER,
    SUCCESS, SUCCESS_HOVER, SUCCESS_TEXT, TEXT, TONE_COLORS,
)

# Text glyphs standing in for the old vector icons inside buttons — safe
# in DejaVu Sans (the default Linux UI font), no emoji fonts involved.
_BUTTON_GLYPHS = {
    "install": "↓", "trash": "✕", "bolt": "⚡", "refresh": "⟳",
    "link": "↗", "x": "✕", "box": "▣", "check": "✓",
}


class RoundedButton(ctk.CTkButton):
    _PALETTE = {
        "primary": (ACCENT, ACCENT_HOVER, ACCENT_TEXT),
        "success": (SUCCESS, SUCCESS_HOVER, SUCCESS_TEXT),
        "danger": (DANGER, DANGER_HOVER, DANGER_TEXT),
        "secondary": (CARD_BORDER, SECONDARY_HOVER, TEXT),
    }

    def __init__(self, parent, text, command=None, variant="secondary", icon=None,
                 width=None, height=34, radius=13, font=F_BODY_B, bg=None, on_blocked=None):
        fill, hover, fg = self._PALETTE[variant]
        self._icon_glyph = _BUTTON_GLYPHS.get(icon, "") if icon else ""
        self._base_text = text
        self.on_blocked = on_blocked
        self.variant = variant
        self._loading = False
        self._loading_base = ""
        self._loading_frame = 0
        super().__init__(
            parent, text=self._decorated(text), command=command,
            width=width or 140, height=height, corner_radius=radius,
            fg_color=fill, hover_color=hover, text_color=fg,
            text_color_disabled=DISABLED_TEXT, font=font, border_width=0,
        )
        # Clicking a disabled button still means something on some pages
        # (e.g. "enter a HF token first") — CTk swallows the click, so we
        # listen underneath.
        if on_blocked is not None:
            self.bind("<Button-1>", self._maybe_blocked)

    # -- old-API surface -------------------------------------------------

    @property
    def command(self):
        return self._command

    @command.setter
    def command(self, fn):
        self._command = fn

    @property
    def text(self):
        return self._base_text

    def set_text(self, text: str):
        self._base_text = text
        if not self._loading:
            self.configure(text=self._decorated(text))

    def set_enabled(self, enabled: bool):
        self.configure(state="normal" if enabled else "disabled")
        # keep the fill readable when disabled (CTk only dims the text)
        fill = self._PALETTE[self.variant][0] if enabled else DISABLED_BG
        self.configure(fg_color=fill)

    def set_variant(self, variant: str):
        self.variant = variant
        fill, hover, fg = self._PALETTE[variant]
        self.configure(fg_color=fill, hover_color=hover, text_color=fg)

    def start_loading(self, base_text="Working"):
        if self._loading:
            return
        self._loading = True
        self._loading_base = base_text
        self.configure(state="disabled")
        self._animate()

    def stop_loading(self):
        self._loading = False
        self.configure(state="normal", text=self._decorated(self._base_text))

    # -- internals ---------------------------------------------------------

    def _decorated(self, text: str) -> str:
        return f"{self._icon_glyph}  {text}" if self._icon_glyph and text else (self._icon_glyph or text)

    def _maybe_blocked(self, _event=None):
        if self.cget("state") == "disabled" and self.on_blocked:
            self.on_blocked()

    def _animate(self):
        if not self._loading or not self.winfo_exists():
            return
        dots = "." * (1 + self._loading_frame % 3)
        self.configure(text=f"{self._loading_base}{dots}")
        self._loading_frame += 1
        self.after(350, self._animate)


class RoundedCard(ctk.CTkFrame):
    """A rounded card with a `.body` plain-tk frame for content — pages
    pack tk.Label/tk.Frame children into .body exactly as before."""

    def __init__(self, parent, bg=CARD_BG, border=CARD_BORDER, radius=18, pad=18, width=None, height=None):
        super().__init__(parent, fg_color=bg, border_color=border, border_width=1,
                         corner_radius=radius, width=width or 200, height=height or 200)
        if width or height:
            self.pack_propagate(False)
            self.grid_propagate(False)
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill="both", expand=True, padx=pad, pady=pad)

    def finalize(self):  # kept for call-site compatibility
        pass


class ProgressBar(ctk.CTkProgressBar):
    def __init__(self, parent, width=200, height=7, bg=None, track=CARD_BORDER, fill=ACCENT):
        super().__init__(parent, width=width, height=height, corner_radius=height // 2,
                         fg_color=track, progress_color=fill, border_width=0)
        self.set(0)

    def set_fraction(self, frac: float):
        self.set(max(0.0, min(1.0, frac)))


class ModernCheckbox(ctk.CTkCheckBox):
    def __init__(self, parent, variable, command=None, size=20, bg=None):
        super().__init__(parent, text="", variable=variable, onvalue=True, offvalue=False,
                         command=command, width=size, height=size,
                         checkbox_width=size, checkbox_height=size, corner_radius=6,
                         fg_color=ACCENT, hover_color=ACCENT_HOVER, border_color=CARD_BORDER,
                         border_width=2, checkmark_color=ACCENT_TEXT)


class ScrollableFrame(ctk.CTkScrollableFrame):
    """CTkScrollableFrame subclasses tkinter.Frame, so plain-tk children
    land inside the scrolled area, and it handles the mouse wheel itself
    (recursively, on enter/leave) — no app-level routing needed."""

    def __init__(self, parent, bg=BG):
        super().__init__(parent, fg_color=bg, corner_radius=0)
        self.inner = self  # old call sites pack content into .inner


def bind_click_recursive(widget, handler, skip=()):
    if widget in skip:
        return
    try:
        widget.configure(cursor="hand2")
    except tk.TclError:
        pass
    widget.bind("<Button-1>", lambda e: handler(), add="+")
    for child in widget.winfo_children():
        bind_click_recursive(child, handler, skip)


def page_header(parent, title):
    tk.Label(parent, text=title, bg=BG, fg=TEXT, font=F_H2).pack(anchor="w", pady=(0, 16))


def callout(parent, text, tone="info"):
    icon_kind = {"info": "info", "warn": "warn", "ok": "check"}[tone]
    bgc, fg = TONE_COLORS[tone]
    card = RoundedCard(parent, bg=bgc, border=bgc, radius=14, pad=12)
    card.pack(fill="x", pady=(4, 12))
    row = tk.Frame(card.body, bg=bgc)
    row.pack(fill="x")
    icon_canvas(row, icon_kind, color=fg, size=18, bg=bgc).pack(side="left", padx=(0, 8), anchor="n")
    autowrap_label(row, text, fg=fg, bg=bgc, font=F_SMALL).pack(side="left", fill="x", expand=True)
    card.finalize()
    return card
