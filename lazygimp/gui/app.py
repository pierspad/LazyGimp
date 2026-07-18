"""LazyGimpApp — root-window plumbing shared by every screen: theming, the
status bar, the background-job runner, the log pump and global scroll
routing. The screens themselves live in pages/ as mixins; this class just
composes them (landing / uninstall / wizard / install-progress).
"""
from __future__ import annotations

import queue
import threading

from ..compat import tk
from ..hardware import detect_hardware
from ..job import Job
from ..plan import InstallPlan, PlannedAction, WizardStep
from . import theme
from .dialogs import TkPasswordPrompt, themed_info
from .icons import blit_icon
from .pages import InstallProgressPage, LandingPage, UninstallPage, WizardPages
from .theme import ACCENT, BG, F_SMALL, TEXT_MUTED
from .widgets import ScrollableFrame


class LazyGimpApp(LandingPage, UninstallPage, WizardPages, InstallProgressPage):
    def __init__(self, root):
        self.root = root
        root.title("LazyGimp installer")
        root.geometry("1040x800")
        root.minsize(920, 660)
        root.configure(bg=BG)
        theme.apply_style(root)

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

        # ONE wheel binding for the whole app: events are routed to the
        # ScrollableFrame (if any) under the widget that received them —
        # no recursive per-child binding, no re-binding on page refresh.
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            root.bind_all(seq, self._on_global_wheel, add="+")

        self.root_frame = tk.Frame(root, bg=BG)
        self.root_frame.pack(fill="both", expand=True)
        self.show_landing()
        self.root.after(150, self._drain_log_queue)

    # ---- global mouse-wheel routing -----------------------------------

    def _on_global_wheel(self, event):
        w = event.widget
        if not isinstance(w, tk.Misc):  # e.g. destroyed widget or menu path
            return
        while w is not None and not isinstance(w, ScrollableFrame):
            w = getattr(w, "master", None)
        if w is None:
            return
        num = getattr(event, "num", None)
        delta = getattr(event, "delta", 0)
        if num == 4:
            w.scroll_units(-2)
        elif num == 5:
            w.scroll_units(2)
        elif delta:
            w.scroll_units(-1 if delta > 0 else 1)

    # ---- status bar -----------------------------------------------------

    def _build_status_bar(self, parent):
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x", padx=26, pady=(0, 14), side="bottom")
        self.status_spinner = tk.Canvas(bar, width=16, height=16, highlightthickness=0, bd=0, bg=BG)
        self.status_spinner.pack(side="left", padx=(0, 8))
        self.status_var = tk.StringVar(value="Full log is also printed to the terminal this was launched from.")
        tk.Label(bar, textvariable=self.status_var, bg=BG, fg=TEXT_MUTED, font=F_SMALL, anchor="w").pack(
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

    # ---- log pump --------------------------------------------------------

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
                # One batched Text insert per tick, however many lines
                # arrived — pip can emit hundreds of lines a second and a
                # per-line insert+scroll would stall the main thread.
                self._append_exec_log_lines(msgs)
        self.root.after(150, self._drain_log_queue)

    # ---- background jobs -------------------------------------------------

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
