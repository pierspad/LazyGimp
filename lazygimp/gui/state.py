"""What's on this system, in the uninstall screen's vocabulary."""

from __future__ import annotations

from ..constants import APPIMAGE_DIR, BACKEND_DIR
from ..distro import detect_distro
from ..gimp_install import appimage_present, gimp_native_installed
from ..photogimp import photogimp_installed
from ..plugins import batcher_installed, segany_plugin_installed
import os


def detect_targets() -> list[tuple[str, str, str]]:
    targets = []
    distro = detect_distro()
    if gimp_native_installed():
        targets.append(("package-manager", "Native GIMP (+ G'MIC) packages", f"installed via {distro}"))
    if appimage_present():
        targets.append(("appimage", "GIMP AppImage", APPIMAGE_DIR))
    if photogimp_installed():
        targets.append(("photogimp", "PhotoGIMP configuration layer",
                         "icons, desktop entry, shortcuts, splash screen, UI layout"))
    if batcher_installed():
        targets.append(("batcher", "Batcher plug-in", "plug-ins/batcher — only this folder"))
    if segany_plugin_installed() or os.path.isdir(BACKEND_DIR):
        targets.append(("sam", "SAM plug-in + Python backend + models",
                         f"plug-ins/seganyplugin and {BACKEND_DIR} — only these"))
    return targets

def anything_installed() -> bool:
    return bool(detect_targets())
