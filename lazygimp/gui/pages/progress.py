"""Shared install-progress screen: runs a list[PlannedAction]
sequentially in one background thread, showing interactive step cards
and a per-step dedicated terminal log panel. Qt port of
``lazygimp/gui/pages/progress.py`` — see gui/README.md for the old
(Tk)->new (Qt) foundation API table this builds on.

Structural note: this stays a *mixin* (same convention as the Tk
version), not a QWidget subclass, so a future ``LazyGimpApp`` can
compose it alongside the landing/uninstall/wizard mixins exactly like
the Tk ``LazyGimpApp`` does. It assumes the composing host object
provides:

* ``self.root`` — the top-level QWidget/QMainWindow (used only for
  ``findChildren``-style introspection in tests; dialogs would parent
  to it too, though this page doesn't open any).
* ``self.root_frame`` — a QWidget whose layout gets cleared and
  rebuilt on every screen render, same role as the Tk engine's
  ``root_frame`` (a plain ``tk.Frame`` that every screen ``.pack()``ed
  itself into after destroying the previous screen's children).
* ``self.log_queue`` — a ``queue.Queue[str]`` shared with whatever
  ``Job`` the background plan runner logs through.
* ``self.run_in_background(fn, on_done=None)`` — runs ``fn(job)`` on a
  worker thread and calls ``on_done()`` back on the GUI thread when
  finished (mirrors the Tk engine's ``LazyGimpApp.run_in_background``).
* ``self.cancel_current_job()`` and ``self.show_landing()``.

None of that plumbing is ported here — it's the separate app.py
integration task the brief calls out — but the contract is identical
to the Tk mixin's, so wiring it up later should be a drop-in.
"""

from __future__ import annotations

import queue

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget,
)

from ...job import Job
from ...plan import PlannedAction
from ..icons import render_icon_pixmap
from ..theme import (
    ACCENT, BG, CARD_BG, CARD_BORDER, DANGER, F_BODY, F_BODY_B,
    F_H2, F_MONO, F_SMALL, F_SMALL_B, LOG_BG, SUCCESS, TEXT, TEXT_MUTED, qfont,
)
from ..widgets import ProgressBar, RoundedButton, RoundedCard, ScrollableFrame

# Pixels wide/tall for each step card — identical to the Tk version.
_CARD_W = 210
_CARD_H = 92
_CARD_RADIUS = 14
_STEP_AREA_H = _CARD_H + 20  # strip height, cards + a little breathing room

# Per-step log buffer cap — identical to the Tk version.
_MAX_LOG_LINES = 2000


def _widget_alive(widget) -> bool:
    """True if the underlying Qt C++ object hasn't been torn down yet —
    the Qt counterpart of the Tk engine's ``.winfo_exists()`` guards,
    which this page used throughout to avoid touching widgets from a
    stale callback after a screen swap."""
    if widget is None:
        return False
    try:
        widget.isVisible()
        return True
    except RuntimeError:
        return False


class _ProgressBridge(QObject):
    """Marshals mid-run UI-refresh requests from the background thread
    running the plan back onto the GUI thread — the Qt counterpart of
    the Tk engine's ``self.root.after(0, self._bump_exec_progress)``.

    The signal must be connected to a slot that is itself a bound method
    of a QObject (this one) with ``Qt.QueuedConnection`` explicitly —
    Qt/PySide6 can only determine "which thread should this call be
    delivered on" from a receiver QObject's thread affinity. Connecting
    straight to a plain Python method (``InstallProgressPage`` is a
    mixin, not a QObject) silently falls back to a *direct* call on
    whichever thread emits, which defeats the whole point and quietly
    mutates widgets off the GUI thread. Routing through this QObject's
    own ``_deliver`` slot (same pattern as ``dialogs.py``'s
    ``QPasswordPrompt``) is what actually makes ``updated.emit()`` safe
    to call from ``_run_plan``'s worker thread."""

    updated = Signal()

    def __init__(self, callback):
        super().__init__()
        self._callback = callback
        self.updated.connect(self._deliver, Qt.QueuedConnection)

    def _deliver(self):
        self._callback()


