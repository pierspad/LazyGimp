"""Reusable canvas widgets.

Rendering strategy: every widget creates its canvas items ONCE (or when
its size actually changes) and afterwards only mutates them in place with
`itemconfig`/`coords`. State changes — hover, enabled, progress, spinner
frames — never call `delete("all")`, so there is no flicker and animation
frames cost microseconds instead of a full geometry rebuild.
"""

from __future__ import annotations

from ..compat import tk, ttk
from .helpers import autowrap_label
from .icons import icon_canvas
from .theme import F_H2, F_SMALL, TONE_COLORS
from .helpers import _rounded_points, draw_round_rect
from .icons import render_icon_photo, draw_icon
from .theme import (
    ACCENT, ACCENT_HOVER, ACCENT_TEXT, BG, CARD_BG, CARD_BORDER, DANGER, DANGER_HOVER,
    DANGER_TEXT, DISABLED_BG, DISABLED_TEXT, F_BODY_B, SECONDARY_HOVER, SUCCESS,
    SUCCESS_HOVER, SUCCESS_TEXT, TEXT,
)


class RoundedButton(tk.Canvas):
    _PALETTE = {
        "primary": (ACCENT, ACCENT_HOVER, ACCENT_TEXT),
        "success": (SUCCESS, SUCCESS_HOVER, SUCCESS_TEXT),
        "danger": (DANGER, DANGER_HOVER, DANGER_TEXT),
        "secondary": (CARD_BORDER, SECONDARY_HOVER, TEXT),
    }

    def __init__(self, parent, text, command=None, variant="secondary", icon=None,
                 width=None, height=34, radius=13, font=F_BODY_B, bg=None, on_blocked=None):
        super().__init__(parent, height=height, width=width or 1, highlightthickness=0, bd=0,
                         bg=bg or parent["bg"])
        self.command = command
        self.on_blocked = on_blocked
        self.variant = variant
        self.icon = icon
        self.radius = radius
        self.text = text
        self.font = font
        self._enabled = True
        self._hover = False
        self._fixed_width = width
        self._loading = False
        self._loading_base = ""
        self._loading_frame = 0
        self._bg_item = None
        self._text_item = None
        self._built_size = None
        self.bind("<Configure>", lambda e: self._rebuild())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Button-1>", self._on_click)

    # ---- public state changes (all incremental) -----------------------

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self._hover = False
        self._restyle()

    def set_text(self, text: str):
        self.text = text
        self._restyle()

    def set_variant(self, variant: str):
        self.variant = variant
        self._restyle()

    def start_loading(self, base_text="Working"):
        if self._loading:
            return
        self._loading = True
        self._loading_base = base_text
        self._loading_frame = 0
        self._enabled = False
        self._restyle()
        self._animate()

    def stop_loading(self):
        self._loading = False

    # ---- internals -----------------------------------------------------

    def _set_hover(self, hover):
        if self._enabled:
            self._hover = hover
            self._restyle()
            self.configure(cursor="hand2" if hover else "")

    def _on_click(self, _event=None):
        if self._enabled:
            if self.command:
                self.command()
        elif self.on_blocked:
            self.on_blocked()

    def _animate(self):
        if not self._loading or not self.winfo_exists():
            return
        self._loading_frame += 1
        _fill, fg = self._colors()
        self._redraw_icon(fg)
        self.after(100, self._animate)

    def _size(self):
        w = max(self.winfo_width(), self._fixed_width or 1, 10)
        h = int(self["height"])
        return w, h

    def _colors(self):
        base_fill, hover_fill, fg = self._PALETTE[self.variant]
        if not self._enabled and not self._loading:
            return DISABLED_BG, DISABLED_TEXT
        if self._loading or not self._hover:
            return base_fill, fg
        return hover_fill, fg

    def _label(self):
        return (self._loading_base + "…") if self._loading else self.text

    def _rebuild(self):
        """Full rebuild — only on first draw and real size changes."""
        w, h = self._size()
        if (w, h) == self._built_size and self._bg_item is not None:
            return
        self._built_size = (w, h)
        self.delete("all")
        fill, fg = self._colors()
        self._bg_item = draw_round_rect(self, 1, 1, w - 1, h - 1, self.radius, fill=fill, outline="")
        self._text_item = self.create_text(0, 0, text=self._label(), fill=fg, font=self.font)
        self._place_text()
        self._redraw_icon(fg)

    def _has_icon(self):
        return self._loading or bool(self.icon)

    def _place_text(self):
        w, h = self._size()
        if self._has_icon():
            self.coords(self._text_item, 38, h / 2)
            self.itemconfig(self._text_item, anchor="w")
        else:
            self.coords(self._text_item, w / 2, h / 2)
            self.itemconfig(self._text_item, anchor="center")

    def _restyle(self):
        if self._bg_item is None:
            return self._rebuild()
        fill, fg = self._colors()
        self.itemconfig(self._bg_item, fill=fill)
        self.itemconfig(self._text_item, fill=fg, text=self._label())
        self._place_text()
        self._redraw_icon(fg)

    def _redraw_icon(self, fg):
        """The icon is the only part that is deleted+recreated on a state
        change: with Pillow it is a single cached PhotoImage (so this is one
        create_image of an already-rendered bitmap), without Pillow a handful
        of vector strokes tagged "icon"."""
        self.delete("icon")
        if not self._has_icon():
            return
        _w, h = self._size()
        if self._loading:
            kind, size, frame = "spinner", 16, self._loading_frame % 12
        else:
            kind, size, frame = self.icon, 17, 0
        photo = render_icon_photo(kind, fg, size, frame)
        if photo is not None:
            self.create_image(22, h / 2, image=photo, tags="icon")
        else:
            before = set(self.find_all())
            draw_icon(self, 22, h / 2, kind, color=fg, s=size * 0.42, frame=frame)
            for item in set(self.find_all()) - before:
                self.addtag_withtag("icon", item)


