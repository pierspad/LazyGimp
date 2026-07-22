"""Small monochrome vector icons — Qt port of ``lazygimp/gui/icons.py``.

The Tk version needed a dual Tk-Canvas/Pillow backend because Tk Canvas
draws without anti-aliasing and Pillow was an optional dependency. Qt's
QPainter always anti-aliases and is never optional here (PySide6 IS the
GUI toolkit for this engine), so this module is simpler: one painter
backend, no cache-miss fallback to jagged canvas primitives.

Geometry (the cx/cy/s coordinate math for each glyph) is copied from the
Tk `_paint_icon()` almost line-for-line — same visual language, same
proportions — just re-targeted at a tiny QPainter adapter instead of the
Tk-Canvas/PIL dual backend. Not pixel-identical (Qt's stroke joins/caps
render slightly differently) but intentionally the same icon set and the
same silhouette per icon.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap

from .theme import TEXT, WARNING


class _Painter:
    """Adapter exposing the same primitive vocabulary as the Tk `_Painter`
    (line/polygon/rect/oval/arc) on top of a QPainter."""

    def __init__(self, qp: QPainter):
        self.qp = qp

    def _pen(self, color, width):
        pen = QPen(Qt.NoPen if color is None else _q(color))
        pen.setWidthF(max(0.1, width))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen

    def line(self, pts, color, width=2):
        self.qp.setPen(self._pen(color, width))
        self.qp.setBrush(Qt.NoBrush)
        path = QPainterPath()
        it = iter(pts)
        coords = list(zip(it, it))
        path.moveTo(*coords[0])
        for x, y in coords[1:]:
            path.lineTo(x, y)
        self.qp.drawPath(path)

    def polygon(self, pts, color=None, outline=None, width=2):
        it = iter(pts)
        points = [QPointF(x, y) for x, y in zip(it, it)]
        if color is not None:
            self.qp.setBrush(_q(color))
            self.qp.setPen(Qt.NoPen)
        else:
            self.qp.setBrush(Qt.NoBrush)
        if outline is not None:
            self.qp.setPen(self._pen(outline, width))
        self.qp.drawPolygon(points)

    def rect(self, x1, y1, x2, y2, color=None, outline=None, width=2, radius=0):
        rect = QRectF(x1, y1, x2 - x1, y2 - y1)
        self.qp.setBrush(_q(color) if color is not None else Qt.NoBrush)
        self.qp.setPen(self._pen(outline, width) if outline is not None else Qt.NoPen)
        if radius > 0:
            self.qp.drawRoundedRect(rect, radius, radius)
        else:
            self.qp.drawRect(rect)

    def oval(self, x1, y1, x2, y2, color=None, outline=None, width=2):
        rect = QRectF(x1, y1, x2 - x1, y2 - y1)
        self.qp.setBrush(_q(color) if color is not None else Qt.NoBrush)
        self.qp.setPen(self._pen(outline, width) if outline is not None else Qt.NoPen)
        self.qp.drawEllipse(rect)

    def arc(self, x1, y1, x2, y2, start, extent, color, width=2):
        rect = QRectF(x1, y1, x2 - x1, y2 - y1)
        self.qp.setBrush(Qt.NoBrush)
        self.qp.setPen(self._pen(color, width))
        # Qt angles: 0 = 3 o'clock, positive = counter-clockwise, in
        # 1/16th-of-a-degree units — same convention Tk's create_arc uses.
        self.qp.drawArc(rect, int(start * 16), int(extent * 16))


def _q(color):
    from PySide6.QtGui import QColor
    return QColor(color)


def _paint_icon(p: _Painter, cx, cy, kind, color, s, frame=0):
    w = max(1.2, s * 0.16)
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
    elif kind == "circle":
        p.oval(cx - s * 0.75, cy - s * 0.75, cx + s * 0.75, cy + s * 0.75, outline=color, width=w)
    elif kind == "appimage":
        p.polygon([
            cx - s * 0.7, cy - s * 0.4,
            cx + s * 0.4, cy - s * 0.7,
            cx + s * 0.7, cy + s * 0.4,
            cx - s * 0.4, cy + s * 0.7
        ], outline=color, width=w)
        p.polygon([
            cx - s * 0.2, cy + s * 0.3,
            cx, cy - s * 0.3,
            cx + s * 0.2, cy + s * 0.3
        ], outline=color, width=w)
    elif kind in ("gimp", "photogimp"):
        p.polygon([cx - s * 0.5, cy - s * 0.3, cx - s * 0.7, cy - s * 0.7, cx - s * 0.2, cy - s * 0.4], outline=color, width=w)
        p.polygon([cx + s * 0.2, cy - s * 0.4, cx + s * 0.7, cy - s * 0.7, cx + s * 0.5, cy - s * 0.3], outline=color, width=w)
        p.oval(cx - s * 0.6, cy - s * 0.4, cx + s * 0.6, cy + s * 0.5, outline=color, width=w)
        p.oval(cx - s * 0.85, cy - s * 0.1, cx - s * 0.5, cy + s * 0.25, color=color)
        p.oval(cx - s * 0.35, cy - s * 0.3, cx + s * 0.05, cy + s * 0.1, outline=color, width=w)
        p.oval(cx - s * 0.05, cy - s * 0.3, cx + s * 0.35, cy + s * 0.1, outline=color, width=w)
        p.oval(cx - s * 0.22, cy - s * 0.18, cx - s * 0.08, cy - s * 0.04, color=color)
        p.oval(cx + s * 0.08, cy - s * 0.18, cx + s * 0.22, cy - s * 0.04, color=color)
        p.arc(cx - s * 0.3, cy + s * 0.05, cx + s * 0.4, cy + s * 0.4, 200, 120, color, width=w)
        if kind == "photogimp":
            p.line([cx + s * 0.05, cy + s * 0.25, cx + s * 0.65, cy + s * 0.55], color, width=max(2.5, s * 0.18))
            p.polygon([cx + s * 0.65, cy + s * 0.55, cx + s * 0.85, cy + s * 0.75, cx + s * 0.75, cy + s * 0.5], color=color)
    elif kind == "gmic":
        p.oval(cx - s * 0.8, cy + s * 0.4, cx + s * 0.8, cy + s * 0.7, outline=color, width=w)
        p.polygon([cx - s * 0.45, cy + s * 0.45, cx, cy - s * 0.75, cx + s * 0.45, cy + s * 0.45], outline=color, width=w)
        p.line([cx - s * 0.6, cy - s * 0.3, cx - s * 0.4, cy - s * 0.3], color, width=w)
        p.line([cx - s * 0.5, cy - s * 0.4, cx - s * 0.5, cy - s * 0.2], color, width=w)
        p.line([cx + s * 0.4, cy - s * 0.1, cx + s * 0.6, cy - s * 0.1], color, width=w)
        p.line([cx + s * 0.5, cy - s * 0.2, cx + s * 0.5, cy], color, width=w)
    elif kind == "batcher":
        # Card 1 (Back, top-right offset)
        p.rect(cx - s * 0.2, cy - s * 0.75, cx + s * 0.7, cy + s * 0.15, outline=color, width=w, radius=s * 0.1)
        # Card 2 (Middle offset)
        p.rect(cx - s * 0.45, cy - s * 0.45, cx + s * 0.45, cy + s * 0.45, outline=color, width=w, radius=s * 0.1)
        # Card 3 (Front main focus)
        p.rect(cx - s * 0.7, cy - s * 0.15, cx + s * 0.2, cy + s * 0.75, outline=color, width=w, radius=s * 0.1)
        # Layer / batch lines inside front card
        lw = max(1.5, w * 0.9)
        p.line([cx - s * 0.5, cy + s * 0.05, cx, cy + s * 0.05], color, width=lw)
        p.line([cx - s * 0.5, cy + s * 0.3, cx, cy + s * 0.3], color, width=lw)
        p.line([cx - s * 0.5, cy + s * 0.55, cx - s * 0.15, cy + s * 0.55], color, width=lw)
    elif kind == "arch":
        p.polygon([cx, cy - s * 0.95, cx - s * 0.8, cy + s * 0.75, cx, cy + s * 0.35, cx + s * 0.8, cy + s * 0.75], outline=color, width=w)
        p.polygon([cx, cy - s * 0.4, cx - s * 0.45, cy + s * 0.45, cx, cy + s * 0.22, cx + s * 0.45, cy + s * 0.45], color=color)
    elif kind == "debian":
        p.oval(cx - s * 0.75, cy - s * 0.75, cx + s * 0.75, cy + s * 0.75, outline=color, width=w)
        p.arc(cx - s * 0.45, cy - s * 0.45, cx + s * 0.45, cy + s * 0.45, 90, 270, color, width=w)
        p.arc(cx - s * 0.2, cy - s * 0.2, cx + s * 0.2, cy + s * 0.2, 0, 180, color, width=w)
    elif kind == "ubuntu":
        p.oval(cx - s * 0.75, cy - s * 0.75, cx + s * 0.75, cy + s * 0.75, outline=color, width=w)
        for angle in (0, 120, 240):
            rad = math.radians(angle)
            px = cx + math.cos(rad) * s * 0.65
            py = cy + math.sin(rad) * s * 0.65
            p.oval(px - s * 0.18, py - s * 0.18, px + s * 0.18, py + s * 0.18, color=color)
    elif kind == "fedora":
        p.oval(cx - s * 0.8, cy - s * 0.8, cx + s * 0.8, cy + s * 0.8, outline=color, width=w)
        p.arc(cx - s * 0.4, cy - s * 0.4, cx + s * 0.1, cy + s * 0.4, 45, 270, color, width=w)
        p.line([cx - s * 0.35, cy, cx + s * 0.25, cy], color, width=w)
    elif kind == "opensuse":
        p.oval(cx - s * 0.8, cy - s * 0.6, cx + s * 0.8, cy + s * 0.6, outline=color, width=w)
        p.oval(cx - s * 0.2, cy - s * 0.2, cx + s * 0.2, cy + s * 0.2, color=color)
    elif kind == "linux":
        p.oval(cx - s * 0.5, cy - s * 0.8, cx + s * 0.5, cy + s * 0.8, outline=color, width=w)
        p.oval(cx - s * 0.25, cy - s * 0.4, cx + s * 0.25, cy, color=color)
        p.oval(cx - s * 0.15, cy - s * 0.65, cx - s * 0.05, cy - s * 0.55, color=color)
        p.oval(cx + s * 0.05, cy - s * 0.65, cx + s * 0.15, cy - s * 0.55, color=color)
        p.polygon([cx - s * 0.1, cy - s * 0.5, cx + s * 0.1, cy - s * 0.5, cx, cy - s * 0.4], color=WARNING)
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
    elif kind in ("trash", "download"):
        # "download" is treated as an alias of "trash"'s geometry-free
        # cousin "install" below in the button-glyph map; kept here only
        # so an unqualified _paint_icon("download", ...) call doesn't
        # silently no-op if some future page code uses that name.
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
        p.oval(cx - 1.4, cy + s * 0.42, cx + 1.4, cy + s * 0.5, color=color)
    elif kind == "info":
        p.oval(cx - s * 0.85, cy - s * 0.85, cx + s * 0.85, cy + s * 0.85, outline=color, width=w)
        p.line([cx, cy - s * 0.05, cx, cy + s * 0.55], color, width=w)
        p.oval(cx - 1.2, cy - s * 0.55, cx + 1.2, cy - s * 0.3, color=color)
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


_ICON_PIXMAP_CACHE: dict = {}


def render_icon_pixmap(kind: str, color: str = TEXT, size: int = 20, frame: int = 0) -> QPixmap:
    """Render one icon to a QPixmap, cached by (kind, color, size, frame) —
    the Qt counterpart of the Tk engine's render_icon_photo()."""
    key = (kind, color, size, frame)
    cached = _ICON_PIXMAP_CACHE.get(key)
    if cached is not None:
        return cached
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    qp = QPainter(image)
    qp.setRenderHint(QPainter.Antialiasing, True)
    _paint_icon(_Painter(qp), size / 2, size / 2, kind, color, size * 0.36, frame)
    qp.end()
    pixmap = QPixmap.fromImage(image)
    _ICON_PIXMAP_CACHE[key] = pixmap
    return pixmap


