"""LazyGimpApp — root-window plumbing shared by every screen: theming
(applied by the caller, see ``lazygimp/gui/__init__.py``), the status
bar, the background-job runner, the log pump and global keyboard
shortcuts. PySide6 port of ``lazygimp/gui/app.py``. The screens
themselves live in ``pages/`` as mixins; this class just composes them
(landing / uninstall / wizard / install-progress) — same convention as
the Tk ``LazyGimpApp``.

Integration note (the one real structural difference from the Tk
original): ``InstallProgressPage`` (``pages/progress.py``) already owns
its own ``self.log_queue``-draining ``QTimer`` while a plan is running,
so its standalone smoke test can build/drive the page without this
app.py existing at all. The Tk ``LazyGimpApp`` had exactly one
``log_queue`` consumer (``_drain_log_queue``, polled via
``root.after``), which both updated the status bar text AND forwarded
lines to the install-progress page when that screen was active. Two
independent consumers calling ``Queue.get_nowait()`` on the *same*
queue would race and steal lines from each other, so this class's own
status-bar pump (``_status_pump_tick``) explicitly does NOT touch
``self.log_queue`` while ``self.current_screen == "installing"`` —
it mirrors the tail of ``InstallProgressPage``'s own per-step buffer
instead. See ``_status_pump_tick`` below for the full reasoning.
"""
from __future__ import annotations

import queue
import threading

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget,
)

from ..hardware import detect_hardware
from ..job import Job
from ..plan import InstallPlan, PlannedAction, WizardStep
from .dialogs import QPasswordPrompt, themed_info
from .icons import render_icon_pixmap
from .pages.landing import LandingPage
from .pages.progress import InstallProgressPage
from .pages.uninstall import UninstallPage
from .pages.wizard import WizardPages
from .theme import ACCENT, F_SMALL, TEXT_MUTED, qfont


def _widget_alive(widget) -> bool:
    """True if the underlying Qt C++ object hasn't been torn down yet —
    same guard used throughout ``pages/progress.py``, needed here for
    the same reason: avoid touching a widget from a timer callback after
    a screen swap has already deleted it."""
    if widget is None:
        return False
    try:
        widget.isVisible()
        return True
    except RuntimeError:
        return False


class _MainThreadCallback(QObject):
    """Marshals a background-thread callback onto the GUI thread — same
    QueuedConnection-via-own-slot pattern documented in ``dialogs.py``'s
    ``QPasswordPrompt`` and ``pages/progress.py``'s ``_ProgressBridge``:
    connecting straight to a plain (non-QObject) Python callable does
    not reliably queue onto the GUI thread, only a bound slot of a
    QObject does."""

    trigger = Signal()

    def __init__(self, callback):
        super().__init__()
        self._callback = callback
        self.trigger.connect(self._deliver, Qt.QueuedConnection)

    def _deliver(self):
        self._callback()


class _GlobalKeyFilter(QObject):
    """Application-wide key event tap — the Qt counterpart of the Tk
    engine's ``root.bind("<Key>", self._on_global_key)``. Tk's bindtags
    mechanism delivers every keypress to a toplevel's own binding in
    addition to whichever widget has focus; the equivalent in Qt is an
    event filter installed on the QApplication itself (not just the
    main window), since a filter installed on a single widget only ever
    sees events addressed to that widget, not to its focused
    descendants (a QLineEdit inside the wizard, say)."""

    def __init__(self, app_obj: "LazyGimpApp"):
        super().__init__()
        self._app = app_obj

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            try:
                self._app._on_global_key(event)
            except Exception:
                # A global shortcut handler must never take the whole
                # app down — same "don't let a callback crash the event
                # loop" spirit as the Tk engine's own callback-exception
                # handling.
                pass
        return False


