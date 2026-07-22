"""Shared install-progress screen: runs a list[PlannedAction]
sequentially in one background thread, showing interactive step cards
and a per-step dedicated terminal log panel."""

from __future__ import annotations

from ...compat import ctk, tk
from ...job import Job
from ...plan import PlannedAction
from ..icons import blit_icon
from ..theme import (
    ACCENT, BG, CARD_BG, CARD_BORDER, DANGER, F_BODY, F_BODY_B,
    F_H2, F_MONO, F_SMALL, F_SMALL_B, LOG_BG, SUCCESS, TEXT, TEXT_MUTED,
)
from ..widgets import ProgressBar, RoundedButton

# Pixels wide for each step card
_CARD_W = 210
_CARD_H = 92
_CARD_RADIUS = 14
_STEP_AREA_H = _CARD_H + 20  # canvas height for the cards strip


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
        self._spinner_after_id = None
        # idx -> the card's tiny status-icon Canvas, so the spinner can be
        # repainted in place every tick instead of tearing down every card.
        self._card_icon_canvases: list[tk.Canvas | None] = [None] * self.exec_total

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

    def _render_install_progress(self):
        self.current_screen = "installing"
        for w in self.root_frame.winfo_children():
            w.destroy()

        content = tk.Frame(self.root_frame, bg=BG)
        content.pack(fill="both", expand=True, padx=28, pady=20)

        # ---- Title / sub-text / progress bar ----
        has_errors = any(s == "failed" for s in self.step_statuses)
        title_text = (
            ("Installation finished with issues" if has_errors else "Installation finished")
            if self.exec_finished
            else "Installing…"
        )
        title_fg = DANGER if (self.exec_finished and has_errors) else TEXT

        self.exec_title_lbl = tk.Label(
            content, text=title_text, bg=BG, fg=title_fg, font=F_H2
        )
        self.exec_title_lbl.pack(anchor="w")

        self.exec_step_lbl = tk.Label(
            content, text=self._exec_progress_text(), bg=BG, fg=TEXT_MUTED, font=F_BODY
        )
        self.exec_step_lbl.pack(anchor="w", pady=(2, 8))

        self.exec_progress_bar = ProgressBar(content, width=760, height=10)
        self.exec_progress_bar.pack(anchor="w", fill="x")
        self.exec_progress_bar.set_fraction(
            self.exec_done / self.exec_total if self.exec_total else 1.0
        )

        # ---- Step-cards strip ----
        cards_section = tk.Frame(content, bg=BG)
        cards_section.pack(fill="x", pady=(14, 0))

        tk.Label(
            cards_section,
            text="STEPS  ·  click a card to view its terminal log",
            bg=BG, fg=TEXT_MUTED, font=F_SMALL_B,
        ).pack(anchor="w", pady=(0, 6))

        # Horizontally scrollable canvas holding the step cards
        strip_h = _STEP_AREA_H
        self._cards_canvas = tk.Canvas(
            cards_section, bg=BG, height=strip_h,
            highlightthickness=0, bd=0,
        )
        self._cards_frame = tk.Frame(self._cards_canvas, bg=BG)

        def _on_frame_configure(e):
            self._cards_canvas.configure(
                scrollregion=self._cards_canvas.bbox("all")
            )

        self._cards_frame.bind("<Configure>", _on_frame_configure)
        self._cards_win = self._cards_canvas.create_window(
            (0, 0), window=self._cards_frame, anchor="nw"
        )

        # Mouse-wheel horizontal scroll on the cards strip
        self._cards_canvas.bind(
            "<MouseWheel>",
            lambda e: self._cards_canvas.xview_scroll(
                -1 if e.delta > 0 else 1, "units"
            ),
        )
        self._cards_canvas.bind(
            "<Button-4>",
            lambda e: self._cards_canvas.xview_scroll(-1, "units"),
        )
        self._cards_canvas.bind(
            "<Button-5>",
            lambda e: self._cards_canvas.xview_scroll(1, "units"),
        )

        self._cards_canvas.pack(fill="x", expand=True)

        self.card_widgets: list[tk.Frame] = []
        self._build_step_cards()

        # ---- Per-step terminal panel ----
        log_panel = tk.Frame(
            content, bg=LOG_BG,
            highlightbackground=CARD_BORDER, highlightthickness=1,
        )
        log_panel.pack(fill="both", expand=True, pady=(10, 0))

        # Header bar
        log_header = tk.Frame(log_panel, bg="#16181d")
        log_header.pack(fill="x", side="top")

        self.term_header_lbl = tk.Label(
            log_header, text="> Terminal", bg="#16181d", fg=ACCENT,
            font=F_BODY_B, anchor="w",
        )
        self.term_header_lbl.pack(side="left", padx=12, pady=7)

        self.term_status_lbl = tk.Label(
            log_header, text="", bg="#16181d", fg=TEXT_MUTED, font=F_SMALL_B,
        )
        self.term_status_lbl.pack(side="right", padx=12, pady=7)

        # Monospace log output
        self.exec_log_text = ctk.CTkTextbox(
            log_panel, fg_color=LOG_BG, text_color=TEXT,
            corner_radius=0, border_width=0, wrap="none",
            font=F_MONO, state="disabled",
        )
        self.exec_log_text.pack(fill="both", expand=True, padx=2, pady=2)

        self._refresh_selected_step_view()

        # ---- Bottom button row ----
        btn_row = tk.Frame(content, bg=BG)
        btn_row.pack(fill="x", pady=(10, 0))
        if self.exec_finished:
            RoundedButton(
                btn_row, "Done", variant="primary", width=140,
                command=self.show_landing,
            ).pack(side="left")
        else:
            RoundedButton(
                btn_row, "Stop", icon="x", variant="danger", width=140,
                command=self._stop_plan_execution,
            ).pack(side="left")

        # Start spinner animation
        self._tick_spinner()

    # ------------------------------------------------------------------
    # Step cards
    # ------------------------------------------------------------------

    def _build_step_cards(self):
        for w in self._cards_frame.winfo_children():
            w.destroy()
        self.card_widgets.clear()
        self._card_icon_canvases = [None] * self.exec_total

        for idx, action in enumerate(self.plan_actions):
            card = self._make_card(self._cards_frame, idx, action)
            card.pack(side="left", padx=(0, 8), pady=4)
            self.card_widgets.append(card)

    def _make_card(self, parent, idx: int, action: PlannedAction) -> tk.Frame:
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

        card = ctk.CTkFrame(
            parent, fg_color=bg,
            border_color=bd, border_width=bw, corner_radius=_CARD_RADIUS,
            width=_CARD_W, height=_CARD_H,
        )
        card.pack_propagate(False)
        card.configure(cursor="hand2")

        # Top row: step number + status icon
        top = tk.Frame(card, bg=bg)
        top.pack(fill="x", padx=14, pady=(12, 0))

        num_color = ACCENT if is_sel else TEXT_MUTED
        num_lbl = tk.Label(
            top, text=f"Step {idx + 1}", bg=bg, fg=num_color, font=F_SMALL_B
        )
        num_lbl.pack(side="left")

        ic = tk.Canvas(top, width=14, height=14, bg=bg, highlightthickness=0, bd=0)
        ic.pack(side="right")
        self._card_icon_canvases[idx] = ic

        if status == "success":
            blit_icon(ic, 7, 7, "check", color=SUCCESS, size=14)
        elif status == "failed":
            blit_icon(ic, 7, 7, "x", color=DANGER, size=14)
        elif status == "running":
            blit_icon(ic, 7, 7, "spinner", color=ACCENT, size=14,
                      frame=self._spin_frame % 12)
        # pending: leave blank

        # Title (truncated only if it wouldn't fit even wrapped over 3 lines)
        lbl_text = action.label
        if len(lbl_text) > 42:
            lbl_text = lbl_text[:40] + "…"
        title_lbl = tk.Label(
            card, text=lbl_text, bg=bg, fg=TEXT, font=F_SMALL,
            anchor="w", wraplength=_CARD_W - 28, justify="left",
        )
        title_lbl.pack(fill="x", padx=14, pady=(6, 12))

        def _click(e=None, i=idx):
            self._select_step(i)

        for w in (card, top, num_lbl, ic, title_lbl):
            w.bind("<Button-1>", _click)

        return card

    def _select_step(self, idx: int):
        if idx < 0 or idx >= self.exec_total:
            return
        self.selected_step_idx = idx
        self._rebuild_cards_inplace()
        self._refresh_selected_step_view()

    def _rebuild_cards_inplace(self):
        """Rebuild only the card widgets, not the whole page."""
        if not hasattr(self, "_cards_frame") or not self._cards_frame.winfo_exists():
            return
        self._build_step_cards()

    # ------------------------------------------------------------------
    # Terminal view
    # ------------------------------------------------------------------

    def _refresh_selected_step_view(self):
        if not hasattr(self, "exec_log_text") or not self.exec_log_text.winfo_exists():
            return

        idx = self.selected_step_idx
        if not (0 <= idx < self.exec_total):
            return

        action = self.plan_actions[idx]
        status = self.step_statuses[idx]

        self.term_header_lbl.configure(
            text=f"> Step {idx + 1}: {action.label}"
        )
        status_text, status_fg = {
            "pending":  ("● Pending",  TEXT_MUTED),
            "running":  ("⏳ Running…", ACCENT),
            "success":  ("✔ Success",  SUCCESS),
            "failed":   ("✖ Failed",   DANGER),
        }.get(status, ("", TEXT_MUTED))
        self.term_status_lbl.configure(text=status_text, fg=status_fg)

        text = self.exec_log_text
        text.configure(state="normal")
        text.delete("1.0", "end")
        lines = self.step_logs[idx]
        if lines:
            text.insert("end", "\n".join(lines) + "\n")
        elif status == "pending":
            text.insert("end", f"[Step {idx + 1} is waiting to start…]\n")
        elif status == "running":
            text.insert("end", f"[Step {idx + 1} started, waiting for output…]\n")
        text.see("end")
        text.configure(state="disabled")

    # ------------------------------------------------------------------
    # Log pump (called from app._drain_log_queue)
    # ------------------------------------------------------------------

    def _on_log_lines_arrived(self, msgs: list[str]):
        """Route incoming log lines to the active step's buffer."""
        if not msgs:
            return

        idx = self.active_step_idx
        if not (0 <= idx < self.exec_total):
            return

        self.step_logs[idx].extend(msgs)
        del self.step_logs[idx][:-2000]  # keep at most 2000 lines per step

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

        # If user is watching this step, append live to the textbox
        if self.selected_step_idx == idx:
            if hasattr(self, "exec_log_text") and self.exec_log_text.winfo_exists():
                text = self.exec_log_text
                text.configure(state="normal")
                text.insert("end", "\n".join(msgs) + "\n")
                over = int(text.index("end-1c").split(".")[0]) - 2000
                if over > 0:
                    text.delete("1.0", f"{over + 1}.0")
                text.see("end")
                text.configure(state="disabled")

    # ------------------------------------------------------------------
    # Progress updates
    # ------------------------------------------------------------------

    def _bump_exec_progress(self):
        if hasattr(self, "exec_step_lbl") and self.exec_step_lbl.winfo_exists():
            self.exec_step_lbl.configure(text=self._exec_progress_text())
        if hasattr(self, "exec_title_lbl") and self.exec_title_lbl.winfo_exists():
            has_errors = any(s == "failed" for s in self.step_statuses)
            if self.exec_finished:
                t = "Installation finished with issues" if has_errors else "Installation finished"
                self.exec_title_lbl.configure(
                    text=t, fg=DANGER if has_errors else TEXT
                )
        if hasattr(self, "exec_progress_bar") and self.exec_progress_bar.winfo_exists():
            self.exec_progress_bar.set_fraction(
                self.exec_done / self.exec_total if self.exec_total else 1.0
            )
        self._rebuild_cards_inplace()
        self._refresh_selected_step_view()

    # ------------------------------------------------------------------
    # Spinner animation (runs independently from log updates)
    # ------------------------------------------------------------------

    def _tick_spinner(self):
        if not hasattr(self, "_cards_frame") or not self._cards_frame.winfo_exists():
            return
        self._spin_frame += 1
        # Repaint just the tiny status-icon canvas of whichever card(s) are
        # "running" — NOT a full _rebuild_cards_inplace(). Tearing down and
        # re-packing every card (frames, labels, bindings, ...) on every
        # 90ms tick is what caused the whole step strip to visibly flicker
        # for as long as any step was running; redrawing one 14x14 canvas
        # in place is effectively free and keeps the rest of the UI static.
        for idx, status in enumerate(self.step_statuses):
            if status != "running":
                continue
            canvas = self._card_icon_canvases[idx] if idx < len(self._card_icon_canvases) else None
            if canvas is not None and canvas.winfo_exists():
                canvas.delete("all")
                blit_icon(canvas, 7, 7, "spinner", color=ACCENT, size=14,
                          frame=self._spin_frame % 12)
        self._spinner_after_id = self.root.after(90, self._tick_spinner)

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
                self.root.after(0, self._bump_exec_progress)

                job.log(f"→ Step {i + 1}: {action.label}")
                try:
                    action.run(job)
                    if self.step_statuses[i] != "failed":
                        self.step_statuses[i] = "success"
                except Exception as e:
                    job.log(f"ERROR during {action.label}: {e}")
                    self.step_statuses[i] = "failed"

                self.exec_done += 1
                self.root.after(0, self._bump_exec_progress)

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
        if self._spinner_after_id is not None:
            try:
                self.root.after_cancel(self._spinner_after_id)
            except Exception:
                pass
            self._spinner_after_id = None
        self._render_install_progress()
