"""Reusable widgets — Qt port of ``lazygimp/gui/widgets.py``.

Public names and method signatures are kept identical to the Tk/CTk
engine wherever it made sense (RoundedButton, RoundedCard, ProgressBar,
ModernCheckbox, ScrollableFrame, bind_click_recursive, page_header,
callout) so the page-porting agents can mostly find/replace an import
line and keep calling the same methods (set_enabled, set_variant,
set_text, start_loading/stop_loading, set_fraction, finalize,
page_up/page_down, on_blocked=, command=).

The single biggest structural difference from Tk is layout: Tk's
pack()/grid() auto-flow with no parent-side declaration, Qt widgets need
an explicit QLayout on their parent. That difference is NOT hidden here
— page code will need real QVBoxLayout/QHBoxLayout/QGridLayout calls —
but RoundedCard.body is still the plain container children get added
to, exactly like the Tk version's tk.Frame. See gui/README.md for
the full old->new table and the layout-migration notes.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSize, QTimer, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractSlider, QCheckBox, QFrame, QHBoxLayout, QLabel, QProgressBar as _QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .icons import icon_label, render_icon
from .theme import (
    ACCENT, ACCENT_HOVER, ACCENT_TEXT, BG, CARD_BG, CARD_BORDER, DANGER, DANGER_HOVER,
    DANGER_TEXT, DISABLED_BG, DISABLED_TEXT, F_BODY, F_BODY_B, F_H2, F_SMALL, SECONDARY_HOVER,
    SUCCESS, SUCCESS_HOVER, SUCCESS_TEXT, TEXT, TEXT_MUTED, TONE_COLORS, qfont,
)

# Icon kind used inside RoundedButton per old glyph name — kept for
# reference/back-compat only. Unlike the Tk engine, Qt buttons never
# need a text-glyph fallback: render_icon() (QPainter-based) always
# succeeds, no optional Pillow dependency involved.
_BUTTON_GLYPHS = {
    "install": "install", "trash": "trash", "bolt": "bolt", "refresh": "refresh",
    "link": "link", "x": "x", "box": "box", "check": "check",
}


class BoolVar:
    """Minimal drop-in for tkinter.BooleanVar's get()/set() surface, for
    page code that used to hold a tk.BooleanVar alongside ModernCheckbox.
    Not a Tk object — just a tiny mutable box, since Qt's QCheckBox has
    no variable= concept of its own."""

    def __init__(self, value: bool = False):
        self._value = bool(value)

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        self._value = bool(value)


class RoundedButton(QPushButton):
    _PALETTE = {
        "primary": (ACCENT, ACCENT_HOVER, ACCENT_TEXT),
        "success": (SUCCESS, SUCCESS_HOVER, SUCCESS_TEXT),
        "danger": (DANGER, DANGER_HOVER, DANGER_TEXT),
        "secondary": (CARD_BORDER, SECONDARY_HOVER, TEXT),
    }

    def __init__(self, parent=None, text="", command=None, variant="secondary", icon=None,
                 width=None, height=34, radius=13, font=F_BODY_B, bg=None, on_blocked=None):
        super().__init__(parent)
        self.variant = variant
        self.icon_name = icon
        self._base_text = text
        self._on_blocked = on_blocked
        self._loading = False
        self._loading_base = ""
        self._loading_frame = 0
        self._radius = radius
        self._fixed_height = height
        self._command = None

        self.setText(text)
        self.setFont(qfont(font))
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setFixedHeight(height)
        if width:
            self.setFixedWidth(width)
        else:
            self.setMinimumWidth(140)
        if icon:
            self.setIcon(render_icon(icon, self._PALETTE[variant][2], size=18))
            self.setIconSize(QSize(18, 18))

        self._loading_timer = QTimer(self)
        self._loading_timer.setInterval(350)
        self._loading_timer.timeout.connect(self._tick_loading)

        self._apply_style()
        self.clicked.connect(self._on_clicked)
        self.command = command  # property setter, see below

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

    @property
    def on_blocked(self):
        return self._on_blocked

    @on_blocked.setter
    def on_blocked(self, fn):
        self._on_blocked = fn

    def set_text(self, text: str):
        self._base_text = text
        if not self._loading:
            self.setText(text)

    def set_enabled(self, enabled: bool):
        self.setEnabled(enabled)

    def set_variant(self, variant: str):
        self.variant = variant
        self._apply_style()
        if self.icon_name:
            fg = self._PALETTE[variant][2]
            self.setIcon(render_icon(self.icon_name, fg, size=18))

    def start_loading(self, base_text="Working"):
        if self._loading:
            return
        self._loading = True
        self._loading_base = base_text
        self._loading_frame = 0
        self.setEnabled(False)
        self._loading_timer.start()
        self._tick_loading()

    def stop_loading(self):
        self._loading = False
        self._loading_timer.stop()
        self.setEnabled(True)
        self.setText(self._base_text)

    # -- internals ---------------------------------------------------------

    def _on_clicked(self):
        if self._command:
            self._command()

    def _tick_loading(self):
        dots = "." * (1 + self._loading_frame % 3)
        self.setText(f"{self._loading_base}{dots}")
        self._loading_frame += 1

    def event(self, e):
        # QPushButton doesn't dispatch mouse events at all while
        # isEnabled() is False, so on_blocked is wired through a raw
        # event() override that also sees disabled-state presses.
        if e.type() == QEvent.MouseButtonPress and not self.isEnabled() and self._on_blocked:
            self._on_blocked()
        return super().event(e)

    def _apply_style(self):
        fill, hover, fg = self._PALETTE[self.variant]
        btn_id = f"Btn_{id(self)}"
        self.setObjectName(btn_id)
        self.setStyleSheet(f"""
            QPushButton#{btn_id} {{
                background-color: {fill};
                color: {fg};
                border: none;
                border-radius: {self._radius}px;
                padding: 0 16px;
                font-weight: 600;
            }}
            QPushButton#{btn_id}:hover {{
                background-color: {hover};
            }}
            QPushButton#{btn_id}:pressed {{
                background-color: {hover};
            }}
            QPushButton#{btn_id}:disabled {{
                background-color: {DISABLED_BG};
                color: {DISABLED_TEXT};
            }}
        """)


class RoundedCard(QFrame):
    """A rounded card with a `.body` plain QWidget for content — pages add
    their own layout to `.body` and add children to that, same convention
    as the Tk engine's tk.Frame (just needs an explicit QLayout, since Qt
    has no pack()/grid() auto-flow).

    Supports optional interactivity (hover/click, active border color/
    width) via an event filter installed on the whole subtree by
    finalize() — the Qt equivalent of the Tk engine's recursive
    <Button-1>/<Enter>/<Leave> binding, needed because Qt (like Tk)
    delivers mouse events to whichever child widget is under the
    pointer, not to the card itself.
    """

    def __init__(self, parent=None, bg=CARD_BG, border=CARD_BORDER, radius=18, pad=18, width=None,
                 height=None, command=None, hover_bg="#2f323a", hover_border=None, active_border=None,
                 active_width=1):
        super().__init__(parent)
        self.card_id = f"Card_{id(self)}"
        self.setObjectName(self.card_id)
        self._bg = bg
        self._border = border
        self._radius = radius
        self._command = command
        self._hover_bg = hover_bg
        self._hover_border = hover_border
        self._active_border = active_border
        self._active_width = active_width
        self._hovered = False
        self._filter = None

        if width:
            self.setFixedWidth(width)
        if height:
            self.setFixedHeight(height)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(pad, pad, pad, pad)
        self.body = QWidget(self)
        self.body.setStyleSheet("background: transparent; border: none;")
        outer.addWidget(self.body)

        self.setMouseTracking(True)
        self._update_style()

    def finalize(self):
        """Wires up hover/click interactivity across the whole subtree.
        Call once after all children have been added to .body — mirrors
        the Tk engine's finalize(), which does the same recursive bind."""
        if self._command is not None:
            self._filter = _CardEventFilter(self)
            self._install_filter(self)

    def childEvent(self, event):
        super().childEvent(event)
        if event.type() == QEvent.ChildAdded and self._filter is not None:
            c = event.child()
            if isinstance(c, QWidget):
                QTimer.singleShot(0, lambda: self._install_filter(c))

    def _install_filter(self, widget: QWidget):
        if self._filter is None:
            return
        targets = [widget] + widget.findChildren(QWidget)
        for w in targets:
            w.setMouseTracking(True)
            if self._command is not None and not isinstance(w, QPushButton):
                w.setCursor(QCursor(Qt.PointingHandCursor))
            w.installEventFilter(self._filter)

    def _on_click(self):
        if self._command:
            self._command()

    def _on_enter(self):
        self._hovered = True
        self._update_style()

    def _on_leave(self):
        self._hovered = False
        self._update_style()

    def _update_style(self):
        bg_color = self._hover_bg if self._hovered else self._bg
        if self._active_border is not None:
            border_color = self._active_border
            border_width = self._active_width
        else:
            border_color = self._hover_border if (self._hovered and self._hover_border) else self._border
            border_width = 1
        cursor = Qt.PointingHandCursor if self._command else Qt.ArrowCursor
        self.setCursor(QCursor(cursor))
        self.setStyleSheet(f"""
            QFrame#{self.card_id} {{
                background-color: {bg_color};
                border: {border_width}px solid {border_color};
                border-radius: {self._radius}px;
            }}
            QFrame#{self.card_id} QWidget {{
                background: transparent;
                border: none;
            }}
            QFrame#{self.card_id} QLabel {{
                background: transparent;
                border: none;
            }}
        """)


