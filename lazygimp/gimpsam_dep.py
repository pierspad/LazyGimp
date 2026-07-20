from __future__ import annotations

from .constants import GIMPSAM_FALLBACK_REF, GIMPSAM_REPO, GIMPSAM_SRC_ASSET, HERE, XDG_CACHE_HOME
from .util import fetch_latest_github_release_assets
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
#   4. GIMPSAM's LATEST official GitHub release: its gimpsam-src.zip
#      asset (built specifically for this), cached per release tag —
#      an already-cached tag never re-downloads
#   5. the newest cached copy, when GitHub is unreachable
#   6. the source zipball of GIMPSAM_FALLBACK_REF — only relevant before
#      the first new-style GIMPSAM release exists
#
# 1-3 never touch the network; a release bundle therefore works fully
# offline. 4-6 only happen when running from a bare git checkout without
# a sibling — a dev situation where network is a fair assumption
# (nothing this installer does works without it anyway).
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


def _cache_base() -> str:
    return os.path.join(XDG_CACHE_HOME, "lazygimp", "gimpsam")


def _find_package_root(root: str) -> Optional[str]:
    if os.path.isfile(os.path.join(root, "gimpsam", "__init__.py")):
        return root
    if not os.path.isdir(root):
        return None
    for entry in sorted(os.listdir(root)):
        sub = os.path.join(root, entry)
        if os.path.isfile(os.path.join(sub, "gimpsam", "__init__.py")):
            return sub
    return None


def _download_zip(url: str, dest_root: str) -> Optional[str]:
    """Fetch a zip into dest_root and return the dir containing gimpsam/."""
    os.makedirs(dest_root, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="lazygimp-gimpsam-") as tmp:
            zip_path = os.path.join(tmp, "gimpsam.zip")
            req = urllib.request.Request(url, headers={"User-Agent": "LazyGimp-Installer"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(zip_path, "wb") as out:
                out.write(resp.read())
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(dest_root)
    except Exception:
        return None
    return _find_package_root(dest_root)


def _resolve_latest_release() -> Optional[str]:
    """Cache-or-download the latest official release's src asset; return
    the importable package root, or None if there is no reachable/usable
    release."""
    release = fetch_latest_github_release_assets(GIMPSAM_REPO)
    if not release:
        return None
    tag = release.get("tag_name") or "latest"
    cache_dir = os.path.join(_cache_base(), tag)
    cached = _find_package_root(cache_dir)
    if cached:
        return cached
    url = next((a.get("browser_download_url") for a in release.get("assets", [])
                if a.get("name") == GIMPSAM_SRC_ASSET), None)
    if not url:
        return None  # a pre-restructure release without the src asset
    return _download_zip(url, cache_dir)


def _newest_cached() -> Optional[str]:
    base = _cache_base()
    if not os.path.isdir(base):
        return None
    tags = sorted(os.listdir(base), key=lambda t: os.path.getmtime(os.path.join(base, t)), reverse=True)
    for tag in tags:
        found = _find_package_root(os.path.join(base, tag))
        if found:
            return found
    return None


def load() -> ModuleType:
    """Import and return the gimpsam package (idempotent). Raises a
    RuntimeError naming every location tried when nothing resolves."""
    global _loaded
    if _loaded is not None:
        return _loaded

    for d in _local_candidate_dirs():
        root = _find_package_root(d)
        if root:
            if root not in sys.path:
                sys.path.insert(0, root)
            break
    _loaded = _try_import()

    if _loaded is None:
        root = (_resolve_latest_release()
                or _newest_cached()
                or _download_zip(f"https://github.com/{GIMPSAM_REPO}/archive/{GIMPSAM_FALLBACK_REF}.zip",
                                 os.path.join(_cache_base(), f"ref-{GIMPSAM_FALLBACK_REF}")))
        if root is None:
            raise RuntimeError(
                "could not resolve the gimpsam package: no $LAZYGIMP_GIMPSAM_SRC_DIR, no sibling "
                "GIMPSAM/ checkout, nothing vendored, and neither the latest GitHub release of "
                f"{GIMPSAM_REPO} (asset {GIMPSAM_SRC_ASSET}), a cached copy, nor the "
                f"{GIMPSAM_FALLBACK_REF} zipball could be fetched — check your connection.")
        if root not in sys.path:
            sys.path.insert(0, root)
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
