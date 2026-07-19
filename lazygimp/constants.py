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
# files) lives in the gimpsam package — pierspad/GIMPSAM — pinned here to
# an exact ref so a LazyGimp release always ships/downloads a known
# GIMPSAM state, never "whatever main is today". Bump deliberately:
# after each GIMPSAM release, point this at its tag (e.g. "v2.0.0").
# See lazygimp/gimpsam_dep.py for the full resolution order.
GIMPSAM_REPO = "pierspad/GIMPSAM"
GIMPSAM_REF = "261719725bf10398df59e5ed861f4ac63cf3500c"

GIMP_VERSIONS_JSON_URL = "https://www.gimp.org/gimp_versions.json"
GIMP_DOWNLOAD_MIRROR = "https://download.gimp.org/gimp"
GMIC_DOWNLOAD_PAGE = "https://gmic.eu/download.html"


def ensure_state_dir() -> str:
    os.makedirs(STATE_DIR, exist_ok=True)
    return STATE_DIR
