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

# Prefer pierspad/GIMPSAM's plug-in (lazy per-family imports, SAM2 + SAM3.1
# support) over the older pierspad/gimpsegany fork; both are tried as a
# local-checkout sibling first (for active development next to this file),
# then as a GitHub raw fallback.
SEGANY_SOURCES = [
    ("GIMPSAM", "pierspad/GIMPSAM", "main"),
    ("gimpsegany", "pierspad/gimpsegany", "main"),
]
SEGANY_PLUGIN_FILES = ["seganyplugin.py", "seganybridge.py"]
SEGANY_README = "https://github.com/pierspad/GIMPSAM#readme"

GIMP_VERSIONS_JSON_URL = "https://www.gimp.org/gimp_versions.json"
GIMP_DOWNLOAD_MIRROR = "https://download.gimp.org/gimp"
GMIC_DOWNLOAD_PAGE = "https://gmic.eu/download.html"

SAM1_PIP_SPEC = "git+https://github.com/facebookresearch/segment-anything.git"
SAM2_PIP_SPEC = "git+https://github.com/facebookresearch/segment-anything-2.git"
SAM3_HF_REPO_ID = "facebook/sam3.1"
SAM3_HF_PAGE = f"https://huggingface.co/{SAM3_HF_REPO_ID}"

TORCH_INDEX_URLS = {
    "CPU (universal, smaller download)": "https://download.pytorch.org/whl/cpu",
    "NVIDIA CUDA 12.6": "https://download.pytorch.org/whl/cu126",
    "NVIDIA CUDA 12.8": "https://download.pytorch.org/whl/cu128",
    "AMD ROCm 6.2": "https://download.pytorch.org/whl/rocm6.2",
}


def ensure_state_dir() -> str:
    os.makedirs(STATE_DIR, exist_ok=True)
    return STATE_DIR
