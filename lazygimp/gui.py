from __future__ import annotations

from .compat import Image, ImageDraw, ImageTk, _PIL_OK, _TK_OK, simpledialog, tk, ttk
from .constants import APPIMAGE_DIR, BACKEND_DIR, GMIC_DOWNLOAD_PAGE, SAM3_HF_PAGE, SAM3_HF_REPO_ID, TORCH_INDEX_URLS, VENV_DIR
from .distro import detect_distro
from .gimp_detect import find_gimp_binary, find_gimp_command
from .gimp_install import appimage_present, gimp_native_installed, gmic_available_on_this_release, gmic_installed, install_gimp_appimage, install_gimp_package_manager, install_gmic_only, remove_gimp_appimage, remove_gimp_package_manager, remove_gmic_only
from .hardware import detect_hardware, recommended_model_key, recommended_torch_index
from .job import Job
from .models import MODEL_BY_KEY, MODEL_REGISTRY, ModelSpec, any_model_installed, model_installed, model_path
from .photogimp import install_photogimp, photogimp_installed, remove_photogimp, repair_desktop_integration
from .plan import InstallPlan, PlannedAction, WizardStep
from .plugins import batcher_installed, install_batcher, install_segany_plugin, remove_batcher, remove_segany_plugin, segany_plugin_installed, write_segany_plugin_settings
from .sam3 import download_sam3, remove_sam3, sam3_failure_message
from .sam_backend import backend_ready, bridge_self_test, install_sam3_transformers, install_sam_backend, remove_sam_backend, venv_exists, write_sam_info
from .util import _self_destruct_if_ephemeral
from typing import Optional
import math
import os
import queue
import shutil
import subprocess
import sys
import threading
import webbrowser

# ===========================================================================
# Everything below this line is the optional GUI. None of the functions
# above import tkinter, so `python3 lazygimp.py status` (etc.) works fine
# on a headless box with no Tk installed at all — see the CLI section
# further down and main() at the very end.
# ===========================================================================

