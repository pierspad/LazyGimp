from __future__ import annotations

from .constants import FLATPAK_GIMP_ID, FLATPAK_GMIC_ID, GMIC_DOWNLOAD_PAGE
from .distro import DISTROS, detect_distro
from .gimp_detect import gimp_warm_up
from .job import Job
from .util import clean_subprocess_env
import shutil

# ---------------------------------------------------------------------------
# GIMP itself — package manager or Flatpak.
# ---------------------------------------------------------------------------

def gimp_native_installed() -> bool:
    distro = detect_distro()
    if not distro:
        return False
    return DISTROS[distro].is_pkg_installed(DISTROS[distro].gimp_pkgs[0])


def gmic_installed(target: str = "pm") -> bool:
    if target == "flatpak":
        if not shutil.which("flatpak"):
            return False
        import subprocess
        res = subprocess.run(["flatpak", "info", FLATPAK_GMIC_ID], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              env=clean_subprocess_env())
        return res.returncode == 0
    distro = detect_distro()
    if not distro:
        return False
    fam = DISTROS[distro]
    pkgs = fam.gmic_pkgs()
    return bool(pkgs) and all(fam.is_pkg_installed(p) for p in pkgs)


def gmic_available_on_this_release(target: str = "pm") -> bool:
    if target == "flatpak":
        return True
    distro = detect_distro()
    if not distro:
        return False
    return bool(DISTROS[distro].gmic_pkgs())


def flatpak_present() -> bool:
    if not shutil.which("flatpak"):
        return False
    import subprocess
    res = subprocess.run(["flatpak", "info", FLATPAK_GIMP_ID], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          env=clean_subprocess_env())
    return res.returncode == 0


appimage_present = flatpak_present


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


def install_gmic_only(job: Job, target: str = "pm") -> bool:
    if target == "flatpak":
        if not shutil.which("flatpak"):
            job.log("ERROR: Flatpak is not installed on this system.")
            return False
        job.log(f"Installing G'MIC Flatpak extension ({FLATPAK_GMIC_ID})...")
        rc = job.run_cmd(["flatpak", "install", "-y", "flathub", f"{FLATPAK_GMIC_ID}//3"])
        if rc != 0:
            rc = job.run_cmd(["flatpak", "install", "-y", "flathub", FLATPAK_GMIC_ID])
        if rc != 0:
            job.log(f"Flatpak install failed for {FLATPAK_GMIC_ID} (exit {rc}).")
            return False
        job.log("G'MIC Flatpak extension installed.")
        return True
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


def remove_gmic_only(job: Job, target: str = "pm") -> bool:
    if target == "flatpak":
        if not shutil.which("flatpak"):
            return True
        job.log(f"Removing G'MIC Flatpak extension ({FLATPAK_GMIC_ID})...")
        rc = job.run_cmd(["flatpak", "uninstall", "-y", FLATPAK_GMIC_ID])
        return rc == 0
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


def install_gimp_flatpak(job: Job, include_gmic: bool = True) -> bool:
    if not shutil.which("flatpak"):
        job.log("Flatpak is not installed on this system. Attempting to install flatpak...")
        distro = detect_distro()
        if distro:
            fam = DISTROS[distro]
            job.run_root(fam.install_cmd(["flatpak"]))
        if not shutil.which("flatpak"):
            job.log("ERROR: 'flatpak' binary could not be found or installed.")
            return False

    job.log("Adding Flathub repository (if not already present)...")
    job.run_cmd(["flatpak", "remote-add", "--if-not-exists", "flathub", "https://dl.flathub.org/repo/flathub.flatpakrepo"])

    job.log(f"Installing GIMP Flatpak ({FLATPAK_GIMP_ID})...")
    rc = job.run_cmd(["flatpak", "install", "-y", "flathub", FLATPAK_GIMP_ID])
    if rc != 0:
        job.log(f"Flatpak install failed for {FLATPAK_GIMP_ID} (exit {rc}).")
        return False

    if include_gmic:
        job.log(f"Installing G'MIC Flatpak extension ({FLATPAK_GMIC_ID})...")
        rc_gmic = job.run_cmd(["flatpak", "install", "-y", "flathub", f"{FLATPAK_GMIC_ID}//3"])
        if rc_gmic != 0:
            job.run_cmd(["flatpak", "install", "-y", "flathub", FLATPAK_GMIC_ID])

    job.log("GIMP Flatpak installed successfully.")
    gimp_warm_up(job)
    return True


def remove_gimp_flatpak(job: Job) -> bool:
    if not shutil.which("flatpak"):
        job.log("Flatpak is not installed on this system.")
        return True
    job.log(f"Removing GIMP Flatpak ({FLATPAK_GIMP_ID}) and G'MIC extension...")
    rc = job.run_cmd(["flatpak", "uninstall", "-y", FLATPAK_GIMP_ID, FLATPAK_GMIC_ID])
    return rc == 0


install_gimp_appimage = install_gimp_flatpak
remove_gimp_appimage = remove_gimp_flatpak