# Qt.Key_* -> the same lowercase keysym-like strings the Tk engine's
# _on_global_key already branches on, so the branching logic below can
# stay a straight port instead of being rewritten around Qt's enum.
_KEY_NAMES = {
    Qt.Key_Backspace: "backspace",
    Qt.Key_Return: "return",
    Qt.Key_Enter: "return",
    Qt.Key_Escape: "escape",
    Qt.Key_Left: "left",
    Qt.Key_Right: "right",
    Qt.Key_Up: "up",
    Qt.Key_Down: "down",
    Qt.Key_PageUp: "prior",
    Qt.Key_PageDown: "next",
    Qt.Key_Space: "space",
    Qt.Key_1: "1", Qt.Key_2: "2", Qt.Key_3: "3", Qt.Key_4: "4", Qt.Key_5: "5",
    Qt.Key_6: "6", Qt.Key_7: "7", Qt.Key_8: "8", Qt.Key_9: "9",
    Qt.Key_A: "a", Qt.Key_B: "b", Qt.Key_G: "g", Qt.Key_I: "i", Qt.Key_P: "p",
    Qt.Key_Q: "q", Qt.Key_S: "s", Qt.Key_T: "t", Qt.Key_U: "u",
}


class LazyGimpApp(LandingPage, UninstallPage, WizardPages, InstallProgressPage):
    _STATUS_MAX_CHARS = 160

    def __init__(self, root: QMainWindow):
        self.root = root
        self.window = root  # alias some dialogs.py helpers look for (show_snackbar)
        root.setWindowTitle("LazyGimp installer")
        root.setFixedSize(960, 680)

        app_icon = QIcon(render_icon_pixmap("photogimp", ACCENT, 64))
        root.setWindowIcon(app_icon)
        app_instance = QApplication.instance()
        if app_instance is not None:
            app_instance.setWindowIcon(app_icon)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.busy = False
        self.current_job = None
        self.current_screen = "landing"
        self.hw = detect_hardware()
        self.password_prompt = QPasswordPrompt(root)
        self._job_bridges: list[_MainThreadCallback] = []

        # Wizard/plan state — (re)initialized fresh by show_wizard()/
        # show_install_progress() each time either screen is entered,
        # same as the Tk original.
        self.plan = InstallPlan()
        self.wizard_steps: list[WizardStep] = []
        self.wizard_index = 0
        self.plan_actions: list[PlannedAction] = []

        self.root_frame = QWidget(root)
        root_layout = QVBoxLayout(self.root_frame)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root.setCentralWidget(self.root_frame)

        # Status-bar widgets only exist once a screen that calls
        # _build_status_bar() has been shown at least once (only
        # uninstall.py does, matching the Tk original) — every method
        # that touches them guards with hasattr()/_widget_alive().
        self._status_spin_timer: QTimer | None = None
        self._status_spin_frame = 0
        self._status_spinning = False

        self._key_filter = _GlobalKeyFilter(self)
        app_instance = QApplication.instance()
        if app_instance is not None:
            app_instance.installEventFilter(self._key_filter)

        self.show_landing()

        # App-level status-bar pump — the Qt counterpart of the Tk
        # engine's self-rescheduling root.after(150, self._drain_log_queue)
        # loop. Named differently from InstallProgressPage's own
        # _drain_log_queue (which this class also inherits) on purpose:
        # see the module docstring for why the two must never both
        # consume self.log_queue at the same time.
        self._status_timer = QTimer(root)
        self._status_timer.timeout.connect(self._status_pump_tick)
        self._status_timer.start(150)

    # ---- status bar -----------------------------------------------------

    def _build_status_bar(self, parent):
        layout = parent.layout()
        if layout is None:
            layout = QVBoxLayout(parent)
            layout.setContentsMargins(0, 0, 0, 0)

        bar = QWidget(parent)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(26, 0, 26, 14)
        bar_layout.setSpacing(8)

        self.status_spinner_label = QLabel(bar)
        self.status_spinner_label.setFixedSize(16, 16)
        self.status_spinner_label.setStyleSheet("background: transparent;")
        bar_layout.addWidget(self.status_spinner_label)

        self.status_label = QLabel(
            "Full log is also printed to the terminal this was launched from.", bar)
        self.status_label.setFont(qfont(F_SMALL))
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        bar_layout.addWidget(self.status_label, 1)

        layout.addWidget(bar)

        self._status_spin_frame = 0
        self._status_spinning = self.busy
        if self.busy:
            self._start_status_spin()

    def _start_status_spin(self):
        if self._status_spin_timer is None:
            self._status_spin_timer = QTimer(self.root)
            self._status_spin_timer.timeout.connect(self._tick_status_spin)
        self._status_spin_frame = 0
        self._status_spin_timer.start(90)

    def _tick_status_spin(self):
        if not self._status_spinning or not _widget_alive(getattr(self, "status_spinner_label", None)):
            if self._status_spin_timer is not None:
                self._status_spin_timer.stop()
            return
        self.status_spinner_label.setPixmap(
            render_icon_pixmap("spinner", ACCENT, size=16, frame=self._status_spin_frame % 12))
        self._status_spin_frame += 1

    def _set_status_text(self, text: str):
        if not hasattr(self, "status_label") or not _widget_alive(self.status_label):
            return
        clean = " ".join(text.replace("\r", " ").split())
        if len(clean) > self._STATUS_MAX_CHARS:
            clean = "…" + clean[-(self._STATUS_MAX_CHARS - 1):]
        self.status_label.setText(clean)

    # ---- log pump (status bar only — see module docstring) ---------------

    def _status_pump_tick(self):
        if self.current_screen == "installing":
            # InstallProgressPage owns its own log_queue-draining QTimer
            # for as long as a plan is running — do not also call
            # log_queue.get_nowait() here, that would race the two
            # timers over the same queue. Mirror the active step's
            # already-buffered tail into the status bar instead.
            idx = getattr(self, "active_step_idx", None)
            step_logs = getattr(self, "step_logs", None)
            if step_logs is not None and idx is not None and 0 <= idx < len(step_logs) and step_logs[idx]:
                self._set_status_text(step_logs[idx][-1])
            return

        msgs = []
        try:
            while True:
                msgs.append(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        if msgs:
            self._set_status_text(msgs[-1])

    # ---- background jobs -------------------------------------------------

    def set_busy(self, busy: bool):
        self.busy = busy
        if not hasattr(self, "status_spinner_label") or not _widget_alive(self.status_spinner_label):
            return
        self._status_spinning = busy
        if busy:
            self._start_status_spin()
        else:
            self.status_spinner_label.clear()
            if self._status_spin_timer is not None:
                self._status_spin_timer.stop()

    def run_in_background(self, fn, on_done=None):
        if self.busy:
            themed_info(self.root, "Busy", "Another operation is already running.")
            return
        self.set_busy(True)
        job = Job(self.log_queue, password_prompt=self.password_prompt)
        self.current_job = job

        def finished():
            if self.current_job is job:
                self.current_job = None
            self.set_busy(False)
            if on_done:
                on_done()

        bridge = _MainThreadCallback(finished)
        self._job_bridges.append(bridge)

        def wrapper():
            try:
                fn(job)
            except Exception as e:
                job.log(f"ERROR: {e}")
            finally:
                bridge.trigger.emit()

        threading.Thread(target=wrapper, daemon=True).start()

    def cancel_current_job(self):
        if self.current_job is not None:
            self.current_job.log("Cancel requested by user — stopping...")
            self.current_job.cancel()

    # ---- global keyboard shortcuts ---------------------------------------

    def _on_global_key(self, event):
        focused = QApplication.focusWidget()
        is_entry = isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox))

        key = _KEY_NAMES.get(event.key(), "")
        if not key:
            return
        modifiers = event.modifiers()
        is_alt = bool(modifiers & Qt.AltModifier)
        is_shift = bool(modifiers & Qt.ShiftModifier)

        # 1. Alt-based navigation (always active, even while typing)
        if is_alt:
            if key == "right":
                if (self.current_screen == "wizard" and hasattr(self, "wizard_steps")
                        and self.wizard_index < len(self.wizard_steps) - 1):
                    if self._wizard_can_advance():
                        self._wizard_advance()
                return
            elif key == "left":
                if self.current_screen == "wizard":
                    self._wizard_back()
                return
            elif key == "s":
                if self.current_screen == "wizard" and hasattr(self, "wizard_steps"):
                    step = self.wizard_steps[self.wizard_index]
                    if not step.prerequisite:
                        self._wizard_advance()
                return
            elif key == "i":
                if self.current_screen == "wizard" and hasattr(self, "wizard_steps"):
                    step = self.wizard_steps[self.wizard_index]
                    if step.key == "review":
                        self._wizard_start_install()
                return

        # 2. Prevent single-character shortcuts while typing in a text field
        if is_entry:
            return

        # 3. Single-character/arrow-key shortcuts when not typing
        if self.current_screen == "landing":
            if key in ("1", "q"):
                self.show_wizard()
                return
            elif key == "2":
                self.start_quick_setup()
                return
            elif key == "u":
                self.show_uninstall_confirm()
                return

        elif self.current_screen == "wizard" and hasattr(self, "wizard_steps"):
            step = self.wizard_steps[self.wizard_index]

            if key == "prior":
                scroller = getattr(self, "_wizard_scroller", None)
                if scroller:
                    scroller.page_up()
                return
            elif key == "next":
                scroller = getattr(self, "_wizard_scroller", None)
                if scroller:
                    scroller.page_down()
                return

            if key in ("right", "return", "down"):
                if step.key == "review" and key == "return":
                    self._wizard_start_install()
                elif self._wizard_can_advance():
                    self._wizard_advance()
                return
            elif key in ("left", "escape", "backspace", "up"):
                self._wizard_back()
                return
            elif key == "s":
                if not step.prerequisite:
                    self._wizard_advance()
                return

            if step.key == "gimp":
                if key in ("1", "p"):
                    self._wizard_pick_gimp_method("pm")
                elif key in ("2", "a"):
                    self._wizard_pick_gimp_method("appimage")

            elif step.key == "components":
                if key in ("1", "p"):
                    handler = getattr(self, "_wizard_cards", {}).get("photogimp")
                    if handler:
                        handler()
                elif key in ("2", "g"):
                    handler = getattr(self, "_wizard_cards", {}).get("gmic")
                    if handler:
                        handler()
                elif key in ("3", "b"):
                    handler = getattr(self, "_wizard_cards", {}).get("batcher")
                    if handler:
                        handler()

            elif step.key == "sam":
                shift_num = key if (is_shift and key in ("1", "2", "3", "4")) else None

                if shift_num is not None:
                    active_fam = getattr(self, "_sam_expanded_family", "SAM1")
                    n = int(shift_num)
                    if active_fam == "SAM1":
                        model_labels = ["vit_b", "vit_l", "vit_h"]
                        if n <= len(model_labels):
                            handler = getattr(self, "_wizard_cards", {}).get(
                                f"sam_model:{model_labels[n - 1]}")
                            if handler:
                                handler()
                    elif active_fam == "SAM2":
                        model_labels = ["hiera_tiny", "hiera_small", "hiera_base_plus", "hiera_large"]
                        if n <= len(model_labels):
                            handler = getattr(self, "_wizard_cards", {}).get(
                                f"sam_model:{model_labels[n - 1]}")
                            if handler:
                                handler()
                    elif active_fam == "SAM3":
                        if n == 1:
                            handler = getattr(self, "_wizard_cards", {}).get("sam3")
                            if handler:
                                handler()
                    return

                if not is_shift:
                    if key == "1":
                        self.show_sam_category("SAM1")
                    elif key == "2":
                        self.show_sam_category("SAM2")
                    elif key == "3":
                        self.show_sam_category("SAM3")
                    elif key == "t":
                        entry = getattr(self, "_hf_token_entry", None)
                        if entry is not None and _widget_alive(entry):
                            entry.setFocus()
                    elif key == "p":
                        combo = getattr(self, "_pytorch_combo", None)
                        if combo is not None and _widget_alive(combo):
                            combo.setFocus()
                            try:
                                combo.showPopup()
                            except Exception:
                                pass
                    elif key == "a":
                        handler = getattr(self, "_wizard_cards", {}).get("queue_all_sam1")
                        if handler:
                            handler()
                    elif key == "b":
                        handler = getattr(self, "_wizard_cards", {}).get("queue_all_sam2")
                        if handler:
                            handler()

            elif step.key == "review":
                if key == "space":
                    self._wizard_start_install()
                elif key in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
                    idx = int(key) - 1
                    cmds = getattr(self, "_review_rows_discard_commands", [])
                    if 0 <= idx < len(cmds):
                        cmds[idx]()
