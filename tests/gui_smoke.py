"""GUI smoke test runner for PySide6 Qt interface."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lazygimp.gui._smoke_test import main as smoke_main  # noqa: E402
from lazygimp.gui.pages._smoke_test_landing_uninstall import main as smoke_landing  # noqa: E402
from lazygimp.gui.pages._smoke_test_progress import main as smoke_progress  # noqa: E402
from lazygimp.gui.pages._smoke_test_wizard import main as smoke_wizard  # noqa: E402

if __name__ == "__main__":
    smoke_main()
    smoke_landing()
    smoke_wizard()
    smoke_progress()
    print("GUI smoke test OK — every screen rendered without callback errors.")
