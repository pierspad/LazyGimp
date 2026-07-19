from __future__ import annotations

from .constants import GIMPSAM_REF, GIMPSAM_REPO, HERE, XDG_CACHE_HOME
from types import ModuleType
from typing import Optional
import importlib
import os
import sys
import tempfile
import urllib.request
import zipfile

# ---------------------------------------------------------------------------
# The gimpsam package (pierspad/GIMPSAM) is LazyGimp's single source of
# truth for everything SAM: model registry, venv/PyTorch backend, SAM 3.1
# gating, plug-in files. LazyGimp only aggregates it — nothing SAM is
# implemented here anymore. Resolution order:
#
#   1. $LAZYGIMP_GIMPSAM_SRC_DIR — explicit override
#   2. a sibling GIMPSAM/ checkout — active development next to this repo
#   3. plain `import gimpsam` — the copy vendored into release bundles by
#      scripts/build_release_assets.sh (pyz / src zip / binary all ship it)
#   4. a cached download of the source zipball at GIMPSAM_REF
#   5. download that zipball now, cache it, import it
#
# 1-3 never touch the network; 4-5 only happen when running from a bare
# git checkout without a sibling — a dev situation where network is a fair
# assumption (nothing this installer does works without it anyway).
# ---------------------------------------------------------------------------

_loaded: Optional[ModuleType] = None


def _local_candidate_dirs() -> list[str]:
    dirs = []
    override = os.environ.get("LAZYGIMP_GIMPSAM_SRC_DIR")
    if override:
        dirs.append(override)
    if HERE:
        dirs.append(os.path.abspath(os.path.join(HERE, "..", "..", "GIMPSAM")))
    return dirs


def _cache_root() -> str:
    return os.path.join(XDG_CACHE_HOME, "lazygimp", "gimpsam", GIMPSAM_REF)


def _download_pinned_source(dest_root: str) -> str:
    """Fetch the GIMPSAM source zipball at GIMPSAM_REF into dest_root and
    return the directory that contains the gimpsam/ package."""
    url = f"https://github.com/{GIMPSAM_REPO}/archive/{GIMPSAM_REF}.zip"
    os.makedirs(dest_root, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lazygimp-gimpsam-") as tmp:
        zip_path = os.path.join(tmp, "gimpsam.zip")
        req = urllib.request.Request(url, headers={"User-Agent": "LazyGimp-Installer"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(zip_path, "wb") as out:
            out.write(resp.read())
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest_root)
    found = _find_package_root(dest_root)
    if not found:
        raise RuntimeError(f"no gimpsam/ package inside {url}")
    return found


def _find_package_root(root: str) -> Optional[str]:
    if os.path.isfile(os.path.join(root, "gimpsam", "__init__.py")):
        return root
    for entry in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        sub = os.path.join(root, entry)
        if os.path.isfile(os.path.join(sub, "gimpsam", "__init__.py")):
            return sub
    return None


def load() -> ModuleType:
    """Import and return the gimpsam package (idempotent). Raises a
    RuntimeError naming every location tried when nothing resolves."""
    global _loaded
    if _loaded is not None:
        return _loaded

    tried: list[str] = []
    for d in _local_candidate_dirs():
        root = _find_package_root(d)
        if root:
            if root not in sys.path:
                sys.path.insert(0, root)
            break
        tried.append(d)
    _loaded = _try_import()
    if _loaded is None:
        cached = _find_package_root(_cache_root())
        if not cached:
            try:
                cached = _download_pinned_source(_cache_root())
            except Exception as e:
                tried.append(f"{GIMPSAM_REPO}@{GIMPSAM_REF} ({e})")
                raise RuntimeError(
                    "could not resolve the gimpsam package — tried: " + "; ".join(tried)
                ) from e
        if cached not in sys.path:
            sys.path.insert(0, cached)
        _loaded = _try_import()
    if _loaded is None:
        raise RuntimeError("gimpsam resolved on disk but failed to import — see traceback above")

    # Import the submodules the shims re-export, so `load().models` etc.
    # are always attribute-ready.
    for sub in ("constants", "models", "hardware", "backend", "sam3", "plugin"):
        importlib.import_module(f"gimpsam.{sub}")
    return _loaded


def _try_import() -> Optional[ModuleType]:
    try:
        return importlib.import_module("gimpsam")
    except ImportError:
        return None
