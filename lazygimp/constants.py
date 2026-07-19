from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Where things live on disk. The backend directory is shared with any prior
# GIMPSAM/LazyGimp shell install (same path both used), so upgrading to this
# file never orphans an already-downloaded multi-GB model.
# ---------------------------------------------------------------------------

HOME = os.path.expanduser("~")
XDG_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
XDG_DATA_HOME = os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")
XDG_STATE_HOME = os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state")
XDG_CACHE_HOME = os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache")

STATE_DIR = os.path.join(XDG_STATE_HOME, "lazygimp")
BACKEND_DIR = os.path.join(XDG_DATA_HOME, "lazygimp", "segany")
VENV_DIR = os.path.join(BACKEND_DIR, "venv")
MODELS_DIR = os.path.join(BACKEND_DIR, "models")
VENV_PYTHON = os.path.join(VENV_DIR, "bin", "python3")
VENV_PIP = os.path.join(VENV_DIR, "bin", "pip")

PHOTOGIMP_MANIFEST = ".lazygimp-photogimp.manifest"
PHOTOGIMP_EXCLUDE = {"pluginrc"}  # GIMP's own per-machine plug-in cache — never ship it
DESKTOP_FILES_MANIFEST = os.path.join(STATE_DIR, "desktop-files.manifest")
APPIMAGE_DIR = os.environ.get("LAZYGIMP_APPIMAGE_DIR") or os.path.join(HOME, "Applications")

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isdir(HERE):
        HERE = None
except NameError:
    HERE = None

# --- upstream locations (renovate-friendly pins, all in one place) ---------

PHOTOGIMP_REPO = "Diolinux/PhotoGIMP"
PHOTOGIMP_RELEASE_TAG = "3.1"

BATCHER_REPO = "kamilburda/batcher"
BATCHER_RELEASE_TAG = "1.2.9"

# Everything SAM (model registry, torch indexes, venv backend, plug-in
# files) lives in the gimpsam package — pierspad/GIMPSAM. LazyGimp takes
# it from that repo's LATEST official (non-prerelease) GitHub release,
# whose gimpsam-src.zip asset is built specifically to be consumed here:
# the package plus the plug-in files, resolvable fully offline once
# extracted. See lazygimp/gimpsam_dep.py for the full resolution order.
# GIMPSAM_FALLBACK_REF only matters before GIMPSAM's first new-style
# release exists (no asset to download yet) — then the source zipball of
# this ref is used instead.
GIMPSAM_REPO = "pierspad/GIMPSAM"
GIMPSAM_SRC_ASSET = "gimpsam-src.zip"
GIMPSAM_FALLBACK_REF = "main"

GIMP_VERSIONS_JSON_URL = "https://www.gimp.org/gimp_versions.json"
GIMP_DOWNLOAD_MIRROR = "https://download.gimp.org/gimp"
GMIC_DOWNLOAD_PAGE = "https://gmic.eu/download.html"


def ensure_state_dir() -> str:
    os.makedirs(STATE_DIR, exist_ok=True)
    return STATE_DIR