class _CardEventFilter(QObject):
    """Routes Enter/Leave/MouseButtonPress from any descendant of a
    RoundedCard back to the card's own hover/click handlers."""

    def __init__(self, card: RoundedCard):
        super().__init__(card)
        self._card = card

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Enter:
            self._card._on_enter()
        elif t == QEvent.Leave:
            pos = QCursor.pos()
            card_pos = self._card.mapFromGlobal(pos)
            if not self._card.rect().contains(card_pos):
                self._card._on_leave()
        elif t == QEvent.MouseButtonPress:
            if not isinstance(obj, QPushButton):
                self._card._on_click()
                return True
        return False


class ProgressBar(_QProgressBar):
    def __init__(self, parent=None, width=200, height=7, bg=None, track=CARD_BORDER, fill=ACCENT):
        super().__init__(parent)
        self.setRange(0, 1000)
        self.setValue(0)
        self.setTextVisible(False)
        self.setFixedHeight(height)
        if width:
            self.setFixedWidth(width)
        radius = height // 2
        self.setStyleSheet(f"""
            QProgressBar {{
                background-color: {track};
                border: none;
                border-radius: {radius}px;
            }}
            QProgressBar::chunk {{
                background-color: {fill};
                border-radius: {radius}px;
            }}
        """)

    def set_fraction(self, frac: float):
        frac = max(0.0, min(1.0, frac))
        self.setValue(int(round(frac * 1000)))


