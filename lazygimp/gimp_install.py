from __future__ import annotations

from .constants import APPIMAGE_DIR, GIMP_DOWNLOAD_MIRROR, GIMP_VERSIONS_JSON_URL, GMIC_DOWNLOAD_PAGE
from .distro import DISTROS, detect_distro
from .gimp_detect import gimp_warm_up
from .job import Job
from typing import Optional
import glob
import json
import os
import platform
import urllib.request

# ---------------------------------------------------------------------------
# GIMP itself — package manager or official AppImage.
# ---------------------------------------------------------------------------

def gimp_native_installed() -> bool:
    distro = detect_distro()
    if not distro:
        return False
    return DISTROS[distro].is_pkg_installed(DISTROS[distro].gimp_pkgs[0])


def gmic_installed() -> bool:
    distro = detect_distro()
    if not distro:
        return False
    fam = DISTROS[distro]
    pkgs = fam.gmic_pkgs()
    return bool(pkgs) and all(fam.is_pkg_installed(p) for p in pkgs)


def gmic_available_on_this_release() -> bool:
    distro = detect_distro()
    if not distro:
        return False
    return bool(DISTROS[distro].gmic_pkgs())


def appimage_present() -> bool:
    return bool(glob.glob(os.path.join(APPIMAGE_DIR, "GIMP-*.AppImage")))


def install_gimp_package_manager(job: Job, include_gmic: bool = True) -> bool:
    distro = detect_distro()
    if not distro:
        job.log("ERROR: no supported distribution detected (arch, debian, ubuntu, fedora, opensuse).")
        return False
    fam = DISTROS[distro]
    job.log(f"Detected distribution family: {distro}")
    if fam.refresh_cmd:
        job.run_root(fam.refresh_cmd)
    pkgs = list(fam.gimp_pkgs)
    if include_gmic:
        gmic_pkgs = fam.gmic_pkgs()
        if gmic_pkgs:
            pkgs += gmic_pkgs
        else:
            job.log("G'MIC package is not available on this release — skipping (see --skip-gmic behaviour).")
    rc = job.run_root(fam.install_cmd(pkgs))
    for note in fam.notes():
        job.log(f"NOTE: {note}")
    if rc != 0:
        job.log(f"Package manager install failed (exit {rc}).")
        if distro == "arch":
            job.log("DIAGNOSTIC TIP: If pacman failed with 'unable to lock database', check if pamac/discover/terminal is using pacman. If stale, run: sudo rm /var/lib/pacman/db.lck")
        return False
    gimp_warm_up(job)
    return True


def install_gmic_only(job: Job) -> bool:
    distro = detect_distro()
    if not distro:
        job.log("ERROR: G'MIC is installed through the system package manager — no supported distribution detected.")
        return False
    fam = DISTROS[distro]
    pkgs = fam.gmic_pkgs()
    if not pkgs:
        job.log("G'MIC has no package on this distribution release. "
                f"See {GMIC_DOWNLOAD_PAGE} for a manual build, or upgrade your distro release.")
        return False
    if fam.refresh_cmd:
        job.run_root(fam.refresh_cmd)
    rc = job.run_root(fam.install_cmd(pkgs))
    if rc != 0:
        job.log(f"G'MIC install failed (exit {rc}).")
        if distro == "arch":
            job.log("DIAGNOSTIC TIP: If pacman failed with 'unable to lock database', check if pamac/discover/terminal is using pacman. If stale, run: sudo rm /var/lib/pacman/db.lck")
        return False
    job.log("G'MIC installed.")
    return True


def remove_gmic_only(job: Job) -> bool:
    distro = detect_distro()
    if not distro:
        job.log("Cannot remove G'MIC automatically — no supported distribution detected.")
        return False
    fam = DISTROS[distro]
    pkgs = [p for p in fam.gmic_pkgs() if fam.is_pkg_installed(p)]
    if not pkgs:
        job.log("G'MIC package was not installed via the package manager.")
        return True
    rc = job.run_root(fam.remove_cmd(pkgs))
    return rc == 0


def remove_gimp_package_manager(job: Job) -> bool:
    distro = detect_distro()
    if not distro:
        job.log("Cannot remove native GIMP packages automatically — no supported distribution detected.")
        return False
    fam = DISTROS[distro]
    all_pkgs = fam.gimp_pkgs + fam.gmic_pkgs()
    pkgs = [p for p in all_pkgs if fam.is_pkg_installed(p)]
    if not pkgs:
        job.log("No LazyGimp-installed packages found via the package manager.")
        return True
    return job.run_root(fam.remove_cmd(pkgs)) == 0


def _latest_appimage_info() -> Optional[tuple[str, str, str]]:
    arch = platform.machine()
    with urllib.request.urlopen(GIMP_VERSIONS_JSON_URL, timeout=20) as resp:
        data = json.load(resp)
    for release in data.get("STABLE", []):
        for image in release.get("appimage", []):
            if arch in image.get("filename", ""):
                return release["version"], image["filename"], image["sha256"]
    return None


def install_gimp_appimage(job: Job) -> Optional[tuple[str, str]]:
    """Returns (appimage_path, version) on success, so callers (PhotoGIMP)
    can hint the exact profile GIMP will use and retarget the desktop
    launcher at this exact file (it is never on PATH)."""
    info = _latest_appimage_info()
    if not info:
        job.log(f"No official GIMP AppImage published for architecture {platform.machine()}.")
        return None
    version, filename, sha256 = info
    series = version.rsplit(".", 1)[0]
    url = f"{GIMP_DOWNLOAD_MIRROR}/v{series}/linux/{filename}"
    os.makedirs(APPIMAGE_DIR, exist_ok=True)
    dest = os.path.join(APPIMAGE_DIR, filename)

    if os.path.isfile(dest) and _sha256_of(dest) == sha256:
        job.log(f"GIMP {version} AppImage already present and verified — skipping download")
    else:
        if not job.download(url, dest):
            return None
        actual = _sha256_of(dest)
        if actual != sha256:
            job.log(f"ERROR: checksum mismatch for {dest} (expected {sha256}, got {actual})")
            os.remove(dest)
            return None
        job.log(f"Checksum verified for {os.path.basename(dest)}")
    os.chmod(dest, 0o755)
    symlink = os.path.join(APPIMAGE_DIR, "GIMP.AppImage")
    try:
        if os.path.islink(symlink) or os.path.exists(symlink):
            os.remove(symlink)
        os.symlink(filename, symlink)
    except OSError as e:
        job.log(f"Could not create GIMP.AppImage symlink: {e} (not fatal)")
    job.log(f"GIMP {version} AppImage installed at {dest} (symlink: GIMP.AppImage)")
    gimp_warm_up(job, dest)
    return dest, version


def remove_gimp_appimage(job: Job) -> bool:
    removed = False
    for pattern in ("GIMP-*.AppImage", "GIMP.AppImage"):
        for f in glob.glob(os.path.join(APPIMAGE_DIR, pattern)):
            try:
                os.remove(f)
                job.log(f"Removed {f}")
                removed = True
            except OSError as e:
                job.log(f"Could not remove {f}: {e}")
    if not removed:
        job.log("No GIMP AppImage found.")
    return True


def _sha256_of(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
