"""Exercises InstallProgressPage (lazygimp/gui_qt/pages/progress.py)
inside a real QApplication and confirms nothing raises. Not a UI test
(no display needed) — run with:

    QT_QPA_PLATFORM=offscreen python3 -m lazygimp.gui_qt.pages._smoke_test_progress

Two passes:

1. A manual/direct pass that drives status transitions
   (pending -> running -> success/failed), log-line arrival and card
   clicks by calling the page's own internal methods directly —
   deterministic, no real threading involved.
2. A real end-to-end pass that calls show_install_progress() with a
   tiny fake host app (providing the run_in_background/log_queue/
   root_frame/etc. contract the page expects from its future app.py
   integration) and a handful of PlannedActions that exercise the
   success path, the heuristic-failure-from-log-text path, and the
   exception-raised path, then pumps the real Qt event loop until the
   background thread finishes and asserts the final state.
"""
from __future__ import annotations

import queue
import sys
import threading
import time


def main() -> int:
    from PySide6.QtCore import QObject, Qt, QTimer, Signal
    from PySide6.QtWidgets import QApplication, QMainWindow, QPlainTextEdit, QVBoxLayout, QWidget

    from lazygimp.gui_qt import theme
    from lazygimp.gui_qt.pages.progress import InstallProgressPage
    from lazygimp.gui_qt.widgets import RoundedButton
    from lazygimp.job import Job
    from lazygimp.plan import PlannedAction

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(theme.build_stylesheet())

    class _DoneBridge(QObject):
        """Same QueuedConnection-via-own-slot pattern as progress.py's
        _ProgressBridge — connecting straight to a plain (non-QObject)
        Python callable does not reliably queue onto the GUI thread."""

        done = Signal()

        def __init__(self, callback):
            super().__init__()
            self._callback = callback
            self.done.connect(self._deliver, Qt.QueuedConnection)

        def _deliver(self):
            self._callback()

    class FakeHostApp(InstallProgressPage):
        """Minimal stand-in for the future Qt LazyGimpApp, providing
        exactly the contract InstallProgressPage documents needing."""

        def __init__(self):
            self.window = QMainWindow()
            self.root = self.window
            central = QWidget()
            self.window.setCentralWidget(central)
            QVBoxLayout(central)
            self.root_frame = central
            self.log_queue: "queue.Queue[str]" = queue.Queue()
            self.current_screen = "landing"
            self.busy = False
            self.current_job = None
            self.landing_calls = 0
            self._bridges = []  # keep _DoneBridge instances alive

        def run_in_background(self, fn, on_done=None):
            self.busy = True
            job = Job(self.log_queue)
            self.current_job = job
            bridge = _DoneBridge(on_done) if on_done else None
            if bridge is not None:
                self._bridges.append(bridge)

            def wrapper():
                try:
                    fn(job)
                finally:
                    self.current_job = None
                    self.busy = False
                    if bridge is not None:
                        bridge.done.emit()

            threading.Thread(target=wrapper, daemon=True).start()

        def cancel_current_job(self):
            if self.current_job is not None:
                self.current_job.cancel()

        def show_landing(self):
            self.landing_calls += 1

    # ---- Pass 1: direct/manual state-machine drive, no real thread ----
    host1 = FakeHostApp()
    a1 = PlannedAction(key="a1", label="Install step one", kind="install", run=lambda job: None)
    a2 = PlannedAction(key="a2", label="Install step two", kind="install", run=lambda job: None)

    host1.plan_actions = [a1, a2]
    host1.exec_total = 2
    host1.exec_done = 0
    host1.exec_cancelled = False
    host1.exec_finished = False
    host1.step_logs = [[], []]
    host1.step_statuses = ["pending", "pending"]
    host1.active_step_idx = 0
    host1.selected_step_idx = 0
    host1._spin_frame = 0
    host1._card_icon_labels = [None, None]
    from lazygimp.gui_qt.pages.progress import _ProgressBridge
    host1._bridge = _ProgressBridge(host1._bump_exec_progress)
    host1._spinner_timer = QTimer()
    host1._spinner_timer.timeout.connect(host1._tick_spinner)
    host1._log_timer = QTimer()
    host1._log_timer.timeout.connect(host1._drain_log_queue)

    host1._render_install_progress()
    assert isinstance(host1.exec_log_text, QPlainTextEdit)
    assert len(host1.card_widgets) == 2
    assert "waiting to start" in host1.exec_log_text.toPlainText()

    # pending -> running
    host1.step_statuses[0] = "running"
    host1.active_step_idx = 0
    host1._bump_exec_progress()
    assert "started, waiting for output" in host1.exec_log_text.toPlainText()

    # spinner tick shouldn't raise and should update the running card's icon
    host1._tick_spinner()
    host1._tick_spinner()

    # simulate a log line arriving for the active (selected) step
    host1.log_queue.put("hello from step one")
    host1._drain_log_queue()
    assert "hello from step one" in host1.exec_log_text.toPlainText()
    assert host1.step_logs[0] == ["hello from step one"]

    # running -> success
    host1.step_statuses[0] = "success"
    host1.exec_done = 1
    host1._bump_exec_progress()

    # click card 2 (index 1, still pending)
    host1._select_step(1)
    assert host1.selected_step_idx == 1
    assert "waiting to start" in host1.exec_log_text.toPlainText()

    # out-of-range click is a no-op, must not raise
    host1._select_step(99)
    assert host1.selected_step_idx == 1
    host1._select_step(-1)
    assert host1.selected_step_idx == 1

    # heuristic failure detection while step 2 is "running"
    host1.step_statuses[1] = "running"
    host1.active_step_idx = 1
    host1._on_log_lines_arrived(["Package manager install failed: exit code 1"])
    assert host1.step_statuses[1] == "failed"
    assert "Failed" in host1.term_status_lbl.text() or host1.step_statuses[1] == "failed"

    # log-buffer capping: push way more than the 2000-line cap in one batch
    host1.step_statuses[1] = "running"  # heuristic already flipped it; force back to exercise cap only
    many_lines = [f"line {i}" for i in range(2500)]
    host1._on_log_lines_arrived(many_lines)
    assert len(host1.step_logs[1]) <= 2000
    assert host1.step_logs[1][-1] == "line 2499"

    # Stop button with no current_job must not raise
    host1._stop_plan_execution()

    print("PASS 1 OK — manual state-machine drive (pending/running/success/failed, "
          "log arrival, card clicks, log capping) completed without error.")

    # ---- Pass 2: real end-to-end run through show_install_progress() ----
    host2 = FakeHostApp()

    def ok_step(job):
        job.log("doing the thing")
        # Same reasoning as heuristic_fail_step's pause below: log routing
        # keys off "whichever step is active *when the drain timer next
        # fires*", exactly like the Tk original's `root.after(150, ...)`
        # poll. A real install action streams output over many drain
        # ticks; a fake action that logs once and returns instantly can
        # outrun the very first tick and have its line misattributed to
        # the step that starts right after it. Pause so the timer gets a
        # fair chance to drain this line while this step is still active.
        time.sleep(0.3)

    def heuristic_fail_step(job):
        job.log("Package manager install failed: simulated apt error")
        # Give the page's 150ms log-drain QTimer a chance to actually see
        # this step as "running" and flip it to "failed" before the plan
        # loop marks it "success" for having returned without raising —
        # real install actions stream several log lines over multiple
        # drain ticks via job.run_cmd(); a step that logs one line and
        # returns instantly (like this fake one) needs an explicit pause
        # here to exercise that same race honestly instead of racing past
        # it, since the drain timer only fires while the GUI event loop
        # (pumped by the deadline loop below) is spinning.
        time.sleep(0.3)

    def exception_fail_step(job):
        job.log("about to blow up")
        raise RuntimeError("boom")

    actions = [
        PlannedAction(key="ok", label="A perfectly fine step", kind="install", run=ok_step),
        PlannedAction(key="heuristic", label="A step that logs a known failure phrase",
                      kind="install", run=heuristic_fail_step),
        PlannedAction(key="exc", label="A step that raises", kind="remove", run=exception_fail_step),
    ]

    host2.show_install_progress(actions)
    assert len(host2.card_widgets) == 3

    deadline = time.monotonic() + 5.0
    while not host2.exec_finished and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)

    assert host2.exec_finished, "plan runner did not finish within the timeout"
    assert host2.exec_done == 3
    assert host2.step_statuses[0] == "success", host2.step_statuses
    assert host2.step_statuses[1] == "failed", host2.step_statuses
    assert host2.step_statuses[2] == "failed", host2.step_statuses
    assert any("doing the thing" in line for line in host2.step_logs[0])
    assert any("Package manager install failed" in line for line in host2.step_logs[1])
    assert any("ERROR during" in line and "boom" in line for line in host2.step_logs[2])

    # Selecting each finished step should show that step's own buffered log.
    host2._select_step(0)
    assert host2.exec_log_text.toPlainText().strip() == "\n".join(host2.step_logs[0]).strip()
    host2._select_step(2)
    assert host2.exec_log_text.toPlainText().strip() == "\n".join(host2.step_logs[2]).strip()

    # Finished screen shows a "Done" button wired to show_landing.
    done_buttons = [b for b in host2.root.findChildren(RoundedButton) if b.text == "Done"]
    assert len(done_buttons) == 1, "expected exactly one Done button after the run finished"
    done_buttons[0].click()
    assert host2.landing_calls == 1

    # Timers should have been stopped once the run finished.
    assert not host2._spinner_timer.isActive()
    assert not host2._log_timer.isActive()

    print("PASS 2 OK — end-to-end show_install_progress() run (success + heuristic-failed + "
          "exception-failed steps, card selection, Done button) completed without error.")

    # ---- Pass 3: a fresh, never-finished run shows a Stop button ----
    host3 = FakeHostApp()

    def slow_step(job):
        time.sleep(0.3)
        job.log("finished slow step")

    host3.show_install_progress([
        PlannedAction(key="slow", label="A step still running", kind="install", run=slow_step),
    ])
    app.processEvents()
    stop_buttons = [b for b in host3.root.findChildren(RoundedButton) if b.text == "Stop"]
    assert len(stop_buttons) == 1, "expected a Stop button while the plan is still running"

    # Let it finish so the background thread doesn't outlive the test process.
    deadline = time.monotonic() + 3.0
    while not host3.exec_finished and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert host3.exec_finished

    print("PASS 3 OK — Stop button shown while a plan is running.")

    print("SMOKE TEST OK — InstallProgressPage exercised end-to-end without error.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