class ModernCheckbox(QCheckBox):
    """With `text`, the label is part of the checkbox: clicking it toggles
    — native QCheckBox behavior, for free, same as CTk's.

    `variable`, if given, is anything with get()/set() (a BoolVar, or a
    page's own tk.BooleanVar-alike) and is kept in sync bidirectionally.
    """

    def __init__(self, parent=None, variable=None, command=None, size=22, bg=None,
                 text="", font=None, text_color=None):
        super().__init__(text, parent)
        self._variable = variable
        self._command = command
        self.setFont(qfont(font or F_BODY))
        fg = text_color or TEXT_MUTED
        self.setStyleSheet(f"""
            QCheckBox {{
                color: {fg};
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: {size - 4}px;
                height: {size - 4}px;
                border-radius: 6px;
                border: 2px solid {CARD_BORDER};
                background: transparent;
            }}
            QCheckBox::indicator:hover {{
                border: 2px solid {ACCENT_HOVER};
            }}
            QCheckBox::indicator:checked {{
                background-color: {ACCENT};
                border: 2px solid {ACCENT};
            }}
        """)
        if variable is not None:
            self.setChecked(bool(variable.get()))
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool):
        if self._variable is not None:
            self._variable.set(checked)
        if self._command:
            self._command()


class ScrollableFrame(QScrollArea):
    """Native QScrollArea wrapper — the Qt counterpart of CTkScrollableFrame.

    Unlike the Tk engine (where `.inner = self`, since CTkScrollableFrame
    IS its own content surface), QScrollArea needs a distinct content
    widget: `.inner` is that content QWidget. Page code adds a layout to
    `.inner` and adds children to that layout, same convention as adding
    to a RoundedCard's `.body`. Mouse-wheel scrolling is handled natively
    by QScrollArea — no manual wheel-event routing needed here.
    """

    def __init__(self, parent=None, bg=BG):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(f"QScrollArea {{ background-color: {bg}; border: none; }}")
        self.inner = QWidget(self)
        self.inner.setStyleSheet(f"background-color: {bg};")
        self.setWidget(self.inner)

    def page_up(self):
        bar = self.verticalScrollBar()
        if bar is not None:
            bar.triggerAction(QAbstractSlider.SliderPageStepSub)

    def page_down(self):
        bar = self.verticalScrollBar()
        if bar is not None:
            bar.triggerAction(QAbstractSlider.SliderPageStepAdd)