if _TK_OK:
    # --- dark theme palette -------------------------------------------------
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
    DANGER = "#ee5a5f"
    DANGER_HOVER = "#f27478"
    WARNING = "#f2a93c"
    DISABLED_BG = "#34363c"
    DISABLED_TEXT = "#6d7076"

    # ------------------------------------------------------------------
    # Small monochrome vector icons — one geometry definition per icon
    # against a tiny backend-agnostic painter, targeting either a Tk
    # Canvas (no anti-aliasing) or a Pillow surface rendered at 4x and
    # downsampled (genuinely anti-aliased). Pillow stays optional so the
    # GUI has no hard dependency beyond Tkinter itself.
    # ------------------------------------------------------------------

    class _Painter:
        def __init__(self, target, pil=False):
            self.target = target
            self.pil = pil

        def line(self, pts, color, width=2):
            if self.pil:
                self.target.line(pts, fill=color, width=max(1, round(width)), joint="curve")
            else:
                self.target.create_line(*pts, fill=color, width=width, capstyle="round", joinstyle="round")

        def polygon(self, pts, color=None, outline=None, width=2):
            if self.pil:
                if color is not None:
                    self.target.polygon(pts, fill=color)
                if outline is not None:
                    self.target.polygon(pts, outline=outline, width=max(1, round(width)))
            else:
                self.target.create_polygon(*pts, fill=color or "", outline=outline or "", width=width)

        def rect(self, x1, y1, x2, y2, color=None, outline=None, width=2, radius=0):
            if self.pil:
                if radius > 0:
                    self.target.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=color, outline=outline,
                                                   width=max(1, round(width)))
                else:
                    self.target.rectangle([x1, y1, x2, y2], fill=color, outline=outline, width=max(1, round(width)))
            else:
                self.target.create_rectangle(x1, y1, x2, y2, fill=color or "", outline=outline or "", width=width)

        def oval(self, x1, y1, x2, y2, color=None, outline=None, width=2):
            if self.pil:
                self.target.ellipse([x1, y1, x2, y2], fill=color, outline=outline, width=max(1, round(width)))
            else:
                self.target.create_oval(x1, y1, x2, y2, fill=color or "", outline=outline or "", width=width)

        def arc(self, x1, y1, x2, y2, start, extent, color, width=2):
            if self.pil:
                self.target.arc([x1, y1, x2, y2], start=-(start + extent), end=-start, fill=color,
                                 width=max(1, round(width)))
            else:
                self.target.create_arc(x1, y1, x2, y2, start=start, extent=extent, style="arc", outline=color,
                                        width=width)

    def _paint_icon(p: _Painter, cx, cy, kind, color, s, frame=0):
        w = max(1.6, s * 0.16)
        if kind == "gear":
            outer_r, inner_r = s, s * 0.6
            tooth_half = s * 0.42
            for i in range(8):
                ang = math.radians(i * 45)
                ca, sa = math.cos(ang), math.sin(ang)
                corners = []
                for rr, tt in ((inner_r, -tooth_half), (outer_r, -tooth_half), (outer_r, tooth_half),
                               (inner_r, tooth_half)):
                    corners += [cx + rr * ca - tt * sa, cy + rr * sa + tt * ca]
                p.polygon(corners, color)
            p.oval(cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r, outline=color, width=s * 0.3)
        elif kind == "bolt":
            p.polygon([
                cx + s * 0.15, cy - s, cx - s * 0.65, cy + s * 0.1, cx - s * 0.05, cy + s * 0.1,
                cx - s * 0.15, cy + s, cx + s * 0.65, cy - s * 0.1, cx + s * 0.05, cy - s * 0.1,
            ], color)
        elif kind == "link":
            rx, ry, offset = s * 0.55, s * 0.4, s * 0.32
            ring_w = max(2.0, s * 0.24)
            p.oval(cx - offset - rx, cy - ry, cx - offset + rx, cy + ry, outline=color, width=ring_w)
            p.oval(cx + offset - rx, cy - ry, cx + offset + rx, cy + ry, outline=color, width=ring_w)
        elif kind == "trash":
            top, bottom = cy - s * 0.55, cy + s * 0.95
            top_half, bottom_half = s * 0.62, s * 0.5
            p.polygon([cx - top_half, top, cx + top_half, top, cx + bottom_half, bottom, cx - bottom_half, bottom],
                       outline=color, width=w)
            p.line([cx - s * 0.85, top, cx + s * 0.85, top], color, width=w)
            p.line([cx - s * 0.28, top, cx - s * 0.28, top - s * 0.28], color, width=w)
            p.line([cx + s * 0.28, top, cx + s * 0.28, top - s * 0.28], color, width=w)
            p.line([cx - s * 0.28, top - s * 0.28, cx + s * 0.28, top - s * 0.28], color, width=w)
            rib_w = max(1.4, s * 0.1)
            for fx in (-0.26, 0, 0.26):
                p.line([cx + fx * s, top + s * 0.2, cx + fx * s * 0.85, bottom - s * 0.12], color, width=rib_w)
        elif kind == "install":
            p.line([cx - s, cy + s * 0.15, cx - s, cy + s], color, width=w)
            p.line([cx - s, cy + s, cx + s, cy + s], color, width=w)
            p.line([cx + s, cy + s * 0.15, cx + s, cy + s], color, width=w)
            p.line([cx - s * 0.55, cy - s * 0.15, cx - s * 0.05, cy + s * 0.35, cx + s * 0.7, cy - s * 0.55],
                   color, width=max(2.0, s * 0.2))
        elif kind == "folder":
            p.polygon([
                cx - s, cy - s * 0.35, cx - s * 0.32, cy - s * 0.35, cx - s * 0.15, cy - s * 0.15,
                cx + s, cy - s * 0.15, cx + s, cy + s * 0.55, cx - s, cy + s * 0.55,
            ], color)
        elif kind == "undo":
            p.arc(cx - s * 0.8, cy - s * 0.75, cx + s * 0.8, cy + s * 0.75, 200, 250, color, width=w)
            p.polygon([cx - s * 0.9, cy - s * 0.1, cx - s * 0.32, cy - s * 0.52, cx - s * 0.42, cy + s * 0.08], color)
        elif kind == "warn":
            p.polygon([cx, cy - s, cx - s, cy + s * 0.7, cx + s, cy + s * 0.7], outline=color, width=w)
            p.line([cx, cy - s * 0.15, cx, cy + s * 0.28], color, width=w)
            p.oval(cx - 1.4, cy + s * 0.42, cx + 1.4, cy + s * 0.5, color)
        elif kind == "info":
            p.oval(cx - s * 0.85, cy - s * 0.85, cx + s * 0.85, cy + s * 0.85, outline=color, width=w)
            p.line([cx, cy - s * 0.05, cx, cy + s * 0.55], color, width=w)
            p.oval(cx - 1.2, cy - s * 0.55, cx + 1.2, cy - s * 0.3, color)
        elif kind == "check":
            p.line([cx - s * 0.7, cy, cx - s * 0.1, cy + s * 0.6, cx + s * 0.8, cy - s * 0.6], color,
                   width=max(2.0, s * 0.22))
        elif kind == "x":
            w2 = max(1.8, s * 0.2)
            p.line([cx - s * 0.6, cy - s * 0.6, cx + s * 0.6, cy + s * 0.6], color, width=w2)
            p.line([cx - s * 0.6, cy + s * 0.6, cx + s * 0.6, cy - s * 0.6], color, width=w2)
        elif kind == "refresh":
            p.arc(cx - s * 0.8, cy - s * 0.8, cx + s * 0.8, cy + s * 0.8, 30, 260, color, width=w)
            p.polygon([cx + s * 0.55, cy - s * 0.85, cx + s * 0.95, cy - s * 0.35, cx + s * 0.4, cy - s * 0.25],
                       color)
        elif kind == "spinner":
            start = (frame * 30) % 360
            p.arc(cx - s, cy - s, cx + s, cy + s, start, 110, color, width=w)
        elif kind == "box":
            p.rect(cx - s, cy - s * 0.55, cx + s, cy + s, outline=color, width=w, radius=s * 0.12)
            p.line([cx - s, cy - s * 0.05, cx + s, cy - s * 0.05], color, width=w)
            p.line([cx, cy - s * 0.55, cx, cy + s], color, width=w)

    _ICON_PHOTO_CACHE: dict = {}

    def render_icon_photo(kind, color, size=18, frame=0):
        if not _PIL_OK:
            return None
        key = (kind, color, size, frame)
        cached = _ICON_PHOTO_CACHE.get(key)
        if cached is not None:
            return cached
        big = size * 4
        img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        _paint_icon(_Painter(draw, pil=True), big / 2, big / 2, kind, color, big * 0.36, frame)
        photo = ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))
        _ICON_PHOTO_CACHE[key] = photo
        return photo

    def draw_icon(canvas, cx, cy, kind, color=TEXT, s=7, frame=0):
        _paint_icon(_Painter(canvas, pil=False), cx, cy, kind, color, s, frame)

    def blit_icon(canvas, cx, cy, kind, color=TEXT, size=18, frame=0):
        photo = render_icon_photo(kind, color, size, frame)
        if photo is not None:
            canvas.create_image(cx, cy, image=photo)
        else:
            draw_icon(canvas, cx, cy, kind, color=color, s=size * 0.42, frame=frame)

    def icon_canvas(parent, kind, color=TEXT, size=18, bg=None):
        c = tk.Canvas(parent, width=size, height=size, highlightthickness=0, bd=0, bg=bg or parent["bg"])
        blit_icon(c, size / 2, size / 2, kind, color=color, size=size)
        return c

    # ------------------------------------------------------------------
    # Rounded-corner widgets
    # ------------------------------------------------------------------

    def _rounded_points(x1, y1, x2, y2, r):
        r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
        return [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]

    def draw_round_rect(canvas, x1, y1, x2, y2, r=16, **kwargs):
        return canvas.create_polygon(_rounded_points(x1, y1, x2, y2, r), smooth=True, **kwargs)

    def autowrap_label(parent, text, fg=TEXT_MUTED, bg=None, font=("Sans", 9), justify="left"):
        lbl = tk.Label(parent, text=text, fg=fg, bg=bg or parent["bg"], font=font, justify=justify, anchor="w")

        def _resize(event):
            new_wrap = max(60, event.width - 4)
            if lbl.cget("wraplength") != new_wrap:
                lbl.configure(wraplength=new_wrap)

        lbl.bind("<Configure>", _resize)
        return lbl

    def flatten_entry(entry, bg=CARD_BG):
        try:
            entry.configure(highlightthickness=0, highlightbackground=bg, highlightcolor=bg)
        except tk.TclError:
            pass

    def rating_widget(parent, quality, speed, bg=CARD_BG):
        row = tk.Frame(parent, bg=bg)

        def dots(container, score):
            for i in range(5):
                c = tk.Canvas(container, width=10, height=10, highlightthickness=0, bd=0, bg=bg)
                c.pack(side="left", padx=1)
                color = ACCENT if i < score else CARD_BORDER
                c.create_oval(1, 1, 9, 9, fill=color, outline="")

        tk.Label(row, text="Quality", bg=bg, fg=TEXT_MUTED, font=("Sans", 9)).pack(side="left", padx=(0, 4))
        qf = tk.Frame(row, bg=bg)
        qf.pack(side="left", padx=(0, 16))
        dots(qf, quality)
        tk.Label(row, text="Speed", bg=bg, fg=TEXT_MUTED, font=("Sans", 9)).pack(side="left", padx=(0, 4))
        sf = tk.Frame(row, bg=bg)
        sf.pack(side="left")
        dots(sf, speed)
        return row

    class RoundedButton(tk.Canvas):
        _PALETTE = {
            "primary": (ACCENT, ACCENT_HOVER, ACCENT_TEXT),
            "success": (SUCCESS, SUCCESS_HOVER, "#08210f"),
            "danger": (DANGER, DANGER_HOVER, "#2b0b0c"),
            "secondary": (CARD_BORDER, "#3f424a", TEXT),
        }

        def __init__(self, parent, text, command=None, variant="secondary", icon=None,
                     width=None, height=34, radius=13, font=("Sans", 10, "bold"), bg=None, on_blocked=None):
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
            self.bind("<Configure>", lambda e: self._draw())
            self.bind("<Enter>", lambda e: self._set_hover(True))
            self.bind("<Leave>", lambda e: self._set_hover(False))
            self.bind("<Button-1>", self._on_click)

        def _set_hover(self, hover):
            if self._enabled:
                self._hover = hover
                self._draw()
                self.configure(cursor="hand2" if hover else "")

        def _on_click(self, _event=None):
            if self._enabled:
                if self.command:
                    self.command()
            elif self.on_blocked:
                self.on_blocked()

        def set_enabled(self, enabled: bool):
            self._enabled = enabled
            self._hover = False
            self._draw()

        def set_text(self, text: str):
            self.text = text
            self._draw()

        def set_variant(self, variant: str):
            self.variant = variant
            self._draw()

        def start_loading(self, base_text="Working"):
            if self._loading:
                return
            self._loading = True
            self._loading_base = base_text
            self._loading_frame = 0
            self._enabled = False
            self._animate()

        def stop_loading(self):
            self._loading = False

        def _animate(self):
            if not self._loading or not self.winfo_exists():
                return
            self._loading_frame += 1
            self._draw()
            self.after(100, self._animate)

        def _draw(self):
            self.delete("all")
            w = max(self.winfo_width(), self._fixed_width or 1, 10)
            h = int(self["height"])
            base_fill, hover_fill, fg = self._PALETTE[self.variant]
            if not self._enabled and not self._loading:
                fill, fg = DISABLED_BG, DISABLED_TEXT
            elif self._loading:
                fill = base_fill
            elif self._hover:
                fill = hover_fill
            else:
                fill = base_fill
            draw_round_rect(self, 1, 1, w - 1, h - 1, self.radius, fill=fill, outline="")
            if self._loading:
                blit_icon(self, 22, h / 2, "spinner", color=fg, size=16, frame=self._loading_frame % 12)
                self.create_text(38, h / 2, text=self._loading_base + "…", fill=fg, font=self.font, anchor="w")
            elif self.icon:
                blit_icon(self, 22, h / 2, self.icon, color=fg, size=17)
                self.create_text(38, h / 2, text=self.text, fill=fg, font=self.font, anchor="w")
            else:
                self.create_text(w / 2, h / 2, text=self.text, fill=fg, font=self.font, anchor="center")

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
            self.canvas.delete("card_bg")
            if w > 4 and h > 4:
                draw_round_rect(self.canvas, 1, 1, w - 1, h - 1, self._radius,
                                 fill=self._bg, outline=self._border, width=1, tags="card_bg")
                self.canvas.tag_lower("card_bg")

        def finalize(self):
            self.update_idletasks()
            self._on_body_configure()
            self._on_canvas_configure()

    class ProgressBar(tk.Canvas):
        def __init__(self, parent, width=200, height=7, bg=None, track=CARD_BORDER, fill=ACCENT):
            super().__init__(parent, width=width, height=height, highlightthickness=0, bd=0, bg=bg or parent["bg"])
            self._frac = 0.0
            self._track, self._fillc = track, fill
            self.bind("<Configure>", lambda e: self._draw())

        def set_fraction(self, frac: float):
            self._frac = max(0.0, min(1.0, frac))
            self._draw()

        def _draw(self):
            self.delete("all")
            w = self.winfo_width() or int(self["width"])
            h = int(self["height"])
            draw_round_rect(self, 0, 0, w, h, h / 2, fill=self._track, outline="")
            fw = w * self._frac
            if fw >= h:
                draw_round_rect(self, 0, 0, fw, h, h / 2, fill=self._fillc, outline="")

    class ModernCheckbox(tk.Canvas):
        def __init__(self, parent, variable, command=None, size=20, bg=None):
            super().__init__(parent, width=size, height=size, highlightthickness=0, bd=0, bg=bg or parent["bg"])
            self.variable = variable
            self.command = command
            self.size = size
            self._trace_id = variable.trace_add("write", lambda *_a: self._draw())
            self.bind("<Configure>", lambda e: self._draw())
            self.bind("<Button-1>", self._toggle)
            self.bind("<Enter>", lambda e: self.configure(cursor="hand2"))
            self.bind("<Destroy>", self._on_destroy)
            self._draw()

        def _toggle(self, _event=None):
            self.variable.set(not self.variable.get())
            if self.command:
                self.command()

        def _on_destroy(self, _event=None):
            try:
                self.variable.trace_remove("write", self._trace_id)
            except Exception:
                pass

        def _draw(self):
            if not self.winfo_exists():
                return
            self.delete("all")
            s = self.size
            if self.variable.get():
                draw_round_rect(self, 1, 1, s - 1, s - 1, 6, fill=ACCENT, outline="")
                blit_icon(self, s / 2, s / 2, "check", color=ACCENT_TEXT, size=max(10, int(s * 0.75)))
            else:
                draw_round_rect(self, 1.5, 1.5, s - 1.5, s - 1.5, 6, fill="", outline=CARD_BORDER, width=2)

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

    class ScrollableFrame(tk.Frame):
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
            self._wheel_bound_ids: set = set()
            self.bind_mousewheel_recursive()

        def bind_mousewheel_recursive(self, widget=None):
            widget = widget or self.inner
            if id(widget) not in self._wheel_bound_ids:
                widget.bind("<MouseWheel>", self._on_wheel, add="+")
                widget.bind("<Button-4>", self._on_up, add="+")
                widget.bind("<Button-5>", self._on_down, add="+")
                self._wheel_bound_ids.add(id(widget))
            for child in widget.winfo_children():
                self.bind_mousewheel_recursive(child)

        def _on_wheel(self, event):
            if self.canvas.winfo_exists():
                self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

        def _on_up(self, event):
            if self.canvas.winfo_exists():
                self.canvas.yview_scroll(-2, "units")

        def _on_down(self, event):
            if self.canvas.winfo_exists():
                self.canvas.yview_scroll(2, "units")

    def page_header(parent, title):
        tk.Label(parent, text=title, bg=BG, fg=TEXT, font=("Sans", 18, "bold")).pack(anchor="w", pady=(0, 16))

    def callout(parent, text, tone="info"):
        colors = {"info": ("#16303a", "#7fd0f0"), "warn": ("#3a2e14", WARNING), "ok": ("#123522", SUCCESS)}
        icon_kind = {"info": "info", "warn": "warn", "ok": "check"}[tone]
        bgc, fg = colors[tone]
        card = RoundedCard(parent, bg=bgc, border=bgc, radius=14, pad=12)
        card.pack(fill="x", pady=(4, 12))
        row = tk.Frame(card.body, bg=bgc)
        row.pack(fill="x")
        icon_canvas(row, icon_kind, color=fg, size=18, bg=bgc).pack(side="left", padx=(0, 8), anchor="n")
        autowrap_label(row, text, fg=fg, bg=bgc, font=("Sans", 9)).pack(side="left", fill="x", expand=True)
        card.finalize()
        return card

    def themed_dialog(root, title, message, kind="info"):
        win = tk.Toplevel(root)
        win.configure(bg=BG)
        win.title(title)
        win.transient(root)
        win.resizable(False, False)
        card = RoundedCard(win, radius=18, pad=20, width=380)
        card.pack(padx=2, pady=2)
        tk.Label(card.body, text=title, bg=CARD_BG, fg=TEXT, font=("Sans", 13, "bold")).pack(anchor="w")
        autowrap_label(card.body, message, fg=TEXT_MUTED, bg=CARD_BG, font=("Sans", 10)).pack(
            anchor="w", fill="x", pady=(10, 18))
        result = {"value": None}
        btns = tk.Frame(card.body, bg=CARD_BG)
        btns.pack(anchor="e")

        def close(v):
            result["value"] = v
            win.destroy()

        if kind == "confirm":
            RoundedButton(btns, "Cancel", variant="secondary", width=90, command=lambda: close(False)).pack(
                side="left", padx=(0, 8))
            RoundedButton(btns, "Confirm", variant="danger", icon="trash", width=120,
                          command=lambda: close(True)).pack(side="left")
        else:
            RoundedButton(btns, "OK", variant="primary", width=90, command=lambda: close(True)).pack(side="left")
        card.finalize()
        win.update_idletasks()
        rx, ry, rw, rh = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{rx + max(0, (rw - ww) // 2)}+{ry + max(0, (rh - wh) // 2)}")
        win.grab_set()
        win.wait_window()
        return result["value"]

    def themed_info(root, title, message):
        themed_dialog(root, title, message, kind="info")

    def themed_confirm(root, title, message) -> bool:
        return bool(themed_dialog(root, title, message, kind="confirm"))

    def show_snackbar(app, message: str, tone: str = "warn", duration_ms: int = 2200):
        colors = {"warn": ("#3a2e14", WARNING), "error": ("#3a1414", DANGER), "ok": ("#123522", SUCCESS)}
        bgc, fg = colors.get(tone, colors["warn"])
        root = app.root
        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=root["bg"])
        card = RoundedCard(win, bg=bgc, border=bgc, radius=14, pad=14)
        card.pack()
        row = tk.Frame(card.body, bg=bgc)
        row.pack()
        icon_canvas(row, "warn" if tone == "warn" else ("x" if tone == "error" else "check"), color=fg, size=16,
                    bg=bgc).pack(side="left", padx=(0, 8))
        tk.Label(row, text=message, bg=bgc, fg=fg, font=("Sans", 10, "bold")).pack(side="left")
        card.finalize()
        win.update_idletasks()
        x = root.winfo_rootx() + max(0, (root.winfo_width() - win.winfo_reqwidth()) // 2)
        y = root.winfo_rooty() + root.winfo_height() - 110
        win.geometry(f"+{x}+{y}")
        win.after(duration_ms, lambda: win.destroy() if win.winfo_exists() else None)

    # ------------------------------------------------------------------
    # SAM model download queue — one model downloads at a time, everything
    # else Install-clicked while that's running just joins the queue.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # GUI password prompt for the package-manager (sudo) install path.
    # ------------------------------------------------------------------

    class TkPasswordPrompt:
        def __init__(self, root):
            self.root = root

        def __call__(self, prompt_text: str) -> str:
            result: dict = {}
            done = threading.Event()

            def ask():
                result["pw"] = simpledialog.askstring(
                    "Password required",
                    f"{prompt_text}\n\n(needed to install/remove system packages; this is your normal "
                    "login password, sent straight to sudo, never stored)",
                    show="*", parent=self.root,
                )
                done.set()

            self.root.after(0, ask)
            done.wait()
            return result.get("pw") or ""

    # ------------------------------------------------------------------
    # What's on this system, in the uninstall screen's vocabulary.
    # ------------------------------------------------------------------

    def detect_targets() -> list[tuple[str, str, str]]:
        targets = []
        distro = detect_distro()
        if gimp_native_installed():
            targets.append(("package-manager", "Native GIMP (+ G'MIC) packages", f"installed via {distro}"))
        if appimage_present():
            targets.append(("appimage", "GIMP AppImage", APPIMAGE_DIR))
        if photogimp_installed():
            targets.append(("photogimp", "PhotoGIMP configuration layer",
                             "icons, desktop entry, shortcuts, splash screen, UI layout"))
        if batcher_installed():
            targets.append(("batcher", "Batcher plug-in", "plug-ins/batcher — only this folder"))
        if segany_plugin_installed() or os.path.isdir(BACKEND_DIR):
            targets.append(("sam", "SAM plug-in + Python backend + models",
                             f"plug-ins/seganyplugin and {BACKEND_DIR} — only these"))
        return targets

    def anything_installed() -> bool:
        return bool(detect_targets())

    # ------------------------------------------------------------------
    # The app itself. One landing screen (Quick setup / Manage / Uninstall),
    # a paginated setup wizard (GIMP > PhotoGIMP > G'MIC > SAM > Batcher >
    # Review) that only ever *queues* actions into an InstallPlan, and one
    # shared install-progress screen that actually runs a plan — whether it
    # came from the wizard's Review page or from Quick Setup's own prefilled
    # plan. Every wizard page is fully self-contained and re-reads live
    # filesystem state on every render, exactly so "I already have GIMP, I just
    # want to add G'MIC" (or Batcher, or SAM) is a single click.
    # ------------------------------------------------------------------

    class LazyGimpApp:
        def __init__(self, root):
            self.root = root
            root.title("LazyGimp installer")
            root.geometry("1040x800")
            root.minsize(920, 660)
            root.configure(bg=BG)
            self._style()

            self.log_queue: "queue.Queue[str]" = queue.Queue()
            self.busy = False
            self.current_job = None
            self.current_screen = "landing"
            self.hw = detect_hardware()
            self.password_prompt = TkPasswordPrompt(root)

            # Wizard/plan state — (re)initialized fresh by show_wizard()/
            # show_install_progress() each time either screen is entered.
            self.plan = InstallPlan()
            self.wizard_steps: list[WizardStep] = []
            self.wizard_index = 0
            self.plan_actions: list[PlannedAction] = []
            self._exec_log_lines: list[str] = []

            self.root_frame = tk.Frame(root, bg=BG)
            self.root_frame.pack(fill="both", expand=True)
            self.show_landing()
            self.root.after(150, self._drain_log_queue)

        # ---- generic Tk plumbing (theme, status bar, background jobs) ----

        def _style(self):
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass
            style.configure("TEntry", fieldbackground="#303237", foreground=TEXT, insertcolor=TEXT,
                             bordercolor="#303237", lightcolor="#303237", darkcolor="#303237",
                             borderwidth=0, relief="flat", padding=6)
            style.configure("TCombobox", fieldbackground="#303237", background="#303237", foreground=TEXT,
                             arrowcolor=TEXT, bordercolor="#303237", lightcolor="#303237", darkcolor="#303237",
                             borderwidth=0, relief="flat", padding=6)
            style.map("TCombobox", fieldbackground=[("readonly", "#303237")], foreground=[("readonly", TEXT)],
                      background=[("readonly", "#303237")])
            style.layout("Modern.Vertical.TScrollbar", [
                ("Vertical.Scrollbar.trough", {"children": [
                    ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"}),
                ], "sticky": "ns"}),
            ])
            style.configure("Modern.Vertical.TScrollbar", gripcount=0, background="#4a4d54",
                             troughcolor=BG, bordercolor=BG, lightcolor="#4a4d54", darkcolor="#4a4d54",
                             relief="flat", width=8, arrowsize=0)
            style.configure("TSeparator", background=CARD_BORDER)
            self.root.option_add("*TCombobox*Listbox.background", "#303237")
            self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
            self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
            self.root.option_add("*TCombobox*Listbox.selectForeground", ACCENT_TEXT)

        def _build_status_bar(self, parent):
            bar = tk.Frame(parent, bg=BG)
            bar.pack(fill="x", padx=26, pady=(0, 14), side="bottom")
            self.status_spinner = tk.Canvas(bar, width=16, height=16, highlightthickness=0, bd=0, bg=BG)
            self.status_spinner.pack(side="left", padx=(0, 8))
            self.status_var = tk.StringVar(value="Full log is also printed to the terminal this was launched from.")
            tk.Label(bar, textvariable=self.status_var, bg=BG, fg=TEXT_MUTED, font=("Sans", 9), anchor="w").pack(
                side="left", fill="x", expand=True)
            self._status_spin_frame = 0
            self._status_spinning = False

        def _spin_status(self):
            if not self._status_spinning or not self.status_spinner.winfo_exists():
                return
            self.status_spinner.delete("all")
            blit_icon(self.status_spinner, 8, 8, "spinner", color=ACCENT, size=14, frame=self._status_spin_frame % 12)
            self._status_spin_frame += 1
            self.root.after(90, self._spin_status)

        _STATUS_MAX_CHARS = 160

        def _drain_log_queue(self):
            msgs = []
            try:
                while True:
                    msgs.append(self.log_queue.get_nowait())
            except queue.Empty:
                pass
            if msgs:
                last = msgs[-1]
                if hasattr(self, "status_var") and self.status_var is not None:
                    clean = " ".join(last.replace("\r", " ").split())
                    if len(clean) > self._STATUS_MAX_CHARS:
                        clean = "…" + clean[-(self._STATUS_MAX_CHARS - 1):]
                    try:
                        self.status_var.set(clean)
                    except tk.TclError:
                        pass
                if self.current_screen == "installing":
                    self._exec_log_lines.extend(msgs)
                    del self._exec_log_lines[:-500]
                    for m in msgs:
                        self._append_exec_log(m)
            self.root.after(150, self._drain_log_queue)

        def set_busy(self, busy: bool):
            self.busy = busy
            if not hasattr(self, "status_spinner") or not self.status_spinner.winfo_exists():
                return
            self._status_spinning = busy
            if busy:
                self._spin_status()
            else:
                self.status_spinner.delete("all")

        def run_in_background(self, fn, on_done=None):
            if self.busy:
                themed_info(self.root, "Busy", "Another operation is already running.")
                return
            self.set_busy(True)
            job = Job(self.log_queue, password_prompt=self.password_prompt)
            self.current_job = job

            def wrapper():
                try:
                    fn(job)
                except Exception as e:
                    job.log(f"ERROR: {e}")
                finally:
                    if self.current_job is job:
                        self.current_job = None
                    self.root.after(0, lambda: (self.set_busy(False), (on_done() if on_done else None)))

            threading.Thread(target=wrapper, daemon=True).start()

        def cancel_current_job(self):
            if self.current_job is not None:
                self.current_job.log("Cancel requested by user — stopping...")
                self.current_job.cancel()

        # ---- landing screen -----------------------------------------------

        def show_landing(self):
            self.current_screen = "landing"
            for w in self.root_frame.winfo_children():
                w.destroy()

            wrap = tk.Frame(self.root_frame, bg=BG)
            wrap.pack(fill="both", expand=True)
            center = tk.Frame(wrap, bg=BG)
            center.place(relx=0.5, rely=0.4, anchor="center")

            tk.Label(center, text="LazyGimp", bg=BG, fg=TEXT, font=("Sans", 28, "bold")).pack()
            tk.Label(center, text="GIMP + PhotoGIMP + G'MIC + SAM + Batcher, ready to use",
                     bg=BG, fg=TEXT_MUTED, font=("Sans", 11)).pack(pady=(2, 10))
            distro = detect_distro()
            method_note = f"Recommended for this system: {'package manager (' + distro + ')' if distro else 'AppImage'}"
            tk.Label(center, text=method_note, bg=BG, fg=TEXT_MUTED, font=("Sans", 9)).pack(pady=(0, 24))

            row = tk.Frame(center, bg=BG)
            row.pack()
            CARD_W, CARD_H = 320, 255

            manage = RoundedCard(row, radius=20, pad=24, width=CARD_W, height=CARD_H)
            manage.grid(row=0, column=0, padx=10)
            title_row = tk.Frame(manage.body, bg=CARD_BG)
            title_row.pack(anchor="w")
            icon_canvas(title_row, "gear", color=TEXT, size=20).pack(side="left", padx=(0, 8))
            tk.Label(title_row, text="Manage components", bg=CARD_BG, fg=TEXT, font=("Sans", 14, "bold")).pack(
                side="left")
            autowrap_label(
                manage.body,
                "Walk through PhotoGIMP, G'MIC, SAM and Batcher one page at a time, queue exactly what you "
                "want installed or removed, then run the whole checklist in one pass.",
                bg=CARD_BG, font=("Sans", 9),
            ).pack(anchor="w", fill="x", pady=(8, 16))
            open_btn = RoundedButton(manage.body, "Open", variant="secondary", width=272, height=40,
                                      command=self.show_wizard)
            open_btn.pack(anchor="w", side="bottom")
            manage.finalize()
            bind_click_recursive(manage, self.show_wizard, skip=(open_btn,))

            auto = RoundedCard(row, radius=20, pad=24, width=CARD_W, height=CARD_H)
            auto.grid(row=0, column=1, padx=10)
            title_row2 = tk.Frame(auto.body, bg=CARD_BG)
            title_row2.pack(anchor="w")
            icon_canvas(title_row2, "bolt", color=TEXT, size=20).pack(side="left", padx=(0, 8))
            tk.Label(title_row2, text="Quick setup", bg=CARD_BG, fg=TEXT, font=("Sans", 14, "bold")).pack(side="left")
            autowrap_label(
                auto.body,
                "Installs everything still missing, in order: PhotoGIMP, G'MIC, SAM (with a model picked "
                "for your hardware) and Batcher. Already-installed pieces are left alone.",
                bg=CARD_BG, font=("Sans", 9),
            ).pack(anchor="w", fill="x", pady=(8, 16))
            start_btn = RoundedButton(auto.body, "Start", variant="primary", width=272, height=40,
                                       command=self.start_quick_setup)
            start_btn.pack(anchor="w", side="bottom")
            auto.finalize()
            bind_click_recursive(auto, self.start_quick_setup, skip=(start_btn,))

            if anything_installed():
                btn_row = tk.Frame(center, bg=BG)
                btn_row.pack(pady=(18, 0))
                if find_gimp_command():
                    RoundedButton(btn_row, "Close installer and open GIMP", variant="primary", icon="bolt", width=340,
                                  command=self.launch_gimp_and_close).pack(pady=(0, 10))
                RoundedButton(btn_row, "Uninstall from this system", variant="danger", icon="trash", width=340,
                              command=self.show_uninstall_confirm).pack()

        def launch_gimp_and_close(self):
            cmd = find_gimp_command()
            if not cmd:
                show_snackbar(self, "GIMP not found", tone="error")
                return
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            except Exception as e:
                show_snackbar(self, f"Couldn't launch GIMP: {e}", tone="error")
                return
            self.root.destroy()

        # ---- quick setup: everything missing, in priority order -----------

        def start_quick_setup(self):
            if self.busy:
                themed_info(self.root, "Busy", "Setup is already running.")
                return
            # One-click setup is just a prefilled plan handed straight to the
            # same executor the wizard's Review page uses — no separate code
            # path, no separate "what to install" logic to keep in sync.
            self.show_install_progress(self._build_quick_setup_plan())

        def _build_quick_setup_plan(self) -> list["PlannedAction"]:
            actions: list[PlannedAction] = []

            if not find_gimp_binary() and not appimage_present():
                if detect_distro():
                    actions.append(PlannedAction(
                        "gimp:install", "Install GIMP (package manager)", "install",
                        lambda job: install_gimp_package_manager(job, include_gmic=False)))
                else:
                    actions.append(PlannedAction(
                        "gimp:install", "Install GIMP (AppImage)", "install",
                        lambda job: install_gimp_appimage(job)))

            if not photogimp_installed():
                actions.append(PlannedAction(
                    "photogimp:install", "Install PhotoGIMP", "install",
                    lambda job: install_photogimp(job, gimp_command=(find_gimp_command() or [None])[0])))

            if gmic_available_on_this_release() and not gmic_installed():
                actions.append(PlannedAction("gmic:install", "Install G'MIC", "install",
                                              lambda job: install_gmic_only(job)))

            if not segany_plugin_installed():
                actions.append(PlannedAction("sam_plugin:install", "Install the SAM plug-in", "install",
                                              lambda job: install_segany_plugin(job)))

            if not backend_ready():
                actions.append(PlannedAction(
                    "sam_backend:install", "Set up the SAM Python backend", "install",
                    lambda job: install_sam_backend(job, recommended_torch_index(self.hw))))

            if not any_model_installed():
                rec = MODEL_BY_KEY[recommended_model_key(self.hw)]

                def install_recommended(job: Job, rec=rec):
                    if job.download(rec.url, model_path(rec), job.cancel_event):
                        write_segany_plugin_settings(rec)
                        write_sam_info([rec.key])
                        bridge_self_test(job, rec)

                actions.append(PlannedAction(f"sam_model:{rec.key}:install",
                                              f"Download the recommended SAM model: {rec.label}",
                                              "install", install_recommended))

            if not batcher_installed():
                actions.append(PlannedAction("batcher:install", "Install Batcher", "install",
                                              lambda job: install_batcher(job)))

            return actions

        # ---- uninstall screen ----------------------------------------------

        def show_uninstall_confirm(self):
            self.current_screen = "uninstall"
            for w in self.root_frame.winfo_children():
                w.destroy()

            wrap = tk.Frame(self.root_frame, bg=BG)
            wrap.pack(fill="both", expand=True)
            self._build_status_bar(wrap)

            content = tk.Frame(wrap, bg=BG)
            content.pack(fill="both", expand=True, padx=40, pady=30)

            title_row = tk.Frame(content, bg=BG)
            title_row.pack(anchor="w")
            icon_canvas(title_row, "trash", color=DANGER, size=24).pack(side="left", padx=(0, 10))
            tk.Label(title_row, text="Uninstall LazyGimp", bg=BG, fg=TEXT, font=("Sans", 20, "bold")).pack(side="left")
            tk.Label(content, text="Choose what to remove. Personal GIMP files (brushes, scripts, settings not "
                                    "shipped by PhotoGIMP) are never touched — only what LazyGimp itself installed.",
                     bg=BG, fg=TEXT_MUTED, font=("Sans", 10), wraplength=760, justify="left").pack(anchor="w",
                                                                                                     pady=(4, 18))

            targets = detect_targets()
            btns = tk.Frame(content, bg=BG)
            btns.pack(fill="x", pady=(20, 0), side="bottom")

            card = RoundedCard(content)
            card.pack(fill="both", expand=True)
            check_vars: list[tuple] = []
            if targets:
                for key, name, detail in targets:
                    row = tk.Frame(card.body, bg=CARD_BG)
                    row.pack(fill="x", pady=7, anchor="w")
                    var = tk.BooleanVar(value=True)
                    ModernCheckbox(row, var, command=lambda: update_confirm_label(), bg=CARD_BG).pack(
                        side="left", padx=(0, 10))
                    icon_canvas(row, "trash", color=DANGER, size=18, bg=CARD_BG).pack(side="left", padx=(0, 10))
                    col = tk.Frame(row, bg=CARD_BG)
                    col.pack(side="left", fill="x", expand=True)
                    tk.Label(col, text=name, bg=CARD_BG, fg=TEXT, font=("Sans", 10, "bold"), anchor="w").pack(
                        anchor="w")
                    autowrap_label(col, detail, fg=TEXT_MUTED, bg=CARD_BG, font=("Sans", 9)).pack(anchor="w",
                                                                                                    fill="x")
                    check_vars.append((var, key))
            else:
                tk.Label(card.body, text="Nothing found to remove.", bg=CARD_BG, fg=TEXT_MUTED).pack(anchor="w")
            card.finalize()

            RoundedButton(btns, "Cancel", variant="secondary", width=110, command=self.show_landing).pack(
                side="left")
            confirm_btn = RoundedButton(btns, "Delete selected", variant="danger", icon="trash", width=200,
                                         command=lambda: self.on_confirm_uninstall(
                                             [k for v, k in check_vars if v.get()]))
            confirm_btn.pack(side="left", padx=8)
            RoundedButton(btns, "Delete all", variant="danger", icon="trash", width=140,
                          command=lambda: self.on_confirm_uninstall([k for _, k in check_vars])).pack(side="left")

            def update_confirm_label():
                n = sum(1 for v, _ in check_vars if v.get())
                confirm_btn.set_text(f"Delete selected ({n})")
                confirm_btn.set_enabled(n > 0)

            update_confirm_label()

        def on_confirm_uninstall(self, keys: list[str]):
            if not keys:
                return
            needs_root = "package-manager" in keys

            def task(job: Job):
                if "photogimp" in keys:
                    remove_photogimp(job)
                if "batcher" in keys:
                    remove_batcher(job)
                if "sam" in keys:
                    remove_segany_plugin(job)
                    remove_sam_backend(job)
                if "appimage" in keys:
                    remove_gimp_appimage(job)
                if "package-manager" in keys:
                    if needs_root:
                        job.log("Removing native packages needs administrator rights — "
                                "a password prompt may appear below.")
                    remove_gimp_package_manager(job)
                job.log("Uninstall finished.")

            self.run_in_background(task, on_done=self.show_landing)

        # ---- manage screen: one card per component, priority order ---------
        # PhotoGIMP > G'MIC > SAM > Batcher, with GIMP itself as the one
        # prerequisite card ahead of all four (per the user's own ordering).

        # ---- paginated setup wizard -----------------------------------------
        # Every page only ever queues PlannedActions into self.plan; nothing
        # here touches disk. The wizard is entered fresh every time (own
        # plan, own step list) so reopening it always reflects current
        # reality — an already-installed component simply renders with
        # Install disabled and Uninstall enabled instead of vanishing.

        _WIZARD_RENDERERS = {
            "gimp": "_wizard_render_gimp",
            "photogimp": "_wizard_render_photogimp",
            "gmic": "_wizard_render_gmic",
            "sam": "_wizard_render_sam",
            "batcher": "_wizard_render_batcher",
            "review": "_wizard_render_review",
        }

        # Which wizard page owns a given plan key, so Review's rows can jump
        # straight back to the page that queued them.
        _WIZARD_KEY_PREFIXES = (
            ("gimp_install_", "gimp"),
            ("photogimp:", "photogimp"),
            ("gmic:", "gmic"),
            ("sam_setup:", "sam"),
            ("sam_model:", "sam"),
            ("sam3:", "sam"),
            ("batcher:", "batcher"),
        )

        def show_wizard(self):
            self.plan = InstallPlan()
            default_choice = list(TORCH_INDEX_URLS.keys())[
                list(TORCH_INDEX_URLS.values()).index(recommended_torch_index(self.hw))]
            self.torch_choice = tk.StringVar(value=default_choice)
            self.hf_token_var = tk.StringVar()
            self.wizard_steps = self._build_wizard_steps()
            self.wizard_index = 0
            self._render_wizard_step()

        def _build_wizard_steps(self) -> list[WizardStep]:
            steps = []
            if not (gimp_native_installed() or appimage_present()):
                steps.append(WizardStep("gimp", "GIMP (prerequisite)", prerequisite=True))
            steps.append(WizardStep("photogimp", "PhotoGIMP"))
            steps.append(WizardStep("gmic", "G'MIC"))
            steps.append(WizardStep("sam", "SAM (segmentation models)"))
            steps.append(WizardStep("batcher", "Batcher"))
            steps.append(WizardStep("review", "Review & install"))
            return steps

        def _wizard_can_advance(self) -> bool:
            step = self.wizard_steps[self.wizard_index]
            if step.key == "gimp":
                return self.plan.has("gimp_install_pm") or self.plan.has("gimp_install_appimage")
            return True

        def _wizard_advance(self):
            if not self._wizard_can_advance():
                return
            self.wizard_index += 1
            self._render_wizard_step()

        def _wizard_back(self):
            if self.wizard_index == 0:
                if len(self.plan) and not themed_confirm(
                        self.root, "Leave setup", "Discard your selections and go back to the start screen?"):
                    return
                self.show_landing()
                return
            self.wizard_index -= 1
            self._render_wizard_step()

        def _wizard_jump_to_step(self, step_key: str):
            for i, step in enumerate(self.wizard_steps):
                if step.key == step_key:
                    self.wizard_index = i
                    self._render_wizard_step()
                    return

        def _wizard_step_key_for_action(self, key: str) -> str:
            for prefix, step_key in self._WIZARD_KEY_PREFIXES:
                if key.startswith(prefix):
                    return step_key
            return "review"

        def _wizard_toggle_and_advance(self, key: str, label: str, kind: str, run, *, advance: bool):
            """Toggle one PlannedAction in/out of the plan. Picking an action
            on a single-decision page (GIMP/PhotoGIMP/G'MIC/Batcher) moves
            straight on to the next page, like a normal installer; un-picking
            it (or toggling on a multi-item page like SAM, where jumping away
            after every click would make it impossible to pick more than one
            thing) just refreshes this page in place — a cheap, flicker-free
            partial redraw, not a full-screen rebuild."""
            now_queued = self.plan.toggle(PlannedAction(key=key, label=label, kind=kind, run=run))
            if advance and now_queued:
                self._wizard_advance()
            else:
                self._refresh_wizard_body()

        def _render_wizard_step(self):
            self.current_screen = "wizard"
            for w in self.root_frame.winfo_children():
                w.destroy()
            step = self.wizard_steps[self.wizard_index]

            outer = tk.Frame(self.root_frame, bg=BG)
            outer.pack(fill="both", expand=True)

            top = tk.Frame(outer, bg=BG)
            top.pack(fill="x", padx=26, pady=(16, 0))
            tk.Label(top, text=step.title, bg=BG, fg=TEXT, font=("Sans", 16, "bold")).pack(side="left")
            tk.Label(top, text=f"Step {self.wizard_index + 1} of {len(self.wizard_steps)}", bg=BG,
                     fg=TEXT_MUTED, font=("Sans", 10)).pack(side="right")

            nav = tk.Frame(outer, bg=BG)
            nav.pack(fill="x", padx=26, pady=(10, 16), side="bottom")
            RoundedButton(nav, "← Back", variant="secondary", width=110, command=self._wizard_back).pack(
                side="left")
            self._wizard_next_btn = None
            if step.key != "review":
                self._wizard_next_btn = RoundedButton(nav, "Next →", variant="primary", width=140,
                                                       command=self._wizard_advance)
                self._wizard_next_btn.pack(side="right")
                self._wizard_next_btn.set_enabled(self._wizard_can_advance())
                if not step.prerequisite:
                    RoundedButton(nav, "Skip →", variant="secondary", width=110,
                                  command=self._wizard_advance).pack(side="right", padx=(0, 8))

            self._wizard_scroller = ScrollableFrame(outer)
            self._wizard_scroller.pack(fill="both", expand=True, padx=26, pady=(6, 0))
            self._wizard_body_parent = self._wizard_scroller.inner
            self._refresh_wizard_body()

        def _refresh_wizard_body(self):
            """Re-render only the current page's content, in place — used for
            every toggle click so a selection never causes the whole screen
            (top bar, nav bar, scrollbar) to flash and rebuild."""
            parent = self._wizard_body_parent
            for w in parent.winfo_children():
                w.destroy()
            step = self.wizard_steps[self.wizard_index]
            getattr(self, self._WIZARD_RENDERERS[step.key])(parent)
            self._wizard_scroller.bind_mousewheel_recursive()
            if self._wizard_next_btn is not None and self._wizard_next_btn.winfo_exists():
                self._wizard_next_btn.set_enabled(self._wizard_can_advance())

        def _status_row(self, body, ok: bool, text: str):
            row = tk.Frame(body, bg=CARD_BG)
            row.pack(fill="x", pady=(0, 10))
            icon_canvas(row, "check" if ok else "x", color=SUCCESS if ok else TEXT_MUTED, size=16,
                        bg=CARD_BG).pack(side="left", padx=(0, 8))
            autowrap_label(row, text, fg=TEXT, bg=CARD_BG, font=("Sans", 10)).pack(side="left", fill="x",
                                                                                     expand=True)

        def _wizard_toggle_card(self, parent, *, key: str, installed: bool, status_text: str, install_label: str,
                                 install_run, uninstall_run, uninstall_label: str = "Uninstall",
                                 install_enabled: bool = True, disabled_reason: Optional[str] = None,
                                 advance: bool = True, extra=None):
            """One reusable card covering every single-decision component page
            (PhotoGIMP, G'MIC, Batcher):
            not installed -> one green toggle that queues/unqueues Install;
            installed -> one red toggle that queues/unqueues Uninstall.
            Exactly one button, so there's never a second, greyed-out one
            sitting next to it — just a ✓ once it's queued."""
            card = RoundedCard(parent)
            card.pack(fill="x", pady=(0, 10))
            body = card.body
            self._status_row(body, installed, status_text)
            if extra:
                extra(body)
            btn_row = tk.Frame(body, bg=CARD_BG)
            btn_row.pack(fill="x", pady=(6, 0))
            if installed:
                remove_key = f"{key}:remove"
                queued = self.plan.has(remove_key)
                RoundedButton(
                    btn_row, uninstall_label + (" ✓" if queued else ""), icon="trash", variant="danger", width=220,
                    command=lambda: self._wizard_toggle_and_advance(
                        remove_key, f"Remove {install_label}", "remove", uninstall_run, advance=advance),
                ).pack(side="left")
            else:
                install_key = f"{key}:install"
                queued = self.plan.has(install_key)
                btn = RoundedButton(
                    btn_row, install_label + (" ✓" if queued else ""), icon="install", variant="success", width=220,
                    command=lambda: self._wizard_toggle_and_advance(
                        install_key, install_label, "install", install_run, advance=advance),
                )
                btn.pack(side="left")
                btn.set_enabled(install_enabled or queued)
                if not (install_enabled or queued) and disabled_reason:
                    callout(body, disabled_reason, "warn")
            card.finalize()

        # -- GIMP (prerequisite; mandatory, exclusive choice of method) -------

        def _wizard_render_gimp(self, parent):
            native = gimp_native_installed()
            appimg = appimage_present()
            distro = detect_distro()
            card = RoundedCard(parent)
            card.pack(fill="x", pady=(0, 4))
            body = card.body
            self._status_row(body, native, f"Native package ({distro or 'no supported distro detected'})"
                                            + (" — installed" if native else " — not installed"))
            self._status_row(body, appimg, f"AppImage in {APPIMAGE_DIR}"
                                            + (" — installed" if appimg else " — not installed"))

            btn_row = tk.Frame(body, bg=CARD_BG)
            btn_row.pack(fill="x", pady=(6, 0))
            pm_selected = self.plan.has("gimp_install_pm")
            ai_selected = self.plan.has("gimp_install_appimage")
            pm_btn = RoundedButton(
                btn_row, "Install via package manager" + (" ✓" if pm_selected else ""), icon="install",
                variant="success", width=270, command=lambda: self._wizard_pick_gimp_method("pm"))
            pm_btn.pack(side="left", padx=(0, 8))
            pm_btn.set_enabled(bool(distro))
            ai_btn = RoundedButton(
                btn_row, "Install AppImage" + (" ✓" if ai_selected else ""), icon="install",
                variant="success", width=210, command=lambda: self._wizard_pick_gimp_method("appimage"))
            ai_btn.pack(side="left")
            if not distro:
                callout(body, "No supported distribution detected (arch, debian, ubuntu, fedora, opensuse) — "
                               "use the AppImage instead.", "warn")
            callout(body, "GIMP is a prerequisite for everything else, so this page can't be skipped — "
                          "pick one of the two methods above to continue.", "info")
            card.finalize()

        def _wizard_pick_gimp_method(self, method: str):
            self.plan.discard("gimp_install_pm")
            self.plan.discard("gimp_install_appimage")
            if method == "pm":
                action = PlannedAction("gimp_install_pm", "Install GIMP (package manager)", "install",
                                        lambda job: install_gimp_package_manager(job, include_gmic=False))
            else:
                action = PlannedAction("gimp_install_appimage", "Install GIMP (AppImage)", "install",
                                        lambda job: install_gimp_appimage(job))
            self.plan.add(action)
            self._wizard_advance()

        # -- PhotoGIMP ---------------------------------------------------------

        def _wizard_render_photogimp(self, parent):
            installed = photogimp_installed()

            def extra(body):
                autowrap_label(body, "Also fixes the taskbar/window icon showing a generic icon instead of "
                                      "PhotoGIMP's — every (re)install regenerates that desktop-file fix.",
                               fg=TEXT_MUTED, bg=CARD_BG, font=("Sans", 9)).pack(anchor="w", fill="x", pady=(0, 10))
                if installed:
                    RoundedButton(body, "Fix taskbar icon now", icon="refresh", variant="secondary", width=200,
                                  command=self._repair_photogimp_desktop).pack(anchor="w", pady=(0, 8))

            self._wizard_toggle_card(
                parent, key="photogimp", installed=installed,
                status_text="Icons, shortcuts, splash screen, UI layout"
                             + (" — installed" if installed else " — not installed"),
                install_label="Install PhotoGIMP",
                install_run=lambda job: install_photogimp(job, gimp_command=(find_gimp_command() or [None])[0]),
                uninstall_run=lambda job: remove_photogimp(job),
                extra=extra,
            )

        def _repair_photogimp_desktop(self):
            def task(job: Job):
                repair_desktop_integration(job)

            def done():
                if self.current_screen == "wizard":
                    self._refresh_wizard_body()
                show_snackbar(self, "Desktop entry fixed — restart GIMP and re-pin it", tone="ok")

            self.run_in_background(task, on_done=done)

        # -- G'MIC ---------------------------------------------------------------

        def _wizard_render_gmic(self, parent):
            installed = gmic_installed()
            available = gmic_available_on_this_release()
            self._wizard_toggle_card(
                parent, key="gmic", installed=installed,
                status_text="Extra filter collection for GIMP" + (" — installed" if installed else " — not installed"),
                install_label="Install G'MIC",
                install_run=lambda job: install_gmic_only(job),
                uninstall_run=lambda job: remove_gmic_only(job),
                install_enabled=available,
                disabled_reason=(None if available else
                                  f"No G'MIC package on this distribution release — see {GMIC_DOWNLOAD_PAGE} "
                                  "for a manual build."),
            )

        # -- SAM: one setup action (plug-in + backend) + models + SAM 3.1 -------
        # The plug-in and the Python backend are two files on disk from the
        # user's point of view — "SAM works or it doesn't" — so they're one
        # queueable action, not two separate questions. Its single run()
        # re-checks what's actually missing at execution time and only does
        # that, so the very same button is correct whether nothing is
        # installed yet, only the backend is broken, or everything is already
        # fine (in which case the page offers Uninstall instead).
        #
        # Every widget on this page is built exactly once per visit and then
        # only ever has its text/enabled state *updated* afterwards (never
        # destroyed and rebuilt) — refresh_sam_page() below is the one place
        # that happens, which is what keeps this page from flashing on every
        # click the way a full-page rebuild would.

        def _sam_setup_install_run(self):
            def run(job: Job):
                if not segany_plugin_installed():
                    job.log("Installing the SAM plug-in...")
                    install_segany_plugin(job)
                else:
                    job.log("SAM plug-in already installed.")
                if not backend_ready():
                    job.log("Setting up the SAM Python backend...")
                    install_sam_backend(job, TORCH_INDEX_URLS[self.torch_choice.get()])
                else:
                    job.log("SAM Python backend already ready.")
            return run

        @staticmethod
        def _sam_setup_remove_run(job: Job):
            remove_segany_plugin(job)
            remove_sam_backend(job)

        @staticmethod
        def _sam_model_install_run(spec: ModelSpec):
            def run(job: Job):
                dest = model_path(spec)
                if os.path.isfile(dest):
                    job.log(f"{spec.label} already downloaded at {dest}")
                    return
                if job.download(spec.url, dest, job.cancel_event):
                    write_segany_plugin_settings(spec)
                    write_sam_info([spec.key])
            return run

        @staticmethod
        def _sam_model_remove_run(spec: ModelSpec):
            def run(job: Job):
                dest = model_path(spec)
                try:
                    if os.path.isdir(dest):
                        shutil.rmtree(dest)
                    elif os.path.isfile(dest):
                        os.remove(dest)
                    job.log(f"Removed {dest}")
                except Exception as e:
                    job.log(f"ERROR removing {dest}: {e}")
            return run

        def _wizard_render_sam(self, parent):
            plugin_ok = segany_plugin_installed()
            ready = backend_ready()
            exists = venv_exists()
            fully_ready = plugin_ok and ready
            setup_install_key, setup_remove_key = "sam_setup:install", "sam_setup:remove"

            def sam_present_after() -> bool:
                if fully_ready:
                    return not self.plan.has(setup_remove_key)
                return self.plan.has(setup_install_key)

            model_widgets: list[tuple] = []       # (button, spec, installed)
            queue_all_buttons: list = []

            # -- combined plug-in + backend card --
            card = RoundedCard(parent)
            card.pack(fill="x", pady=(0, 10))
            body = card.body
            self._status_row(body, plugin_ok, "SAM plug-in files"
                              + (" — installed" if plugin_ok else " — not installed"))
            self._status_row(body, ready, "Python backend (PyTorch venv)"
                              + (" — ready" if ready else " — not ready"))
            if ready:
                callout(body, f"Ready at {VENV_DIR}", "ok")
            elif exists:
                callout(body, "A virtualenv exists but PyTorch isn't importable — Repair will retry it.", "warn")
            else:
                callout(body, "Not set up yet.", "warn")
            tk.Label(body, text="PyTorch build", bg=CARD_BG, fg=TEXT, font=("Sans", 10, "bold")).pack(
                anchor="w", pady=(8, 6))
            combo = ttk.Combobox(body, textvariable=self.torch_choice, values=list(TORCH_INDEX_URLS.keys()),
                                  state="readonly", width=34, font=("Sans", 10))
            combo.pack(anchor="w", pady=(0, 6))
            flatten_entry(combo)

            btn_row = tk.Frame(body, bg=CARD_BG)
            btn_row.pack(fill="x", pady=(6, 0))
            if fully_ready:
                setup_label, setup_kind, setup_key = "Uninstall SAM (plug-in + backend + all models)", "remove", setup_remove_key
                setup_run = self._sam_setup_remove_run
                setup_variant = "danger"
            else:
                setup_label = "Install SAM" if not (plugin_ok or exists) else "Repair SAM setup"
                setup_kind, setup_key = "install", setup_install_key
                setup_run = self._sam_setup_install_run()
                setup_variant = "success"
            setup_btn = RoundedButton(btn_row, setup_label, icon=("trash" if fully_ready else "install"),
                                       variant=setup_variant, width=340)
            setup_btn.pack(side="left")

            def toggle_setup():
                self.plan.toggle(PlannedAction(setup_key, setup_label, setup_kind, setup_run))
                refresh_sam_page()

            setup_btn.command = toggle_setup

            # -- models, by family --
            autowrap_label(
                parent,
                "Quality/Speed are rough 1-5 estimates, comparable within a family. Already-downloaded models "
                "are never a checkbox again — Remove just queues their deletion for the final install step.",
                fg=TEXT_MUTED, bg=BG, font=("Sans", 9),
            ).pack(anchor="w", fill="x", pady=(6, 10))
            gate_note = callout(parent, "Models need the SAM setup above first.", "warn")
            if sam_present_after():
                gate_note.pack_forget()

            rec_key = recommended_model_key(self.hw)
            for family in ("SAM1", "SAM2"):
                fam_card = RoundedCard(parent)
                fam_card.pack(fill="x", pady=(0, 10))
                head = tk.Frame(fam_card.body, bg=CARD_BG)
                head.pack(fill="x", pady=(0, 4))
                tk.Label(head, text=family, bg=CARD_BG, fg=ACCENT, font=("Sans", 11, "bold")).pack(side="left")
                queue_all_btn = RoundedButton(head, "Queue all missing", icon="install", variant="secondary",
                                               width=170)
                queue_all_btn.pack(side="right")
                queue_all_buttons.append(queue_all_btn)

                for spec in [m for m in MODEL_REGISTRY if m.family == family]:
                    row = RoundedCard(fam_card.body, pad=14, radius=16)
                    row.pack(fill="x", pady=6)
                    rbody = row.body
                    top = tk.Frame(rbody, bg=CARD_BG)
                    top.pack(fill="x")
                    left = tk.Frame(top, bg=CARD_BG)
                    left.pack(side="left", fill="x", expand=True)
                    name_row = tk.Frame(left, bg=CARD_BG)
                    name_row.pack(anchor="w")
                    tk.Label(name_row, text=spec.label, bg=CARD_BG, fg=TEXT, font=("Sans", 12, "bold")).pack(
                        side="left")
                    tk.Label(name_row, text=f"   {spec.size}", bg=CARD_BG, fg=TEXT_MUTED, font=("Sans", 9)).pack(
                        side="left")
                    if spec.key == rec_key:
                        tk.Label(name_row, text="  ★ Recommended", bg=CARD_BG, fg=ACCENT,
                                 font=("Sans", 9, "bold")).pack(side="left")
                    rating_widget(left, spec.quality, spec.speed, bg=CARD_BG).pack(anchor="w", pady=(4, 0))

                    installed = model_installed(spec)
                    right = tk.Frame(top, bg=CARD_BG)
                    right.pack(side="right")
                    if installed:
                        btn = RoundedButton(right, "Remove", icon="trash", variant="danger", width=160)
                    else:
                        btn = RoundedButton(right, "Add to plan", icon="install", variant="success", width=160)
                    btn.pack(side="left")
                    model_widgets.append((btn, spec, installed))
                    row.finalize()
                fam_card.finalize()

            def bind_model_row(btn, spec, installed):
                install_key, remove_key = f"sam_model:{spec.key}:install", f"sam_model:{spec.key}:remove"
                if installed:
                    btn.command = lambda: (
                        self.plan.toggle(PlannedAction(remove_key, f"Remove {spec.label}", "remove",
                                                        self._sam_model_remove_run(spec))),
                        refresh_sam_page())
                else:
                    btn.command = lambda: (
                        self.plan.toggle(PlannedAction(install_key, f"Download {spec.label}", "install",
                                                        self._sam_model_install_run(spec))),
                        refresh_sam_page())

            for btn, spec, installed in model_widgets:
                bind_model_row(btn, spec, installed)

            def queue_all(family):
                missing = [m for m in MODEL_REGISTRY if m.family == family and not model_installed(m)]
                if not missing:
                    themed_info(self.root, "Nothing to do", f"All {family} models are already installed.")
                    return
                for spec in missing:
                    key = f"sam_model:{spec.key}:install"
                    if not self.plan.has(key):
                        self.plan.add(PlannedAction(key, f"Download {spec.label}", "install",
                                                     self._sam_model_install_run(spec)))
                refresh_sam_page()

            families = ("SAM1", "SAM2")
            for fam, qbtn in zip(families, queue_all_buttons):
                qbtn.command = lambda fam=fam: queue_all(fam)

            sam3_widgets = self._wizard_render_sam3(parent, sam_present_after)

            def refresh_sam_page():
                present = sam_present_after()
                if fully_ready:
                    setup_btn.set_text(setup_label + (" ✓" if self.plan.has(setup_remove_key) else ""))
                else:
                    setup_btn.set_text(setup_label + (" ✓" if self.plan.has(setup_install_key) else ""))
                if present:
                    gate_note.pack_forget()
                else:
                    gate_note.pack(fill="x", pady=(4, 12))
                for btn, spec, installed in model_widgets:
                    if installed:
                        q = self.plan.has(f"sam_model:{spec.key}:remove")
                        btn.set_text("Remove" + (" ✓" if q else ""))
                    else:
                        q = self.plan.has(f"sam_model:{spec.key}:install")
                        btn.set_text("Add to plan" + (" ✓" if q else ""))
                        btn.set_enabled(present or q)
                for qbtn in queue_all_buttons:
                    qbtn.set_enabled(present)
                sam3_widgets.refresh(present)

            refresh_sam_page()

        # -- SAM 3.1 (gated on Hugging Face) -------------------------------------

        class _Sam3Widgets:
            """Tiny bundle returned so the SAM page's refresh_sam_page() can
            update SAM3's enabled state (it depends on sam_present_after(),
            which the setup card owns) without rebuilding anything."""
            def __init__(self, refresh_fn):
                self._refresh_fn = refresh_fn

            def refresh(self, present: bool):
                self._refresh_fn(present)

        def _wizard_render_sam3(self, parent, sam_present_after):
            spec = MODEL_BY_KEY["sam3"]
            installed = model_installed(spec)
            card = RoundedCard(parent)
            card.pack(fill="x", pady=(0, 10))
            body = card.body

            top = tk.Frame(body, bg=CARD_BG)
            top.pack(fill="x")
            left = tk.Frame(top, bg=CARD_BG)
            left.pack(side="left", fill="x", expand=True)
            name_row = tk.Frame(left, bg=CARD_BG)
            name_row.pack(anchor="w")
            tk.Label(name_row, text=f"{spec.label} (SAM3)", bg=CARD_BG, fg=TEXT, font=("Sans", 12, "bold")).pack(
                side="left")
            tk.Label(name_row, text=f"   {spec.size}", bg=CARD_BG, fg=TEXT_MUTED, font=("Sans", 9)).pack(side="left")
            rating_widget(left, spec.quality, spec.speed, bg=CARD_BG).pack(anchor="w", pady=(4, 0))

            install_key, remove_key = "sam3:install", "sam3:remove"

            autowrap_label(
                body, f"Gated on Hugging Face ({SAM3_HF_REPO_ID}) — request access, wait for approval, then "
                      "paste a READ token below. The token is only checked against the repo once the plan "
                      "actually runs, so queuing it now is free.",
                fg=TEXT_MUTED, bg=CARD_BG, font=("Sans", 9),
            ).pack(anchor="w", fill="x", pady=(12, 14))

            row1 = tk.Frame(body, bg=CARD_BG)
            row1.pack(fill="x", pady=(0, 10))
            RoundedButton(row1, "Request access on Hugging Face", icon="link", variant="secondary", width=270,
                          command=lambda: webbrowser.open(SAM3_HF_PAGE)).pack(side="left")
            transformers_key = "sam3:transformers"
            transformers_btn = RoundedButton(row1, "Install/upgrade transformers", icon="box", variant="success",
                                              width=230)
            transformers_btn.pack(side="left", padx=8)

            def toggle_transformers():
                self.plan.toggle(PlannedAction(transformers_key, "Install/upgrade transformers", "install",
                                                lambda job: install_sam3_transformers(job)))
                transformers_btn.set_text("Install/upgrade transformers"
                                           + (" ✓" if self.plan.has(transformers_key) else ""))

            transformers_btn.command = toggle_transformers

            row2 = tk.Frame(body, bg=CARD_BG)
            row2.pack(fill="x")
            tk.Label(row2, text="HF token", bg=CARD_BG, fg=TEXT, font=("Sans", 10, "bold")).pack(side="left")
            hf_entry = ttk.Entry(row2, textvariable=self.hf_token_var, show="*", width=30, font=("Sans", 10))
            hf_entry.pack(side="left", padx=8, ipady=3)
            flatten_entry(hf_entry)

            gate_note = callout(body, "Needs the SAM setup above first.", "warn")

            if installed:
                sam3_btn = RoundedButton(row2, "Remove", icon="trash", variant="danger", width=130)
                sam3_btn.pack(side="left")

                def toggle_sam3():
                    self.plan.toggle(PlannedAction(remove_key, "Remove SAM 3.1", "remove",
                                                    lambda job: remove_sam3(job)))
                    sam3_btn.set_text("Remove" + (" ✓" if self.plan.has(remove_key) else ""))

                sam3_btn.command = toggle_sam3
                gate_note.pack_forget()

                def refresh(_present: bool):
                    pass
            else:
                sam3_btn = RoundedButton(
                    row2, "Add to plan", icon="install", variant="success", width=140,
                    on_blocked=lambda: show_snackbar(self, "Enter a Hugging Face token first", tone="warn"))
                sam3_btn.pack(side="left")

                def token_entered() -> bool:
                    return bool(self.hf_token_var.get().strip())

                def toggle_sam3():
                    self.plan.toggle(PlannedAction(install_key, "Download SAM 3.1", "install",
                                                    lambda job: self._run_sam3_download(job)))
                    sam3_btn.set_text("Add to plan" + (" ✓" if self.plan.has(install_key) else ""))

                sam3_btn.command = toggle_sam3

                def refresh(present: bool):
                    queued = self.plan.has(install_key)
                    sam3_btn.set_enabled(present and (queued or token_entered()))
                    if present:
                        gate_note.pack_forget()
                    else:
                        gate_note.pack(fill="x", pady=(4, 12))

                trace_id = self.hf_token_var.trace_add("write", lambda *_a: refresh(sam_present_after()))
                sam3_btn.bind("<Destroy>", lambda _e, tid=trace_id: self.hf_token_var.trace_remove("write", tid))

            refresh(sam_present_after())
            card.finalize()
            return self._Sam3Widgets(refresh)

        def _run_sam3_download(self, job: Job):
            token = self.hf_token_var.get().strip()
            if not token:
                job.log("No Hugging Face token was entered — skipping SAM 3.1.")
                return
            ok, tag = download_sam3(job, token)
            if not ok:
                job.log(sam3_failure_message(tag))

        # -- Batcher -----------------------------------------------------

        def _wizard_render_batcher(self, parent):
            installed = batcher_installed()
            self._wizard_toggle_card(
                parent, key="batcher", installed=installed,
                status_text="Batch image processing / export layers"
                             + (" — installed" if installed else " — not installed"),
                install_label="Install Batcher",
                install_run=lambda job: install_batcher(job),
                uninstall_run=lambda job: remove_batcher(job),
            )

        # -- Review & install --------------------------------------------------

        def _wizard_render_review(self, parent):
            if len(self.plan) == 0:
                card = RoundedCard(parent)
                card.pack(fill="x")
                tk.Label(card.body, text="Nothing queued yet — go back and pick at least one action.",
                         bg=CARD_BG, fg=TEXT_MUTED, font=("Sans", 10)).pack(anchor="w")
                card.finalize()
                return

            # SAM models are queued one-by-one so each page can show its own
            # state, but a dozen "Download vit_b" / "Download vit_l" lines
            # here would just be noise — collapse them into one summary row.
            sam_installs = [a for a in self.plan if a.key.startswith("sam_model:") and a.kind == "install"]
            sam_removes = [a for a in self.plan if a.key.startswith("sam_model:") and a.kind == "remove"]
            grouped_keys = {a.key for a in sam_installs + sam_removes}
            other_actions = [a for a in self.plan if a.key not in grouped_keys]

            def add_row(label: str, kind: str, step_key: str, keys: list[str]):
                row = RoundedCard(parent, pad=14, radius=14)
                row.pack(fill="x", pady=5)
                line = tk.Frame(row.body, bg=CARD_BG)
                line.pack(fill="x")
                icon_canvas(line, "trash" if kind == "remove" else "install",
                            color=DANGER if kind == "remove" else SUCCESS, size=16,
                            bg=CARD_BG).pack(side="left", padx=(0, 10))
                tk.Label(line, text=label, bg=CARD_BG, fg=TEXT, font=("Sans", 10, "bold")).pack(
                    side="left", fill="x", expand=True)
                trash_btn = RoundedButton(line, "", icon="trash", variant="secondary", width=40,
                                           command=lambda: self._wizard_discard_many(keys))
                trash_btn.pack(side="right")
                row.finalize()
                bind_click_recursive(row, lambda sk=step_key: self._wizard_jump_to_step(sk), skip=(trash_btn,))

            for action in other_actions:
                add_row(action.label, action.kind, self._wizard_step_key_for_action(action.key), [action.key])
            if sam_installs:
                add_row(f"Download {len(sam_installs)} SAM model" + ("s" if len(sam_installs) != 1 else ""),
                        "install", "sam", [a.key for a in sam_installs])
            if sam_removes:
                add_row(f"Remove {len(sam_removes)} SAM model" + ("s" if len(sam_removes) != 1 else ""),
                        "remove", "sam", [a.key for a in sam_removes])

            RoundedButton(parent, f"Proceed to installation ({len(self.plan)})", icon="bolt", variant="primary",
                          width=320, height=44, command=self._wizard_start_install).pack(anchor="w", pady=(14, 0))

        def _wizard_discard_many(self, keys: list[str]):
            for key in keys:
                self.plan.discard(key)
            self._refresh_wizard_body()

        def _wizard_start_install(self):
            self.show_install_progress(list(self.plan))

        # ---- shared install-progress screen ---------------------------------
        # Runs a list[PlannedAction] sequentially, in one background thread,
        # with a live progress bar and log — used by both the wizard's Review
        # page and Quick Setup's prefilled plan, so there is exactly one place
        # that actually executes anything.

        def show_install_progress(self, actions: list[PlannedAction]):
            self.plan_actions = list(actions)
            self.exec_total = len(self.plan_actions)
            self.exec_done = 0
            self.exec_cancelled = False
            self.exec_finished = False
            self._exec_log_lines = []
            self._render_install_progress()
            self._run_plan()

        def _exec_progress_text(self) -> str:
            if self.exec_total == 0:
                return "Nothing was queued."
            if self.exec_finished:
                if self.exec_cancelled:
                    return f"Stopped after {self.exec_done} of {self.exec_total} steps."
                return f"Finished {self.exec_done} of {self.exec_total} steps."
            return f"Step {min(self.exec_done + 1, self.exec_total)} of {self.exec_total}"

        def _render_install_progress(self):
            self.current_screen = "installing"
            for w in self.root_frame.winfo_children():
                w.destroy()

            content = tk.Frame(self.root_frame, bg=BG)
            content.pack(fill="both", expand=True, padx=32, pady=24)

            title = "Installation finished" if self.exec_finished else "Installing…"
            tk.Label(content, text=title, bg=BG, fg=TEXT, font=("Sans", 18, "bold")).pack(anchor="w")

            self.exec_step_lbl = tk.Label(content, text=self._exec_progress_text(), bg=BG, fg=TEXT_MUTED,
                                           font=("Sans", 10))
            self.exec_step_lbl.pack(anchor="w", pady=(4, 10))

            self.exec_progress_bar = ProgressBar(content, width=760, height=10)
            self.exec_progress_bar.pack(anchor="w", fill="x")
            self.exec_progress_bar.set_fraction(self.exec_done / self.exec_total if self.exec_total else 1.0)

            # A RoundedCard sizes itself to its content's *requested* height,
            # which would cap this panel at a fixed number of text lines no
            # matter how much room the window actually has — so the log gets
            # a plain bordered Frame instead, which correctly stretches to
            # fill whatever vertical space is left (fill="both", expand=True
            # all the way down this chain).
            log_frame = tk.Frame(content, bg=CARD_BG, highlightbackground=CARD_BORDER, highlightthickness=1)
            log_frame.pack(fill="both", expand=True, pady=(16, 0))
            text_frame = tk.Frame(log_frame, bg=CARD_BG)
            text_frame.pack(fill="both", expand=True, padx=10, pady=10)
            self.exec_log_text = tk.Text(text_frame, bg="#101114", fg=TEXT, insertbackground=TEXT, relief="flat",
                                          wrap="word", font=("Monospace", 10), padx=8, pady=6, state="disabled")
            sb = ttk.Scrollbar(text_frame, orient="vertical", command=self.exec_log_text.yview,
                                style="Modern.Vertical.TScrollbar")
            self.exec_log_text.configure(yscrollcommand=sb.set)
            self.exec_log_text.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            for line in self._exec_log_lines:
                self._append_exec_log(line)

            btn_row = tk.Frame(content, bg=BG)
            btn_row.pack(fill="x", pady=(16, 0))
            if self.exec_finished:
                RoundedButton(btn_row, "Done", variant="primary", width=140,
                              command=self.show_landing).pack(side="left")
            else:
                RoundedButton(btn_row, "Stop", icon="x", variant="danger", width=140,
                              command=self._stop_plan_execution).pack(side="left")

        def _append_exec_log(self, line: str):
            if not hasattr(self, "exec_log_text") or not self.exec_log_text.winfo_exists():
                return
            self.exec_log_text.configure(state="normal")
            self.exec_log_text.insert("end", line + "\n")
            self.exec_log_text.see("end")
            self.exec_log_text.configure(state="disabled")

        def _bump_exec_progress(self):
            if hasattr(self, "exec_step_lbl") and self.exec_step_lbl.winfo_exists():
                self.exec_step_lbl.configure(text=self._exec_progress_text())
            if hasattr(self, "exec_progress_bar") and self.exec_progress_bar.winfo_exists():
                self.exec_progress_bar.set_fraction(self.exec_done / self.exec_total if self.exec_total else 1.0)

        def _run_plan(self):
            actions = self.plan_actions

            def task(job: Job):
                for action in actions:
                    if job.cancel_event.is_set():
                        self.exec_cancelled = True
                        job.log(f"Stopped before: {action.label}")
                        break
                    job.log(f"→ {action.label}")
                    try:
                        action.run(job)
                    except Exception as e:
                        job.log(f"ERROR during {action.label}: {e}")
                    self.exec_done += 1
                    self.root.after(0, self._bump_exec_progress)
                if not actions:
                    job.log("Nothing was queued.")
                elif self.exec_cancelled:
                    job.log("Stopped — whatever finished so far was left in place.")
                else:
                    job.log("All done! Restart GIMP to see everything.")

            self.run_in_background(task, on_done=self._finish_plan)

        def _stop_plan_execution(self):
            self.cancel_current_job()

        def _finish_plan(self):
            self.exec_finished = True
            self._render_install_progress()


def launch_gui():
    if not _TK_OK:
        print("[fail] Tkinter is not available in this Python — install python3-tk (or the equivalent "
              "package for your distro) to use the graphical installer, or use the CLI: "
              "python3 lazygimp.py --help", file=sys.stderr)
        sys.exit(1)
    root = tk.Tk()
    LazyGimpApp(root)
    try:
        root.mainloop()
    finally:
        _self_destruct_if_ephemeral()
