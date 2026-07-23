from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Where things live on disk. The backend directory is shared with any prior
# GIMPSAM/LazyGimp shell install (same path both used), so upgrading to this
# file never orphans an already-downloaded multi-GB model.
# ---------------------------------------------------------------------------

import sys

HOME = os.path.expanduser("~")
IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    APPDATA = os.environ.get("APPDATA") or os.path.join(HOME, "AppData", "Roaming")
    LOCALAPPDATA = os.environ.get("LOCALAPPDATA") or os.path.join(HOME, "AppData", "Local")
    XDG_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or APPDATA
    XDG_DATA_HOME = os.environ.get("XDG_DATA_HOME") or LOCALAPPDATA
    XDG_STATE_HOME = os.environ.get("XDG_STATE_HOME") or os.path.join(LOCALAPPDATA, "lazygimp", "state")
    XDG_CACHE_HOME = os.environ.get("XDG_CACHE_HOME") or os.path.join(LOCALAPPDATA, "lazygimp", "cache")
else:
    XDG_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
    XDG_DATA_HOME = os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")
    XDG_STATE_HOME = os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state")
    XDG_CACHE_HOME = os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache")

STATE_DIR = os.path.join(XDG_STATE_HOME, "lazygimp")
BACKEND_DIR = os.path.join(XDG_DATA_HOME, "lazygimp", "segany")
VENV_DIR = os.path.join(BACKEND_DIR, "venv")
MODELS_DIR = os.path.join(BACKEND_DIR, "models")

if IS_WINDOWS:
    VENV_PYTHON = os.path.join(VENV_DIR, "Scripts", "python.exe")
    VENV_PIP = os.path.join(VENV_DIR, "Scripts", "pip.exe")
else:
    VENV_PYTHON = os.path.join(VENV_DIR, "bin", "python3")
    VENV_PIP = os.path.join(VENV_DIR, "bin", "pip")

PHOTOGIMP_MANIFEST = ".lazygimp-photogimp.manifest"
PHOTOGIMP_EXCLUDE = {"pluginrc"}  # GIMP's own per-machine plug-in cache — never ship it
DESKTOP_FILES_MANIFEST = os.path.join(STATE_DIR, "desktop-files.manifest")
FLATPAK_GIMP_ID = "org.gimp.GIMP"
FLATPAK_GMIC_ID = "org.gimp.GIMP.Plugin.GMic"
FLATPAK_CONFIG_DIR = os.path.join(HOME, ".var", "app", FLATPAK_GIMP_ID, "config", "GIMP")
APPIMAGE_DIR = os.path.join(XDG_DATA_HOME, "lazygimp", "appimages")

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isdir(HERE):
        HERE = None
except NameError:
    HERE = None

# --- upstream locations (renovate-friendly pins, all in one place) ---------

PHOTOGIMP_REPO = "Diolinux/PhotoGIMP"
PHOTOGIMP_RELEASE_TAG = "3.1"
# Fallback only, used if the GitHub API call to resolve the *actual* default
# branch fails. PhotoGIMP ships tool-layout fixes as plain commits well
# before cutting a release (confirmed: master was a commit ahead of "3.1",
# with real toolrc differences — an extra tool group tagged releases didn't
# have yet) — see PHOTOGIMP_REPO fetch order in photogimp.py.
PHOTOGIMP_BRANCH = "master"

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
