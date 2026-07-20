from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional
import subprocess

# ---------------------------------------------------------------------------
# Distro / package-manager abstraction (replaces shell_scripts/<distro>.sh).
# Each entry only ever needs to answer four questions: which packages, how
# to install them, how to remove them, and whether one is already installed.
# ---------------------------------------------------------------------------

@dataclass
class DistroFamily:
    key: str
    gimp_pkgs: list[str]
    gmic_pkgs: Callable[[], list[str]]  # may be empty if unavailable on this release
    install_cmd: Callable[[list[str]], list[str]]
    remove_cmd: Callable[[list[str]], list[str]]
    is_pkg_installed: Callable[[str], bool]
    refresh_cmd: Optional[list[str]] = None
    notes: Callable[[], list[str]] = field(default=lambda: [])


def _dpkg_installed(pkg: str) -> bool:
    return subprocess.run(["dpkg", "-s", pkg], capture_output=True).returncode == 0


def _rpm_installed(pkg: str) -> bool:
    return subprocess.run(["rpm", "-q", pkg], capture_output=True).returncode == 0


def _pacman_installed(pkg: str) -> bool:
    return subprocess.run(["pacman", "-Qi", pkg], capture_output=True).returncode == 0


def _apt_cache_has(pkg: str) -> bool:
    return subprocess.run(["apt-cache", "show", pkg], capture_output=True).returncode == 0


def _apt_candidate_is_gimp2() -> bool:
    out = subprocess.run(["apt-cache", "policy", "gimp"], capture_output=True, text=True)
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.startswith("Candidate:"):
            return line.split(":", 1)[1].strip().startswith("2.")
    return False


def _debian_ubuntu_notes() -> list[str]:
    if _apt_candidate_is_gimp2():
        return ["This release ships GIMP 2.x — PhotoGIMP needs GIMP 3+. "
                "Use the AppImage method instead for the latest GIMP."]
    return []


DISTROS: dict[str, DistroFamily] = {
    "arch": DistroFamily(
        key="arch",
        gimp_pkgs=["gimp"],
        gmic_pkgs=lambda: ["gimp-plugin-gmic"],
        install_cmd=lambda pkgs: ["pacman", "-Syu", "--needed", "--noconfirm", *pkgs],
        remove_cmd=lambda pkgs: ["pacman", "-Rns", "--noconfirm", *pkgs],
        is_pkg_installed=_pacman_installed,
    ),
    "debian": DistroFamily(
        key="debian",
        gimp_pkgs=["gimp"],
        gmic_pkgs=lambda: ["gimp-gmic"] if _apt_cache_has("gimp-gmic") else [],
        install_cmd=lambda pkgs: ["apt-get", "install", "-y", *pkgs],
        remove_cmd=lambda pkgs: ["apt-get", "remove", "-y", *pkgs],
        is_pkg_installed=_dpkg_installed,
        refresh_cmd=["apt-get", "update"],
        notes=_debian_ubuntu_notes,
    ),
    "ubuntu": DistroFamily(
        key="ubuntu",
        gimp_pkgs=["gimp"],
        gmic_pkgs=lambda: ["gimp-gmic"] if _apt_cache_has("gimp-gmic") else [],
        install_cmd=lambda pkgs: ["apt-get", "install", "-y", *pkgs],
        remove_cmd=lambda pkgs: ["apt-get", "remove", "-y", *pkgs],
        is_pkg_installed=_dpkg_installed,
        refresh_cmd=["apt-get", "update"],
        notes=_debian_ubuntu_notes,
    ),
    "fedora": DistroFamily(
        key="fedora",
        gimp_pkgs=["gimp"],
        gmic_pkgs=lambda: ["gmic-gimp"],
        install_cmd=lambda pkgs: ["dnf", "install", "-y", *pkgs],
        remove_cmd=lambda pkgs: ["dnf", "remove", "-y", *pkgs],
        is_pkg_installed=_rpm_installed,
    ),
    "opensuse": DistroFamily(
        key="opensuse",
        gimp_pkgs=["gimp"],
        gmic_pkgs=lambda: ["gmic-gimp"],
        install_cmd=lambda pkgs: ["zypper", "--non-interactive", "install", *pkgs],
        remove_cmd=lambda pkgs: ["zypper", "--non-interactive", "remove", *pkgs],
        is_pkg_installed=_rpm_installed,
        refresh_cmd=["zypper", "--non-interactive", "refresh"],
        notes=lambda: ["On Leap, GIMP 3.x may need the graphics repository enabled; "
                        "Tumbleweed always ships the latest stable."],
    ),
}


def detect_distro() -> Optional[str]:
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            data = {}
            for line in fh:
                if "=" in line:
                    k, _, v = line.strip().partition("=")
                    data[k] = v.strip().strip('"')
    except OSError:
        return None
    candidates = [data.get("ID", "")] + data.get("ID_LIKE", "").split()
    for candidate in candidates:
        if candidate in DISTROS:
            return candidate
    return None
