"""Optional-dependency guards (PySide6 for the GUI)."""
from __future__ import annotations

try:
    import PySide6
    _PYSIDE_OK = True
except ImportError:  # pragma: no cover - CLI works without PySide6
    PySide6 = None  # type: ignore[assignment]
    _PYSIDE_OK = False
