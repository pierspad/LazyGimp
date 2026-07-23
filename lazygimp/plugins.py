from __future__ import annotations

from .constants import BATCHER_RELEASE_TAG, BATCHER_REPO
from .gimp_detect import gimp_plugins_dir, gimp_version_dirs, invalidate_gimp_plugin_cache
from .job import Job
from .util import fetch_latest_github_release_assets
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # a plain import would force the gimpsam dependency
    from .models import ModelSpec
import glob
import os
import shutil
import tempfile
import zipfile

# ---------------------------------------------------------------------------
# Plug-in folders (Batcher, SAM's seganyplugin) — download-or-local-checkout,
# copy into GIMP's plug-ins dir, record nothing but the folder's own
# existence (its name IS the record: only LazyGimp ever creates a
# "batcher"/"seganyplugin" folder there).
#
# The SAM plug-in itself is owned by the gimpsam package (resolved from
# GIMPSAM's latest official release by gimpsam_dep): the functions below
# just forward to it, keeping their old names so the GUI/CLI call sites
# never changed. The plug-in files ship inside the resolved bundle, next
# to the package, so installation never separately hits the network.
# Only the installed-check stays local (a pure filesystem probe must not
# force the dependency).
# ---------------------------------------------------------------------------

def batcher_installed(target: Optional[str] = None) -> bool:
    if target is not None:
        d = gimp_plugins_dir(target=target)
        return bool(d) and os.path.isdir(os.path.join(d, "batcher"))
    for d in gimp_version_dirs(None):
        if os.path.isdir(os.path.join(d, "plug-ins", "batcher")):
            return True
    return False


def segany_plugin_installed(target: Optional[str] = None) -> bool:
    if target is not None:
        d = gimp_plugins_dir(target=target)
        return bool(d) and os.path.isfile(os.path.join(d, "seganyplugin", "seganyplugin.py"))
    for d in gimp_version_dirs(None):
        if os.path.isfile(os.path.join(d, "plug-ins", "seganyplugin", "seganyplugin.py")):
            return True
    return False


def _download_zip_and_find(job: Job, url: str, folder_name: str) -> Optional[str]:
    tmp = tempfile.mkdtemp(prefix="lazygimp-plugin-")
    zip_path = os.path.join(tmp, f"{folder_name}.zip")
    if not job.download(url, zip_path):
        return None
    extracted = os.path.join(tmp, "extracted")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extracted)
    for root, dirs, _files in os.walk(extracted):
        if os.path.basename(root) == folder_name:
            return root
    return None


def install_batcher(job: Job, target: Optional[str] = None) -> bool:
    dest_dir = gimp_plugins_dir(target=target)
    if not dest_dir:
        job.log("ERROR: no GIMP plug-ins directory found — install GIMP first.")
        return False
    
    release_info = fetch_latest_github_release_assets(BATCHER_REPO)
    download_url = None
    if release_info:
        assets = release_info.get("assets", [])
        for asset in assets:
            name = asset.get("name", "")
            if name.startswith("batcher-") and name.endswith(".zip"):
                download_url = asset.get("browser_download_url")
                break
        if download_url:
            job.log(f"Resolved latest Batcher download URL from GitHub: {download_url}")

    if not download_url:
        job.log(f"Falling back to pinned Batcher release tag: {BATCHER_RELEASE_TAG}")
        download_url = f"https://github.com/{BATCHER_REPO}/releases/download/{BATCHER_RELEASE_TAG}/batcher-{BATCHER_RELEASE_TAG}.zip"

    src = _download_zip_and_find(job, download_url, "batcher")
    if not src:
        job.log("ERROR: 'batcher' folder not found inside the downloaded archive.")
        return False
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "batcher")
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src, dest)
    for f in glob.glob(os.path.join(dest, "*.py")):
        os.chmod(f, 0o755)
    shutil.rmtree(os.path.dirname(os.path.dirname(src)), ignore_errors=True)
    invalidate_gimp_plugin_cache(job)
    job.log(f"Batcher installed into {dest} — restart GIMP, then look for "
            "'Export Layers…' and 'Batch Convert…' under File")
    return True


def remove_batcher(job: Job, target: Optional[str] = None) -> bool:
    found = False
    targets = [gimp_plugins_dir(target=target)] if target else [
        os.path.join(d, "plug-ins") for d in gimp_version_dirs(None)
    ]
    for d in targets:
        if not d:
            continue
        dest = os.path.join(d, "batcher")
        if os.path.isdir(dest):
            shutil.rmtree(dest)
            invalidate_gimp_plugin_cache(job)
            job.log(f"Removed {dest}")
            found = True
    if not found:
        job.log("Batcher was not installed.")
    return True


def install_segany_plugin(job: Job) -> bool:
    from .gimpsam_dep import load

    # Honour the historical override name alongside gimpsam's own.
    legacy = os.environ.get("LAZYGIMP_SEGANY_SRC_DIR")
    if legacy and not os.environ.get("GIMPSAM_SRC_DIR"):
        os.environ["GIMPSAM_SRC_DIR"] = legacy
    return load().plugin.install_plugin(job)


def remove_segany_plugin(job: Job, target: Optional[str] = None) -> bool:
    found = False
    targets = [gimp_plugins_dir(target=target)] if target else [
        os.path.join(d, "plug-ins") for d in gimp_version_dirs(None)
    ]
    for d in targets:
        if not d:
            continue
        dest = os.path.join(d, "seganyplugin")
        if os.path.isdir(dest):
            shutil.rmtree(dest)
            invalidate_gimp_plugin_cache(job)
            job.log(f"Removed {dest}")
            found = True
    try:
        from .gimpsam_dep import load
        load().plugin.remove_plugin(job)
    except Exception:
        pass
    if not found and not targets:
        job.log("SAM GIMP plug-in was not installed.")
    return True


def write_segany_plugin_settings(primary: ModelSpec) -> None:
    from .gimpsam_dep import load
    load().plugin.write_plugin_settings(primary)