class _ClickFilter(QObject):
    def __init__(self, handler, skip, parent=None):
        super().__init__(parent)
        self._handler = handler
        self._skip = skip

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and obj not in self._skip:
            self._handler()
        return False


def bind_click_recursive(widget: QWidget, handler, skip=()):
    """Installs a click handler (and pointing-hand cursor) on `widget` and
    every descendant, skipping anything in `skip` — the Qt counterpart of
    the Tk engine's recursive <Button-1> binder."""
    filt = _ClickFilter(handler, skip, parent=widget)
    widget.setProperty("_bind_click_recursive_filter", filt)  # keep it alive
    targets = [widget] + widget.findChildren(QWidget)
    for w in targets:
        if w in skip:
            continue
        w.setCursor(QCursor(Qt.PointingHandCursor))
        w.installEventFilter(filt)


def autowrap_label(parent, text, fg=TEXT_MUTED, bg=None, font=F_SMALL, justify=Qt.AlignLeft):
    """QLabel with native word-wrap — the Qt counterpart of the Tk
    engine's autowrap_label(). Qt's QLabel wraps to its own available
    width automatically (setWordWrap(True)); the Tk version needed a
    manual <Configure> handler to fake that, which isn't needed here."""
    lbl = QLabel(text, parent)
    lbl.setWordWrap(True)
    lbl.setFont(qfont(font))
    lbl.setAlignment(justify | Qt.AlignVCenter)
    style = f"color: {fg}; background: transparent;"
    lbl.setStyleSheet(style)
    lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    return lbl


def page_header(parent, title):
    """QLabel styled like a page title. If `parent` already has a layout,
    the header is appended to it automatically (mirroring the Tk
    engine's page_header(), which packed itself into `parent`); otherwise
    the label is returned for the caller to add manually."""
    lbl = QLabel(title, parent)
    lbl.setFont(qfont(F_H2))
    lbl.setStyleSheet(f"color: {TEXT}; background: transparent;")
    layout = parent.layout() if parent is not None else None
    if layout is not None:
        layout.addWidget(lbl)
        layout.setSpacing(max(layout.spacing(), 0))
    return lbl


def callout(parent, text, tone="info"):
    """Tone banner (info/warn/ok) with an icon + wrapped message — same
    tones/colors as the Tk engine's callout(). Auto-adds itself to
    `parent.layout()` when the parent already has one, same auto-pack
    convenience as page_header()."""
    icon_kind = {"info": "info", "warn": "warn", "ok": "check", "error": "x"}[tone]
    bgc, fg = TONE_COLORS[tone]
    card = RoundedCard(parent, bg=bgc, border=bgc, radius=14, pad=12)
    row_layout = QHBoxLayout(card.body)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(8)
    icon = icon_label(card.body, icon_kind, color=fg, size=20)
    icon.setAlignment(Qt.AlignTop)
    row_layout.addWidget(icon, 0, Qt.AlignTop)
    label = autowrap_label(card.body, text, fg=fg, bg=bgc, font=F_SMALL)
    row_layout.addWidget(label, 1)
    card.finalize()
    layout = parent.layout() if parent is not None else None
    if layout is not None:
        layout.addWidget(card)
    return card