def render_icon(kind: str, color: str = TEXT, size: int = 18, frame: int = 0) -> QIcon:
    """QIcon wrapping render_icon_pixmap() — the Qt counterpart of the Tk
    engine's render_ctk_image(), used for QPushButton.setIcon()."""
    return QIcon(render_icon_pixmap(kind, color, size, frame))


def paint_icon_on(painter: QPainter, cx: float, cy: float, kind: str, color: str = TEXT, s: float = 7,
                   frame: int = 0) -> None:
    """Draw one icon directly with an already-open QPainter — the Qt
    counterpart of the Tk engine's draw_icon(), useful inside a custom
    paintEvent (e.g. an animated spinner)."""
    _paint_icon(_Painter(painter), cx, cy, kind, color, s, frame)


def icon_label(parent, kind: str, color: str = TEXT, size: int = 20):
    """QLabel showing one rendered icon — the Qt counterpart of the Tk
    engine's icon_canvas(). Returned widget has a transparent background
    so it sits correctly over a RoundedCard/callout background."""
    from PySide6.QtWidgets import QLabel
    lbl = QLabel(parent)
    lbl.setPixmap(render_icon_pixmap(kind, color, size))
    lbl.setFixedSize(size, size)
    lbl.setStyleSheet("background: transparent;")
    return lbl
