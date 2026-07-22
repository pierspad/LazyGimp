"""Themed modal dialogs, the snackbar and the sudo password prompt — Qt
port of ``lazygimp/gui/dialogs.py``.

The Tk engine builds its own overlay + borderless Toplevel by hand
because plain Tk has no native modal dialog chrome worth keeping. Qt
ships a real QDialog with its own modality/graphics stack, so this
module rides that instead of reimplementing an overlay — QDialog is set
frameless + styled with the same dark palette so it still matches the
rest of the app, but "click outside to dismiss" and centering-on-parent
come from Qt itself rather than hand-rolled event/geometry tracking.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from .icons import icon_label
from .theme import BG, CARD_BG, F_BODY, F_DIALOG_TITLE, TEXT, TEXT_MUTED, TONE_COLORS, qfont
from .widgets import RoundedButton, RoundedCard, autowrap_label


class _ThemedDialogBase(QDialog):
    """Frameless, centered-on-parent modal card. Shared chrome for
    themed_info/themed_confirm/QPasswordPrompt."""

    def __init__(self, parent, width=380):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setStyleSheet(f"QDialog {{ background-color: {BG}; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.card = RoundedCard(self, radius=18, pad=20, width=width)
        outer.addWidget(self.card)
        self.body_layout = QVBoxLayout(self.card.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)

    def _center_on_parent(self):
        parent = self.parentWidget()
        self.adjustSize()
        if parent is not None:
            geo = parent.geometry()
            x = parent.mapToGlobal(parent.rect().topLeft()).x() + max(0, (geo.width() - self.width()) // 2)
            y = parent.mapToGlobal(parent.rect().topLeft()).y() + max(0, (geo.height() - self.height()) // 2)
            self.move(x, y)

    def showEvent(self, event):
        super().showEvent(event)
        self._center_on_parent()


def themed_dialog(parent, title, message, kind="info") -> bool:
    """Blocking modal dialog. Returns True/False like the Tk engine's
    themed_dialog() (True = OK/Confirm, False = Cancel/dismissed)."""
    dlg = _ThemedDialogBase(parent, width=380)
    dlg.setWindowTitle(title)

    title_lbl = QLabel(title, dlg.card.body)
    title_lbl.setFont(qfont(F_DIALOG_TITLE))
    title_lbl.setStyleSheet(f"color: {TEXT}; background: transparent;")
    dlg.body_layout.addWidget(title_lbl)

    msg_lbl = autowrap_label(dlg.card.body, message, fg=TEXT_MUTED, bg=CARD_BG, font=F_BODY)
    dlg.body_layout.addSpacing(10)
    dlg.body_layout.addWidget(msg_lbl)
    dlg.body_layout.addSpacing(18)

    btn_row = QWidget(dlg.card.body)
    btn_layout = QHBoxLayout(btn_row)
    btn_layout.setContentsMargins(0, 0, 0, 0)
    btn_layout.addStretch(1)
    dlg.body_layout.addWidget(btn_row)

    result = {"value": False}

    def close(value: bool):
        result["value"] = value
        dlg.accept() if value else dlg.reject()

    if kind == "confirm":
        cancel = RoundedButton(btn_row, "Cancel [Esc]", variant="secondary", width=110, height=48,
                                command=lambda: close(False))
        confirm = RoundedButton(btn_row, "Confirm [Enter]", variant="danger", icon="trash", width=150,
                                 height=48, command=lambda: close(True))
        btn_layout.addWidget(cancel)
        btn_layout.addWidget(confirm)
    else:
        ok = RoundedButton(btn_row, "OK [Enter]", variant="primary", width=110, height=48,
                            command=lambda: close(True))
        btn_layout.addWidget(ok)

    dlg.card.finalize()
    dlg.exec()
    return result["value"]


def themed_info(parent, title, message) -> None:
    themed_dialog(parent, title, message, kind="info")


def themed_confirm(parent, title, message) -> bool:
    return bool(themed_dialog(parent, title, message, kind="confirm"))


def show_snackbar(app, message: str, tone: str = "warn", duration_ms: int = 2200):
    """Transient bottom-of-window toast. `app` is expected to expose
    `.window` (the QMainWindow/QWidget top-level) — the Qt counterpart
    of the Tk engine's `app.root`."""
    from PySide6.QtCore import QTimer

    bgc, fg = TONE_COLORS.get(tone, TONE_COLORS["warn"])
    parent_window = getattr(app, "window", None) or getattr(app, "root", None)

    win = QDialog(parent_window)
    win.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
    win.setAttribute(Qt.WA_TranslucentBackground, True)

    outer = QVBoxLayout(win)
    outer.setContentsMargins(0, 0, 0, 0)
    card = RoundedCard(win, bg=bgc, border=bgc, radius=14, pad=14)
    outer.addWidget(card)

    row_layout = QHBoxLayout(card.body)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(8)
    icon_kind = "warn" if tone == "warn" else ("x" if tone == "error" else "check")
    row_layout.addWidget(icon_label(card.body, icon_kind, color=fg, size=18))
    msg = QLabel(message, card.body)
    msg.setStyleSheet(f"color: {fg}; background: transparent; font-weight: 600;")
    row_layout.addWidget(msg)
    card.finalize()

    win.show()
    win.adjustSize()
    if parent_window is not None:
        geo = parent_window.geometry()
        top_left = parent_window.mapToGlobal(parent_window.rect().topLeft())
        x = top_left.x() + max(0, (geo.width() - win.width()) // 2)
        y = top_left.y() + geo.height() - 110
        win.move(x, y)

    QTimer.singleShot(duration_ms, win.close)
    return win


class QPasswordPrompt(QWidget):
    """Themed modal password prompt for the sudo install path — Qt
    counterpart of the Tk engine's TkPasswordPrompt.

    Same calling convention: construct once with the top-level window,
    then call the instance with a prompt string from ANY thread (the
    install worker thread calls this synchronously and blocks for the
    result, same as the Tk version's `root.after()` + threading.Event
    dance). Qt signal/slot connections across threads are queued
    automatically as long as this object lives on the GUI thread, which
    is what makes that dance safe here too.
    """

    _request = Signal(str, object)  # (prompt_text, threading.Event) -> result written into result_box

    def __init__(self, window):
        super().__init__()
        self.window = window
        self._request.connect(self._show, Qt.QueuedConnection)

    def __call__(self, prompt_text: str) -> str:
        box = {}
        done = threading.Event()
        self._request.emit(prompt_text, (box, done))
        done.wait()
        return box.get("pw") or ""

    def _show(self, prompt_text: str, ctx):
        box, done = ctx
        try:
            box["pw"] = self._ask(prompt_text)
        finally:
            done.set()

    def _ask(self, prompt_text: str) -> str:
        dlg = _ThemedDialogBase(self.window, width=420)
        dlg.setWindowTitle("Administrator password")

        title_lbl = QLabel("Administrator password", dlg.card.body)
        title_lbl.setFont(qfont(F_DIALOG_TITLE))
        title_lbl.setStyleSheet(f"color: {TEXT}; background: transparent;")
        dlg.body_layout.addWidget(title_lbl)

        msg = (
            f"{prompt_text}\n\nNeeded to install/remove system packages — your normal login "
            "password, sent straight to sudo, never stored."
        )
        msg_lbl = autowrap_label(dlg.card.body, msg, fg=TEXT_MUTED, bg=CARD_BG, font=F_BODY)
        dlg.body_layout.addSpacing(10)
        dlg.body_layout.addWidget(msg_lbl)
        dlg.body_layout.addSpacing(14)

        entry = QLineEdit(dlg.card.body)
        entry.setEchoMode(QLineEdit.Password)
        entry.setFixedWidth(360)
        dlg.body_layout.addWidget(entry)
        dlg.body_layout.addSpacing(16)

        btn_row = QWidget(dlg.card.body)
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addStretch(1)
        dlg.body_layout.addWidget(btn_row)

        result = {"pw": ""}

        def close(ok: bool):
            result["pw"] = entry.text() if ok else ""
            dlg.accept() if ok else dlg.reject()

        cancel = RoundedButton(btn_row, "Cancel", variant="secondary", width=90, command=lambda: close(False))
        unlock = RoundedButton(btn_row, "Unlock", variant="primary", width=110, command=lambda: close(True))
        btn_layout.addWidget(cancel)
        btn_layout.addWidget(unlock)

        entry.returnPressed.connect(lambda: close(True))
        dlg.card.finalize()
        entry.setFocus()
        dlg.exec()
        return result["pw"]


# Backwards-referenceable alias matching the Tk class name, in case
# page-porting agents grep for it directly.
TkPasswordPrompt = QPasswordPrompt
