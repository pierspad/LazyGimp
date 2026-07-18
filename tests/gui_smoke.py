"""GUI smoke test — needs a real display (CI runs it under Xvfb).

Opens the actual app and walks EVERY screen: landing, all wizard pages
(via _wizard_jump_to_step, which renders each page's full widget tree),
the uninstall screen, back to landing — then quits. Any exception raised
in a Tk callback fails the run.

Not named test_* on purpose: `unittest discover` must keep passing on
headless boxes; this file is invoked explicitly as
    xvfb-run -a python tests/gui_smoke.py
"""
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lazygimp.compat import _TK_OK, tk  # noqa: E402

if not _TK_OK:
    print("tkinter is not available — this smoke test needs python3-tk", file=sys.stderr)
    sys.exit(2)

from lazygimp.gui.app import LazyGimpApp  # noqa: E402

failures: list[str] = []
root = tk.Tk()


def fail(kind, exc, tb):
    failures.append("".join(traceback.format_exception(kind, exc, tb)))
    root.after(0, root.destroy)


root.report_callback_exception = fail
app = LazyGimpApp(root)

STEPS = [
    lambda: app.show_wizard(),
    lambda: app._wizard_jump_to_step("photogimp"),
    lambda: app._wizard_jump_to_step("gmic"),
    lambda: app._wizard_jump_to_step("sam"),
    lambda: app._wizard_jump_to_step("batcher"),
    lambda: app._wizard_jump_to_step("review"),
    lambda: app.show_uninstall_confirm(),
    lambda: app.show_landing(),
    lambda: root.destroy(),
]


def run_step(i=0):
    if i >= len(STEPS) or not root.winfo_exists():
        return
    name = getattr(STEPS[i], "__name__", f"step {i}")
    try:
        STEPS[i]()
    except Exception:
        failures.append(f"--- {name} ---\n" + traceback.format_exc())
        root.destroy()
        return
    root.after(250, lambda: run_step(i + 1))


root.after(300, run_step)
root.mainloop()

if failures:
    print("GUI smoke test FAILED:\n" + "\n".join(failures), file=sys.stderr)
    sys.exit(1)
print("GUI smoke test OK — every screen rendered without callback errors.")