class _HorizontalWheelFilter(QObject):
    """Redirects vertical wheel deltas to the cards strip's horizontal
    scrollbar — the Qt counterpart of the Tk engine's explicit
    ``<MouseWheel>``/``<Button-4>``/``<Button-5>`` bindings on the
    cards canvas, which only ever needed to scroll sideways."""

    def __init__(self, scroll_area):
        super().__init__(scroll_area)
        self._scroll_area = scroll_area

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            bar = self._scroll_area.horizontalScrollBar()
            if bar is not None:
                delta = event.angleDelta().y() or event.angleDelta().x()
                bar.setValue(bar.value() - delta)
                return True
        return False


class InstallProgressPage:
    # ------------------------------------------------------------------
    # Public entry-point
    # ------------------------------------------------------------------

    def show_install_progress(self, actions: list[PlannedAction]):
        self.plan_actions = list(actions)
        self.exec_total = len(self.plan_actions)
        self.exec_done = 0
        self.exec_cancelled = False
        self.exec_finished = False

        # Per-step state
        self.step_logs: list[list[str]] = [[] for _ in self.plan_actions]
        # "pending" | "running" | "success" | "failed"
        self.step_statuses: list[str] = ["pending"] * self.exec_total
        self.active_step_idx: int = 0
        self.selected_step_idx: int = 0
        self._spin_frame: int = 0
        # idx -> the card's tiny status-icon QLabel, so the spinner can be
        # repainted in place every tick instead of tearing down every card.
        self._card_icon_labels: list[QLabel | None] = [None] * self.exec_total

        # Cross-thread bridge for the plan runner's mid-loop UI refreshes.
        self._bridge = _ProgressBridge(self._bump_exec_progress)

        # Spinner animation timer. Unlike the Tk engine's ``.after()``
        # chain (which had to manually reschedule itself on every single
        # tick, forever, for as long as the "installing" screen stayed
        # up — even after the run finished, since _render_install_progress
        # unconditionally re-called _tick_spinner at the end), a QTimer
        # already fires on its own schedule once started, so it's started
        # exactly once here and explicitly stopped in _finish_plan() —
        # cleaner and avoids waking up every 90ms for nothing once the
        # run is done.
        self._spinner_timer = QTimer()
        self._spinner_timer.timeout.connect(self._tick_spinner)
        self._spinner_timer.start(90)

        # Log-drain timer — Qt counterpart of the Tk engine's
        # ``root.after(150, self._drain_log_queue)`` poll loop, scoped to
        # this page instead of living in app.py (that port is out of
        # scope here; this keeps the page self-sufficient either way).
        self._log_timer = QTimer()
        self._log_timer.timeout.connect(self._drain_log_queue)
        self._log_timer.start(150)

        self._render_install_progress()
        self._run_plan()

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _exec_progress_text(self) -> str:
        if self.exec_total == 0:
            return "Nothing was queued."
        has_errors = any(s == "failed" for s in self.step_statuses)
        if self.exec_finished:
            if self.exec_cancelled:
                return f"Stopped after {self.exec_done} of {self.exec_total} steps."
            if has_errors:
                n = sum(1 for s in self.step_statuses if s == "failed")
                return (
                    f"Finished {self.exec_done} of {self.exec_total} steps "
                    f"({n} failed — click the red card(s) above to inspect)."
                )
            return f"Finished all {self.exec_total} steps successfully!"
        return f"Step {min(self.exec_done + 1, self.exec_total)} of {self.exec_total}"

    def _clear_root_frame(self):
        layout = self.root_frame.layout()
        if layout is None:
            layout = QVBoxLayout(self.root_frame)
            layout.setContentsMargins(0, 0, 0, 0)
            return layout
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        return layout

    def _render_install_progress(self):
        self.current_screen = "installing"
        root_layout = self._clear_root_frame()

        content = QWidget(self.root_frame)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 20, 28, 20)
        content_layout.setSpacing(0)
        root_layout.addWidget(content)

        # ---- Title / sub-text / progress bar ----
        has_errors = any(s == "failed" for s in self.step_statuses)
        title_text = (
            ("Installation finished with issues" if has_errors else "Installation finished")
            if self.exec_finished
            else "Installing…"
        )
        title_fg = DANGER if (self.exec_finished and has_errors) else TEXT

        self.exec_title_lbl = QLabel(title_text, content)
        self.exec_title_lbl.setFont(qfont(F_H2))
        self.exec_title_lbl.setStyleSheet(f"color: {title_fg}; background: transparent;")
        content_layout.addWidget(self.exec_title_lbl)

        self.exec_step_lbl = QLabel(self._exec_progress_text(), content)
        self.exec_step_lbl.setFont(qfont(F_BODY))
        self.exec_step_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        content_layout.addSpacing(2)
        content_layout.addWidget(self.exec_step_lbl)
        content_layout.addSpacing(6)

        self.exec_progress_bar = ProgressBar(content, width=760, height=10)
        self.exec_progress_bar.set_fraction(
            self.exec_done / self.exec_total if self.exec_total else 1.0
        )
        content_layout.addWidget(self.exec_progress_bar)

        # ---- Step-cards strip ----
        cards_section = QWidget(content)
        cards_section_layout = QVBoxLayout(cards_section)
        cards_section_layout.setContentsMargins(0, 14, 0, 0)
        cards_section_layout.setSpacing(6)
        content_layout.addWidget(cards_section)

        steps_lbl = QLabel("STEPS  ·  click a card to view its terminal log", cards_section)
        steps_lbl.setFont(qfont(F_SMALL_B))
        steps_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        cards_section_layout.addWidget(steps_lbl)

        # Horizontally scrollable strip holding the step cards. ScrollableFrame
        # is a plain QScrollArea wrapper (vertical by default); it's
        # reconfigured here (scrollbar policies + a wheel-redirect filter)
        # rather than extending widgets.py, since that foundation file is
        # shared with the other parallel page-porting agents.
        self._cards_scroll = ScrollableFrame(cards_section, bg=BG)
        self._cards_scroll.setFixedHeight(_STEP_AREA_H)
        self._cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._wheel_filter = _HorizontalWheelFilter(self._cards_scroll)
        self._cards_scroll.viewport().installEventFilter(self._wheel_filter)
        cards_section_layout.addWidget(self._cards_scroll)

        self._cards_layout = QHBoxLayout(self._cards_scroll.inner)
        self._cards_layout.setContentsMargins(2, 4, 2, 4)
        self._cards_layout.setSpacing(8)

        self.card_widgets: list[RoundedCard] = []
        self._build_step_cards()

        # ---- Per-step terminal panel ----
        log_panel = QFrame(content)
        log_panel.setStyleSheet(
            f"QFrame {{ background-color: {LOG_BG}; border: 1px solid {CARD_BORDER}; border-radius: 12px; }}"
        )
        log_panel_layout = QVBoxLayout(log_panel)
        log_panel_layout.setContentsMargins(2, 2, 2, 2)
        log_panel_layout.setSpacing(0)
        content_layout.addSpacing(10)
        content_layout.addWidget(log_panel, 1)

        # Header bar
        log_header = QWidget(log_panel)
        log_header.setStyleSheet("background-color: #16181d; border-top-left-radius: 10px; border-top-right-radius: 10px;")
        log_header_layout = QHBoxLayout(log_header)
        log_header_layout.setContentsMargins(12, 7, 12, 7)

        self.term_header_lbl = QLabel("> Terminal", log_header)
        self.term_header_lbl.setFont(qfont(F_BODY_B))
        self.term_header_lbl.setStyleSheet(f"color: {ACCENT}; background: transparent;")
        log_header_layout.addWidget(self.term_header_lbl)
        log_header_layout.addStretch(1)

        self.term_status_lbl = QLabel("", log_header)
        self.term_status_lbl.setFont(qfont(F_SMALL_B))
        self.term_status_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        log_header_layout.addWidget(self.term_status_lbl)

        log_panel_layout.addWidget(log_header)

        # Monospace log output
        self.exec_log_text = QPlainTextEdit(log_panel)
        self.exec_log_text.setReadOnly(True)
        self.exec_log_text.setFont(qfont(F_MONO))
        self.exec_log_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        # Qt's native block-count cap does the same job as the Tk version's
        # manual "delete everything before line N" trimming — simpler and
        # less error-prone than reimplementing that by hand here.
        self.exec_log_text.setMaximumBlockCount(_MAX_LOG_LINES)
        self.exec_log_text.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {LOG_BG}; color: {TEXT}; border: none; }}"
        )
        log_panel_layout.addWidget(self.exec_log_text, 1)

        self._refresh_selected_step_view()

        # ---- Bottom button row ----
        btn_row = QWidget(content)
        btn_row_layout = QHBoxLayout(btn_row)
        btn_row_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addSpacing(10)
        content_layout.addWidget(btn_row)
        if self.exec_finished:
            done_btn = RoundedButton(
                btn_row, "Done", variant="primary", width=140,
                command=self.show_landing,
            )
            btn_row_layout.addWidget(done_btn)
        else:
            stop_btn = RoundedButton(
                btn_row, "Stop", icon="x", variant="danger", width=140,
                command=self._stop_plan_execution,
            )
            btn_row_layout.addWidget(stop_btn)
        btn_row_layout.addStretch(1)

    # ------------------------------------------------------------------
    # Step cards
    # ------------------------------------------------------------------

    def _build_step_cards(self):
        layout = self._cards_layout
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.card_widgets = []
        self._card_icon_labels = [None] * self.exec_total

        for idx, action in enumerate(self.plan_actions):
            card = self._make_card(idx, action)
            layout.addWidget(card)
            self.card_widgets.append(card)
        layout.addStretch(1)

    def _make_card(self, idx: int, action: PlannedAction) -> RoundedCard:
        status = self.step_statuses[idx]
        is_sel = idx == self.selected_step_idx

        if is_sel:
            bd, bw, bg = ACCENT, 2, "#1e2535"
        elif status == "failed":
            bd, bw, bg = DANGER, 2, "#2a1519"
        elif status == "success":
            bd, bw, bg = SUCCESS, 1, CARD_BG
        elif status == "running":
            bd, bw, bg = ACCENT, 2, "#182030"
        else:
            bd, bw, bg = CARD_BORDER, 1, CARD_BG

        card_kwargs = dict(
            bg=bg, border=bd, radius=_CARD_RADIUS, pad=14,
            width=_CARD_W, height=_CARD_H,
            # Same tint on hover as at rest — the Tk version never
            # changed a card's fill on hover either, only the cursor.
            hover_bg=bg,
            command=lambda i=idx: self._select_step(i),
        )
        if bw == 2:
            card_kwargs["active_border"] = bd
            card_kwargs["active_width"] = 2
        card = RoundedCard(self._cards_scroll.inner, **card_kwargs)

        body_layout = QVBoxLayout(card.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(6)

        # Top row: step number + status icon
        top_row = QWidget(card.body)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)

        num_color = ACCENT if is_sel else TEXT_MUTED
        num_lbl = QLabel(f"Step {idx + 1}", top_row)
        num_lbl.setFont(qfont(F_SMALL_B))
        num_lbl.setStyleSheet(f"color: {num_color}; background: transparent;")
        top_layout.addWidget(num_lbl)
        top_layout.addStretch(1)

        icon_lbl = QLabel(top_row)
        icon_lbl.setFixedSize(14, 14)
        icon_lbl.setStyleSheet("background: transparent;")
        self._paint_card_icon(icon_lbl, status)
        top_layout.addWidget(icon_lbl)
        self._card_icon_labels[idx] = icon_lbl

        body_layout.addWidget(top_row)

        # Title (truncated only if it wouldn't fit even wrapped)
        lbl_text = action.label
        if len(lbl_text) > 42:
            lbl_text = lbl_text[:40] + "…"
        title_lbl = QLabel(lbl_text, card.body)
        title_lbl.setWordWrap(True)
        title_lbl.setFont(qfont(F_SMALL))
        title_lbl.setStyleSheet(f"color: {TEXT}; background: transparent;")
        body_layout.addWidget(title_lbl)
        body_layout.addStretch(1)

        card.finalize()
        return card

    def _paint_card_icon(self, label: QLabel, status: str):
        if status == "success":
            label.setPixmap(render_icon_pixmap("check", SUCCESS, size=14))
        elif status == "failed":
            label.setPixmap(render_icon_pixmap("x", DANGER, size=14))
        elif status == "running":
            label.setPixmap(
                render_icon_pixmap("spinner", ACCENT, size=14, frame=self._spin_frame % 12)
            )
        else:
            label.clear()  # pending: leave blank

    def _select_step(self, idx: int):
        if idx < 0 or idx >= self.exec_total:
            return
        self.selected_step_idx = idx
        self._rebuild_cards_inplace()
        self._refresh_selected_step_view()

    def _rebuild_cards_inplace(self):
        """Rebuild only the card widgets, not the whole page."""
        if not hasattr(self, "_cards_layout") or not _widget_alive(self._cards_scroll):
            return
        self._build_step_cards()

    # ------------------------------------------------------------------
    # Terminal view
    # ------------------------------------------------------------------

    def _scroll_log_to_end(self):
        bar = self.exec_log_text.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.maximum())

    def _refresh_selected_step_view(self):
        if not hasattr(self, "exec_log_text") or not _widget_alive(self.exec_log_text):
            return

        idx = self.selected_step_idx
        if not (0 <= idx < self.exec_total):
            return

        action = self.plan_actions[idx]
        status = self.step_statuses[idx]

        self.term_header_lbl.setText(f"> Step {idx + 1}: {action.label}")
        status_text, status_fg, bg_color = {
            "pending":  ("Pending",  TEXT_MUTED, "#20232a"),
            "running":  ("Running…", ACCENT,     "#1c2838"),
            "success":  ("Success",  SUCCESS,    "#162b22"),
            "failed":   ("Failed",   DANGER,     "#2e1b1d"),
        }.get(status, ("", TEXT_MUTED, "transparent"))
        self.term_status_lbl.setText(status_text)
        self.term_status_lbl.setStyleSheet(
            f"color: {status_fg}; background-color: {bg_color}; padding: 4px 12px; border-radius: 6px;"
        )

        text_widget = self.exec_log_text
        lines = self.step_logs[idx]
        if lines:
            text_widget.setPlainText("\n".join(lines) + "\n")
        elif status == "pending":
            text_widget.setPlainText(f"[Step {idx + 1} is waiting to start…]\n")
        elif status == "running":
            text_widget.setPlainText(f"[Step {idx + 1} started, waiting for output…]\n")
        else:
            text_widget.setPlainText("")
        self._scroll_log_to_end()

    # ------------------------------------------------------------------
    # Log pump
    # ------------------------------------------------------------------

    def _drain_log_queue(self):
        """QTimer-driven poll of ``self.log_queue`` — the Qt counterpart
        of the Tk engine's ``root.after(150, self._drain_log_queue)``,
        scoped to this page so it works standalone (e.g. under the smoke
        test) without depending on the app.py integration."""
        if not hasattr(self, "log_queue") or self.log_queue is None:
            return
        msgs = []
        try:
            while True:
                msgs.append(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        if msgs:
            self._on_log_lines_arrived(msgs)

    def _on_log_lines_arrived(self, msgs: list[str]):
        """Route incoming log lines to the active step's buffer."""
        if not msgs:
            return

        idx = self.active_step_idx
        if not (0 <= idx < self.exec_total):
            return

        for msg in msgs:
            is_prog = ("Installing " in msg and "%" in msg) or ("Downloading " in msg and "%" in msg)
            if is_prog and self.step_logs[idx]:
                last = self.step_logs[idx][-1]
                if ("Installing " in last and "%" in last) or ("Downloading " in last and "%" in last):
                    self.step_logs[idx][-1] = msg
                    continue
            self.step_logs[idx].append(msg)

        del self.step_logs[idx][:-_MAX_LOG_LINES]  # keep at most N lines per step

        # Heuristic failure detection from log text
        error_hints = (
            "Package manager install failed",
            "failed to synchronize all databases",
            "G'MIC install failed",
            "error: failed",
        )
        if self.step_statuses[idx] == "running":
            lower_batch = "\n".join(msgs).lower()
            if any(h.lower() in lower_batch for h in error_hints):
                self.step_statuses[idx] = "failed"
                self._rebuild_cards_inplace()

        # If user is watching this step, update live in the textbox
        if self.selected_step_idx == idx:
            if hasattr(self, "exec_log_text") and _widget_alive(self.exec_log_text):
                self.exec_log_text.setPlainText("\n".join(self.step_logs[idx]))
                self._scroll_log_to_end()

    # ------------------------------------------------------------------
    # Progress updates
    # ------------------------------------------------------------------

    def _bump_exec_progress(self):
        if hasattr(self, "exec_step_lbl") and _widget_alive(self.exec_step_lbl):
            self.exec_step_lbl.setText(self._exec_progress_text())
        if hasattr(self, "exec_title_lbl") and _widget_alive(self.exec_title_lbl):
            has_errors = any(s == "failed" for s in self.step_statuses)
            if self.exec_finished:
                t = "Installation finished with issues" if has_errors else "Installation finished"
                self.exec_title_lbl.setText(t)
                self.exec_title_lbl.setStyleSheet(
                    f"color: {DANGER if has_errors else TEXT}; background: transparent;"
                )
        if hasattr(self, "exec_progress_bar") and _widget_alive(self.exec_progress_bar):
            self.exec_progress_bar.set_fraction(
                self.exec_done / self.exec_total if self.exec_total else 1.0
            )
        self._rebuild_cards_inplace()
        self._refresh_selected_step_view()

    # ------------------------------------------------------------------
    # Spinner animation (runs independently from log updates)
    # ------------------------------------------------------------------

    def _tick_spinner(self):
        if not hasattr(self, "_cards_layout") or not _widget_alive(self._cards_scroll):
            return
        self._spin_frame += 1
        # Repaint just the tiny status-icon QLabel of whichever card(s)
        # are "running" — NOT a full _rebuild_cards_inplace(). Tearing
        # down and rebuilding every card (frames, labels, event filters,
        # ...) on every 90ms tick is what caused the whole step strip to
        # visibly flicker for as long as any step was running in the Tk
        # version; swapping one 14x14 QLabel's pixmap in place is
        # effectively free and keeps the rest of the UI static.
        for idx, status in enumerate(self.step_statuses):
            if status != "running":
                continue
            label = self._card_icon_labels[idx] if idx < len(self._card_icon_labels) else None
            if label is not None and _widget_alive(label):
                label.setPixmap(
                    render_icon_pixmap("spinner", ACCENT, size=14, frame=self._spin_frame % 12)
                )

    # ------------------------------------------------------------------
    # Plan runner
    # ------------------------------------------------------------------

    def _run_plan(self):
        actions = self.plan_actions

        def task(job: Job):
            for i, action in enumerate(actions):
                if job.cancel_event.is_set():
                    self.exec_cancelled = True
                    job.log(f"Stopped before: {action.label}")
                    break

                self.active_step_idx = i
                self.step_statuses[i] = "running"
                # Auto-follow: only switch the terminal view to the new step
                # if the user hasn't manually selected a different one.
                if self.selected_step_idx == i - 1 or i == 0:
                    self.selected_step_idx = i
                self._bridge.updated.emit()

                job.log(f"→ Step {i + 1}: {action.label}")
                try:
                    action.run(job)
                    if self.step_statuses[i] != "failed":
                        self.step_statuses[i] = "success"
                except Exception as e:
                    job.log(f"ERROR during {action.label}: {e}")
                    self.step_statuses[i] = "failed"

                self.exec_done += 1
                self._bridge.updated.emit()

            if not actions:
                job.log("Nothing was queued.")
            elif self.exec_cancelled:
                job.log("Stopped — whatever finished so far was left in place.")
            else:
                has_err = any(s == "failed" for s in self.step_statuses)
                if has_err:
                    job.log(
                        "Finished with errors in one or more steps. "
                        "Click the red card(s) above to see the details."
                    )
                else:
                    job.log("All done! Restart GIMP to see everything.")

        self.run_in_background(task, on_done=self._finish_plan)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _stop_plan_execution(self):
        self.cancel_current_job()

    def _finish_plan(self):
        self.exec_finished = True
        # Flush any tail messages (e.g. the final "All done!" line) that
        # were queued right before the worker thread exited but haven't
        # been drained by the timer yet.
        self._drain_log_queue()
        if self._spinner_timer.isActive():
            self._spinner_timer.stop()
        if self._log_timer.isActive():
            self._log_timer.stop()
        self._render_install_progress()