class RoundedCard(tk.Frame):
    def __init__(self, parent, bg=CARD_BG, border=CARD_BORDER, radius=18, pad=18, width=None, height=None):
        super().__init__(parent, bg=parent["bg"])
        self._bg, self._border, self._radius, self._pad = bg, border, radius, pad
        self._fixed_height = height
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=parent["bg"])
        if width:
            self.canvas.configure(width=width)
        if height:
            self.canvas.configure(height=height)
        self.canvas.pack(fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(pad, pad, window=self.body, anchor="nw")
        self._bg_item = None
        self._last_h = None
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.body.bind("<Configure>", self._on_body_configure)

    def _on_canvas_configure(self, event=None):
        w = self.canvas.winfo_width()
        opts = {"width": max(0, w - 2 * self._pad)}
        if self._fixed_height:
            opts["height"] = max(0, self._fixed_height - 2 * self._pad)
        self.canvas.itemconfig(self._win, **opts)
        self._redraw(w, self.canvas.winfo_height())

    def _on_body_configure(self, event=None):
        if self._fixed_height:
            h = self._fixed_height
        else:
            h = self.body.winfo_reqheight() + 2 * self._pad
            if h != self._last_h:
                self._last_h = h
                self.canvas.configure(height=h)
        self._redraw(self.canvas.winfo_width(), h)

    def _redraw(self, w, h):
        if w <= 4 or h <= 4:
            return
        points = _rounded_points(1, 1, w - 1, h - 1, self._radius)
        if self._bg_item is None:
            self._bg_item = self.canvas.create_polygon(
                points, smooth=True, fill=self._bg, outline=self._border, width=1, tags="card_bg")
            self.canvas.tag_lower(self._bg_item)
        else:
            self.canvas.coords(self._bg_item, *points)

    def finalize(self):
        self.update_idletasks()
        self._on_body_configure()
        self._on_canvas_configure()


class ProgressBar(tk.Canvas):
    def __init__(self, parent, width=200, height=7, bg=None, track=CARD_BORDER, fill=ACCENT):
        super().__init__(parent, width=width, height=height, highlightthickness=0, bd=0, bg=bg or parent["bg"])
        self._frac = 0.0
        self._track, self._fillc = track, fill
        self._track_item = None
        self._fill_item = None
        self._built_w = None
        self.bind("<Configure>", lambda e: self._draw())

    def set_fraction(self, frac: float):
        self._frac = max(0.0, min(1.0, frac))
        self._draw()

    def _draw(self):
        w = self.winfo_width() or int(self["width"])
        h = int(self["height"])
        if self._track_item is None or w != self._built_w:
            self._built_w = w
            self.delete("all")
            self._track_item = draw_round_rect(self, 0, 0, w, h, h / 2, fill=self._track, outline="")
            self._fill_item = draw_round_rect(self, 0, 0, h, h, h / 2, fill=self._fillc, outline="")
        fw = w * self._frac
        if fw >= h:
            self.coords(self._fill_item, *_rounded_points(0, 0, fw, h, h / 2))
            self.itemconfig(self._fill_item, state="normal")
        else:
            self.itemconfig(self._fill_item, state="hidden")


class ModernCheckbox(tk.Canvas):
    def __init__(self, parent, variable, command=None, size=20, bg=None):
        super().__init__(parent, width=size, height=size, highlightthickness=0, bd=0, bg=bg or parent["bg"])
        self.variable = variable
        self.command = command
        self.size = size
        self._box_item = None
        self._trace_id = variable.trace_add("write", lambda *_a: self._sync())
        self.bind("<Button-1>", self._toggle)
        self.bind("<Enter>", lambda e: self.configure(cursor="hand2"))
        self.bind("<Destroy>", self._on_destroy)
        self._build()

    def _toggle(self, _event=None):
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()

    def _on_destroy(self, _event=None):
        try:
            self.variable.trace_remove("write", self._trace_id)
        except Exception:
            pass

    def _build(self):
        s = self.size
        self._box_item = draw_round_rect(self, 1, 1, s - 1, s - 1, 6, fill="", outline="")
        photo = render_icon_photo("check", ACCENT_TEXT, max(10, int(s * 0.75)))
        if photo is not None:
            self.create_image(s / 2, s / 2, image=photo, tags="check")
        else:
            before = set(self.find_all())
            draw_icon(self, s / 2, s / 2, "check", color=ACCENT_TEXT, s=s * 0.32)
            for item in set(self.find_all()) - before:
                self.addtag_withtag("check", item)
        self._sync()

    def _sync(self):
        if not self.winfo_exists():
            return
        if self.variable.get():
            self.itemconfig(self._box_item, fill=ACCENT, outline="", width=1)
            self.itemconfig("check", state="normal")
        else:
            self.itemconfig(self._box_item, fill="", outline=CARD_BORDER, width=2)
            self.itemconfig("check", state="hidden")


class ScrollableFrame(tk.Frame):
    """Vertical scroll area. Wheel events are routed here by the app's ONE
    global binding (see LazyGimpApp._on_global_wheel) — nothing is ever
    bound per-child, so page refreshes cost zero re-binding work."""

    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="Modern.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y", padx=(4, 0))
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self._win, width=e.width))

    def scroll_units(self, units: int):
        if self.canvas.winfo_exists():
            self.canvas.yview_scroll(units, "units")


def bind_click_recursive(widget, handler, skip=()):
    if widget in skip:
        return
    try:
        widget.configure(cursor="hand2")
    except tk.TclError:
        pass
    widget.bind("<Button-1>", lambda e: handler())
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
