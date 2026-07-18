from __future__ import annotations

from .constants import BATCHER_RELEASE_TAG, BATCHER_REPO, HERE, SEGANY_PLUGIN_FILES, SEGANY_SOURCES, VENV_PYTHON
from .gimp_detect import gimp_plugins_dir, invalidate_gimp_plugin_cache
from .job import Job
from .models import ModelSpec, model_path
from .util import fetch_latest_github_release_assets
from typing import Optional
import glob
import json
import os
import shutil
import tempfile
import urllib.request
import zipfile

# ---------------------------------------------------------------------------
# Plug-in folders (Batcher, SAM's seganyplugin) — download-or-local-checkout,
# copy into GIMP's plug-ins dir, record nothing but the folder's own
# existence (its name IS the record: only LazyGimp ever creates a
# "batcher"/"seganyplugin" folder there).
# ---------------------------------------------------------------------------

def batcher_installed() -> bool:
    d = gimp_plugins_dir()
    return bool(d) and os.path.isdir(os.path.join(d, "batcher"))


def segany_plugin_installed() -> bool:
    d = gimp_plugins_dir()
    return bool(d) and os.path.isfile(os.path.join(d, "seganyplugin", "seganyplugin.py"))


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


def install_batcher(job: Job) -> bool:
    dest_dir = gimp_plugins_dir()
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


def remove_batcher(job: Job) -> bool:
    d = gimp_plugins_dir()
    dest = os.path.join(d, "batcher") if d else None
    if dest and os.path.isdir(dest):
        shutil.rmtree(dest)
        invalidate_gimp_plugin_cache(job)
        job.log(f"Removed {dest}")
    else:
        job.log("Batcher was not installed.")
    return True


def resolve_segany_plugin_sources(job: Job) -> dict[str, str]:
    """Local-checkout-first (for active development next to this file: a
    sibling GIMPSAM/ or gimpsegany/ directory), else download from GitHub."""
    override = os.environ.get("LAZYGIMP_SEGANY_SRC_DIR")
    if override and all(os.path.isfile(os.path.join(override, f)) for f in SEGANY_PLUGIN_FILES):
        return {f: os.path.join(override, f) for f in SEGANY_PLUGIN_FILES}
    if HERE:
        for name, _repo, _branch in SEGANY_SOURCES:
            sibling = os.path.join(HERE, "..", name)
            if all(os.path.isfile(os.path.join(sibling, f)) for f in SEGANY_PLUGIN_FILES):
                return {f: os.path.join(sibling, f) for f in SEGANY_PLUGIN_FILES}
    tmp = tempfile.mkdtemp(prefix="lazygimp-segany-src-")
    last_err = None
    for name, repo, branch in SEGANY_SOURCES:
        try:
            result = {}
            for fname in SEGANY_PLUGIN_FILES:
                dest = os.path.join(tmp, fname)
                job.log(f"Fetching {fname} from {repo}@{branch}")
                urllib.request.urlretrieve(f"https://raw.githubusercontent.com/{repo}/{branch}/{fname}", dest)
                result[fname] = dest
            return result
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"could not obtain the SAM plug-in source files: {last_err}")


def install_segany_plugin(job: Job) -> bool:
    dest_dir = gimp_plugins_dir()
    if not dest_dir:
        job.log("ERROR: no GIMP plug-ins directory found — install GIMP first.")
        return False
    try:
        sources = resolve_segany_plugin_sources(job)
    except Exception as e:
        job.log(f"ERROR: {e}")
        return False
    dest = os.path.join(dest_dir, "seganyplugin")
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    for fname, path in sources.items():
        shutil.copy2(path, dest)
        os.chmod(os.path.join(dest, fname), 0o755)
    invalidate_gimp_plugin_cache(job)
    job.log(f"SAM plug-in installed into {dest} — find it under "
            "Image → Segment Anything Layers after a GIMP restart")
    return True


def remove_segany_plugin(job: Job) -> bool:
    d = gimp_plugins_dir()
    dest = os.path.join(d, "seganyplugin") if d else None
    if dest and os.path.isdir(dest):
        shutil.rmtree(dest)
        invalidate_gimp_plugin_cache(job)
        job.log(f"Removed {dest}")
    else:
        job.log("SAM plug-in was not installed.")
    return True


def write_segany_plugin_settings(primary: ModelSpec) -> None:
    d = gimp_plugins_dir()
    if not d:
        return
    plugin_dir = os.path.join(d, "seganyplugin")
    if not os.path.isdir(plugin_dir):
        return
    settings = {
        "pythonPath": VENV_PYTHON,
        "checkPtPath": model_path(primary),
        "modelType": "Auto",
    }
    with open(os.path.join(plugin_dir, "segany_settings.json"), "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
