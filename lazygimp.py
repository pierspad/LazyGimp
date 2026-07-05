#!/usr/bin/env python3
"""
lazygimp.py — GIMP + PhotoGIMP + G'MIC + SAM (Segment Anything) + Batcher,
one standalone Python file, no other files required.

This intentionally replaces LazyGimp's old shell-script bundle
(install.sh, lib/*.sh, shell_scripts/<distro>.sh, package-manager-install.sh,
appimage-install.sh, plugins-install.sh, uninstall.sh, update-segany.sh) and
the separate GIMPSAM installer.py it used to import at runtime. Every piece
of that logic now lives here, in Python, as a single file you can pull and
run directly:

    curl -fsSL https://raw.githubusercontent.com/pierspad/LazyGimp/main/lazygimp.py -o lazygimp.py
    python3 lazygimp.py

No arguments opens the GUI. It has zero *hard* dependencies beyond the
Python standard library (Tkinter, which ships with most distro Python
packages) — Pillow is used only for anti-aliased icons if present.

It is also a normal command-line tool for headless boxes / scripting:

    python3 lazygimp.py status                     # what's installed
    python3 lazygimp.py install photogimp gmic sam batcher
    python3 lazygimp.py remove batcher
    python3 lazygimp.py sam list
    python3 lazygimp.py sam install sam2_hiera_small
    python3 lazygimp.py sam3 download --token hf_xxx
    python3 lazygimp.py --ephemeral                 # GUI, self-deletes on exit

Design notes
------------
* Every component (GIMP itself, PhotoGIMP, G'MIC, SAM, Batcher) is
  independently installable, repairable (= re-run the same idempotent
  install step) and removable — there is no "custom install wizard" you
  must funnel through single-shot; the "Manage" screen in the GUI is just
  cards, each fully self-contained, in priority order:
  PhotoGIMP > G'MIC > SAM > Batcher (GIMP itself is the one prerequisite
  step ahead of all four).
* State is never tracked in a side file that can drift from reality —
  every "is X installed?" question is answered by looking at the
  filesystem/package database directly (a manifest file IS used for
  PhotoGIMP, to know which files it is safe to remove later without
  touching the user's own GIMP configuration — same convention the old
  shell implementation used, so upgrading from it is seamless).
* SAM models: once a model is on disk it is no longer a "pick me"
  checkbox — it turns into a card with Remove (and, for a model with an
  active/queued download elsewhere, Cancel), exactly mirroring how
  GIMPSAM's own installer already treated per-model state. Models still
  missing show Install (or "Add to queue" while another download is
  already running).
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import platform
import pty
import queue
import re
import select
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import webbrowser
import zipfile
from dataclasses import dataclass, field
from typing import Callable, Optional

try:
    import tkinter as tk
    from tkinter import simpledialog, ttk
    _TK_OK = True
except Exception:
    _TK_OK = False

try:
    from PIL import Image, ImageDraw, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


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
PHOTOGIMP_RELEASE_TAG = "3.0"

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


# ---------------------------------------------------------------------------
# SAM model registry — the single source of truth for every SAM checkpoint
# this installer knows how to fetch (replaces config/versions.conf's
# SAM_MODELS bash associative array).
# ---------------------------------------------------------------------------

@dataclass
class ModelSpec:
    key: str
    family: str  # "SAM1", "SAM2", "SAM3"
    label: str
    size: str
    quality: int  # 1-5, rough/comparable within a family
    speed: int  # 1-5
    filename: Optional[str] = None  # None only for SAM3 (a folder, not a file)
    url: Optional[str] = None  # None only for SAM3 (gated — downloaded via HF token)


MODEL_REGISTRY: list[ModelSpec] = [
    ModelSpec("sam_vit_b", "SAM1", "vit_b", "375 MB", quality=2, speed=5,
              filename="sam_vit_b_01ec64.pth",
              url="https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth"),
    ModelSpec("sam_vit_l", "SAM1", "vit_l", "1.2 GB", quality=3, speed=3,
              filename="sam_vit_l_0b3195.pth",
              url="https://dl.fbaipublicfiles.com/segment_anything/sam_vit_l_0b3195.pth"),
    ModelSpec("sam_vit_h", "SAM1", "vit_h", "2.5 GB", quality=4, speed=1,
              filename="sam_vit_h_4b8939.pth",
              url="https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth"),
    ModelSpec("sam2_hiera_tiny", "SAM2", "hiera_tiny", "150 MB", quality=2, speed=5,
              filename="sam2_hiera_tiny.pt",
              url="https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_tiny.pt"),
    ModelSpec("sam2_hiera_small", "SAM2", "hiera_small", "180 MB", quality=3, speed=4,
              filename="sam2_hiera_small.pt",
              url="https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_small.pt"),
    ModelSpec("sam2_hiera_base_plus", "SAM2", "hiera_base_plus", "320 MB", quality=4, speed=3,
              filename="sam2_hiera_base_plus.pt",
              url="https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_base_plus.pt"),
    ModelSpec("sam2_hiera_large", "SAM2", "hiera_large", "900 MB", quality=5, speed=2,
              filename="sam2_hiera_large.pt",
              url="https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_large.pt"),
    ModelSpec("sam3", "SAM3", "sam3.1", "~3.4 GB", quality=5, speed=1),
]
MODEL_BY_KEY = {m.key: m for m in MODEL_REGISTRY}


def model_path(spec: ModelSpec) -> str:
    if spec.family == "SAM3":
        return os.path.join(MODELS_DIR, "sam3")
    return os.path.join(MODELS_DIR, spec.filename)


def model_installed(spec: ModelSpec) -> bool:
    p = model_path(spec)
    if spec.family == "SAM3":
        # snapshot_download() failing partway through (e.g. a 403 on a
        # gated/unapproved repo) can still leave a few small metadata files
        # behind — "folder is non-empty" would then wrongly read as
        # installed. config.json is one of the last files HF writes, so its
        # presence is a real signal the snapshot completed.
        return os.path.isdir(p) and os.path.isfile(os.path.join(p, "config.json"))
    return os.path.isfile(p)


def any_model_installed() -> bool:
    return any(model_installed(m) for m in MODEL_REGISTRY)


# ---------------------------------------------------------------------------
# Hardware detection — used only to pick a sane default SAM model.
# ---------------------------------------------------------------------------

@dataclass
class Hardware:
    cpu_cores: int
    python_version: str
    gpu: Optional[dict]


def detect_gpu() -> Optional[dict]:
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            line = next((l for l in out.stdout.splitlines() if l.strip()), None)
            if line:
                return {"vendor": "NVIDIA", "name": line.strip(), "driver_ready": True}
        except Exception:
            pass
    if shutil.which("rocminfo"):
        try:
            out = subprocess.run(["rocminfo"], capture_output=True, text=True, timeout=5)
            name = next(
                (l.split(":", 1)[1].strip() for l in out.stdout.splitlines() if "Marketing Name" in l), None,
            )
            return {"vendor": "AMD (ROCm)", "name": name or "AMD GPU", "driver_ready": True}
        except Exception:
            pass
    if shutil.which("lspci"):
        try:
            out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5)
            for line in out.stdout.splitlines():
                low = line.lower()
                if "vga" in low or "3d controller" in low:
                    desc = line.split(":", 2)[-1].strip()
                    if "nvidia" in low:
                        return {"vendor": "NVIDIA", "name": desc, "driver_ready": False}
                    if "amd" in low or "advanced micro devices" in low or "radeon" in low:
                        return {"vendor": "AMD", "name": desc, "driver_ready": False}
        except Exception:
            pass
    return None


def detect_hardware() -> Hardware:
    return Hardware(cpu_cores=os.cpu_count() or 1, python_version=platform.python_version(), gpu=detect_gpu())


def recommended_model_key(hw: Hardware) -> str:
    return "sam2_hiera_base_plus" if (hw.gpu and hw.gpu.get("driver_ready")) else "sam2_hiera_small"


def recommended_torch_index(hw: Hardware) -> str:
    if hw.gpu and hw.gpu.get("driver_ready"):
        if "NVIDIA" in hw.gpu["vendor"]:
            return TORCH_INDEX_URLS["NVIDIA CUDA 12.8"]
        if "AMD" in hw.gpu["vendor"]:
            return TORCH_INDEX_URLS["AMD ROCm 6.2"]
    return TORCH_INDEX_URLS["CPU (universal, smaller download)"]


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


# ---------------------------------------------------------------------------
# GIMP detection — install kind, version, per-user config dir. Nothing here
# hardcodes a GIMP version: the config directory (3.0, 3.2, ...) is always
# resolved at runtime.
# ---------------------------------------------------------------------------

def find_gimp_binary() -> Optional[str]:
    return shutil.which("gimp") or shutil.which("gimp-3.0") or shutil.which("gimp-2.10")


def find_gimp_command() -> Optional[list[str]]:
    """The command to *launch* GIMP with — native binary on PATH, or (for an
    AppImage-only install, which is never on PATH) the newest AppImage."""
    bin_ = find_gimp_binary()
    if bin_:
        return [bin_]
    images = sorted(glob.glob(os.path.join(APPIMAGE_DIR, "GIMP-*.AppImage")))
    return [images[-1]] if images else None


def gimp_version_string() -> Optional[str]:
    bin_ = find_gimp_binary()
    if not bin_:
        return None
    try:
        out = subprocess.run([bin_, "--version"], capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    m = re.search(r"(\d+)\.(\d+)(?:\.\d+)?", out.stdout or "")
    return f"{m.group(1)}.{m.group(2)}" if m else None


def gimp_config_base() -> str:
    return os.path.join(XDG_CONFIG_HOME, "GIMP")


def _version_key(name: str):
    try:
        return tuple(int(p) for p in name.split("."))
    except ValueError:
        return (0,)


def gimp_version_dirs() -> list[str]:
    base = gimp_config_base()
    if not os.path.isdir(base):
        return []
    names = [n for n in os.listdir(base) if re.fullmatch(r"\d+\.\d+", n) and os.path.isdir(os.path.join(base, n))]
    names.sort(key=_version_key)
    return [os.path.join(base, n) for n in names]


def gimp_live_config_dir() -> Optional[str]:
    """The config dir GIMP actually reads, proven by a live `pluginrc` —
    more reliable than trusting `gimp --version`, whose reported MAJOR.MINOR
    is not guaranteed to equal the profile directory name GIMP actually
    uses."""
    for d in reversed(gimp_version_dirs()):
        if os.path.isfile(os.path.join(d, "pluginrc")):
            return d
    return None


def gimp_config_dir(version_hint: Optional[str] = None) -> Optional[str]:
    base = gimp_config_base()
    if version_hint:
        m = re.search(r"(\d+)\.(\d+)", version_hint)
        if m:
            return os.path.join(base, f"{m.group(1)}.{m.group(2)}")
    live = gimp_live_config_dir()
    if live:
        return live
    ver = gimp_version_string()
    if ver:
        return os.path.join(base, ver)
    dirs = gimp_version_dirs()
    return dirs[-1] if dirs else None


def gimp_plugins_dir(version_hint: Optional[str] = None) -> Optional[str]:
    cfg = gimp_config_dir(version_hint)
    return os.path.join(cfg, "plug-ins") if cfg else None


def invalidate_gimp_plugin_cache(job: "Job") -> None:
    for d in gimp_version_dirs():
        pluginrc = os.path.join(d, "pluginrc")
        if os.path.isfile(pluginrc):
            try:
                os.remove(pluginrc)
                job.log(f"Cleared {pluginrc} so GIMP rescans plug-ins on next launch")
            except OSError as e:
                job.log(f"Could not clear {pluginrc}: {e} (not fatal)")


def gimp_warm_up(job: "Job", gimp_cmd: Optional[str] = None) -> None:
    """Launch GIMP once, headless, so it generates its per-user config tree
    — must happen before PhotoGIMP/plug-ins are applied on a fresh install."""
    if gimp_version_dirs():
        return
    cmd = gimp_cmd or find_gimp_binary()
    if not cmd:
        return
    warmup_log = os.path.join(ensure_state_dir(), "warmup.log")
    job.log("First GIMP start — generating configuration (one-time step)...")
    timeout = int(os.environ.get("LAZYGIMP_WARMUP_TIMEOUT", "120"))
    try:
        with open(warmup_log, "wb") as lf:
            subprocess.run([cmd, "-i", "-d", "-f", "-s", "-b", "(gimp-quit 0)"],
                            stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT, timeout=timeout)
        job.log("GIMP configuration initialized")
    except subprocess.TimeoutExpired:
        job.log(f"GIMP warm-up did not finish within {timeout}s (log: {warmup_log}); continuing anyway")
    except Exception as e:
        job.log(f"GIMP warm-up did not finish cleanly ({e}); continuing anyway")
    if not gimp_version_dirs():
        ver = gimp_version_string()
        if ver:
            os.makedirs(os.path.join(gimp_config_base(), ver), exist_ok=True)
            job.log(f"created {gimp_config_base()}/{ver} (GIMP will adopt it on first launch)")


# ---------------------------------------------------------------------------
# Job — background work + logging, shared by every long-running action
# (installs, downloads, removals) whether driven by the GUI or the CLI.
# ---------------------------------------------------------------------------

class Job:
    def __init__(self, log_queue: Optional["queue.Queue[str]"] = None, password_prompt=None):
        self.log_queue = log_queue
        self.password_prompt = password_prompt  # callable(str) -> str, GUI-only
        self.cancel_event = threading.Event()
        self.proc: Optional[subprocess.Popen] = None

    def cancel(self):
        self.cancel_event.set()
        if self.proc is not None:
            try:
                self.proc.terminate()
            except Exception:
                pass

    def log(self, msg: str):
        print(msg, flush=True)
        if self.log_queue is not None:
            self.log_queue.put(msg)

    def run_cmd(self, cmd: list[str], **kw) -> int:
        if self.cancel_event.is_set():
            self.log("Cancelled — skipping: " + " ".join(cmd))
            return -1
        self.log("$ " + " ".join(cmd))
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, **kw)
        for line in iter(self.proc.stdout.readline, ""):
            if line:
                self.log(line.rstrip("\n"))
        self.proc.wait()
        rc = self.proc.returncode
        self.proc = None
        return rc

    def run_cmd_capture(self, cmd: list[str], **kw) -> tuple[int, list[str]]:
        if self.cancel_event.is_set():
            self.log("Cancelled — skipping: " + " ".join(cmd))
            return -1, []
        self.log("$ " + " ".join(cmd))
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, **kw)
        lines: list[str] = []
        for line in iter(self.proc.stdout.readline, ""):
            if line:
                clean = line.rstrip("\n")
                self.log(clean)
                lines.append(clean)
        self.proc.wait()
        rc = self.proc.returncode
        self.proc = None
        return rc, lines

    def run_root(self, cmd: list[str], env: Optional[dict] = None) -> int:
        """Run a command that needs root. With a GUI password_prompt, uses a
        pty so an internal `sudo` can actually prompt (a plain subprocess has
        no controlling terminal at all). From a real terminal (CLI usage),
        sudo already has one — no pty tricks needed, just run it directly."""
        env = env or os.environ.copy()
        if os.geteuid() == 0:
            return self.run_cmd(cmd, env=env)
        prefix = ["sudo"] if shutil.which("sudo") else (["doas"] if shutil.which("doas") else None)
        if prefix is None:
            self.log("ERROR: root privileges required, but neither sudo nor doas is installed.")
            return 1
        full_cmd = prefix + cmd
        if self.password_prompt is not None:
            return run_cmd_sudo_pty(self, full_cmd, env, self.password_prompt)
        self.log("$ " + " ".join(full_cmd) + "  (may prompt for your password below)")
        try:
            r = subprocess.run(full_cmd, env=env)
            return r.returncode
        except Exception as e:
            self.log(f"ERROR: {e}")
            return 1

    def download(self, url: str, dest: str, cancel_event: Optional[threading.Event] = None, progress_cb=None,
                 headers: Optional[dict] = None) -> bool:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        part = dest + ".part"
        self.log(f"Downloading {url}")
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as resp, open(part, "wb") as out:
                total = int(resp.headers.get("Content-Length", 0))
                read = 0
                last_pct = -1
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        self.log("Cancelled.")
                        return False
                    buf = resp.read(1024 * 256)
                    if not buf:
                        break
                    out.write(buf)
                    read += len(buf)
                    if progress_cb:
                        progress_cb(read, total)
                    if total:
                        pct = int(read * 100 / total)
                        if pct != last_pct and pct % 5 == 0:
                            self.log(f"  {pct}%  ({read // (1024*1024)} MB / {total // (1024*1024)} MB)")
                            last_pct = pct
            os.replace(part, dest)
            self.log(f"Saved to {dest}")
            return True
        except Exception as e:
            self.log(f"ERROR downloading {url}: {e}")
            return False
        finally:
            if os.path.exists(part):
                try:
                    os.remove(part)
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# The installer's data model: a plan (checklist) of actions the user has
# queued up, plus the wizard pages used to build one interactively. Neither
# of these two classes touches Tk or the filesystem — they are pure data,
# which is what makes them reusable from the paginated wizard, from Quick
# Setup's one-click prefill, and (if it's ever wanted) from a future CLI
# "plan" subcommand, without duplicating any install/remove logic.
# ---------------------------------------------------------------------------

@dataclass
class PlannedAction:
    """One row of the checklist: something to do later, not now.

    `key` is what makes the checklist idempotent — toggling the same button
    twice adds then removes the same entry instead of piling up duplicates.
    `run` is only ever invoked by the shared executor (see
    LazyGimpApp._run_plan), never at the moment the user clicks a button.
    """
    key: str
    label: str
    kind: str  # "install" | "remove" — cosmetic only (icon/colour on Review)
    run: Callable[["Job"], None]


class InstallPlan:
    """An ordered, de-duplicated checklist of PlannedAction. A dict keyed by
    `action.key` gives both O(1) membership checks and stable insertion
    order (Python dicts preserve it), which is exactly what the Review page
    and the executor need."""

    def __init__(self):
        self._items: dict[str, PlannedAction] = {}

    def add(self, action: PlannedAction) -> None:
        self._items[action.key] = action

    def toggle(self, action: PlannedAction) -> bool:
        """Add `action` if its key isn't queued yet, else remove it.
        Returns the new membership (True = now queued)."""
        if action.key in self._items:
            del self._items[action.key]
            return False
        self._items[action.key] = action
        return True

    def discard(self, key: str) -> None:
        self._items.pop(key, None)

    def has(self, key: str) -> bool:
        return key in self._items

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(self._items.values())


@dataclass
class WizardStep:
    """One page of the paginated installer. `prerequisite=True` marks the
    one step (GIMP itself) that is skipped entirely when already satisfied,
    and that cannot be skipped manually while it's showing."""
    key: str
    title: str
    prerequisite: bool = False


def run_cmd_sudo_pty(job: Job, cmd: list[str], env: dict, password_prompt) -> int:
    """Run `cmd` with its controlling terminal attached to a fresh pty, so an
    internal `sudo` can prompt for a password even though this process (a Tk
    GUI) has none of its own. `password_prompt(text) -> str` must block until
    answered; it is responsible for hopping onto the GUI's own main thread
    and back, if needed."""
    job.log("$ " + " ".join(cmd))
    pid, master_fd = pty.fork()
    if pid == 0:  # child
        try:
            os.execvpe(cmd[0], cmd, env)
        except Exception:
            os._exit(127)

    buf = b""
    try:
        while True:
            if job.cancel_event.is_set():
                job.log("Cancel requested — terminating...")
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                r, _, _ = select.select([master_fd], [], [], 0.2)
            except OSError:
                break
            if master_fd in r:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    chunk = b""
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    job.log(line.decode(errors="replace").rstrip("\r"))
                tail = buf.decode(errors="replace")
                if tail and tail.rstrip().endswith(":") and "password" in tail.lower():
                    pw = password_prompt(tail.strip())
                    os.write(master_fd, ((pw or "") + "\n").encode())
                    buf = b""
            try:
                wpid, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                break
            if wpid == pid:
                try:
                    while True:
                        chunk = os.read(master_fd, 4096)
                        if not chunk:
                            break
                        buf += chunk
                except OSError:
                    pass
                if buf:
                    job.log(buf.decode(errors="replace"))
                    buf = b""
                return os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1
    finally:
        if buf:
            job.log(buf.decode(errors="replace"))
        try:
            os.close(master_fd)
        except OSError:
            pass
    try:
        _, status = os.waitpid(pid, 0)
        return os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1
    except ChildProcessError:
        return 1


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


# ---------------------------------------------------------------------------
# PhotoGIMP — the configuration layer (icons, shortcuts, splash, layout).
# Version-agnostic (re-targeted onto whatever config dir the installed GIMP
# actually uses) and non-destructive (full backup + manifest, so it can be
# upgraded/removed cleanly without ever touching the user's own files).
# ---------------------------------------------------------------------------

def photogimp_target_dir() -> Optional[str]:
    return gimp_live_config_dir()  # only "installed" if GIMP has actually adopted a profile


def photogimp_installed() -> bool:
    for d in gimp_version_dirs():
        if os.path.isfile(os.path.join(d, PHOTOGIMP_MANIFEST)):
            return True
    return False


def _photogimp_download_and_extract(job: Job) -> Optional[str]:
    tmp = tempfile.mkdtemp(prefix="lazygimp-photogimp-")
    zip_path = os.path.join(tmp, "photogimp.zip")
    base_url = f"https://github.com/{PHOTOGIMP_REPO}/releases/download/{PHOTOGIMP_RELEASE_TAG}"
    if not job.download(f"{base_url}/PhotoGIMP-linux.zip", zip_path):
        if not job.download(f"{base_url}/PhotoGIMP.zip", zip_path):
            return None
    extracted = os.path.join(tmp, "extracted")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extracted)
    return extracted


def _photogimp_locate_payload(extracted: str) -> Optional[str]:
    candidates = []
    for root, dirs, _files in os.walk(extracted):
        if re.search(r"/\.config/GIMP/(\d+\.\d+)$", root.replace(os.sep, "/")):
            candidates.append(root)
    if not candidates:
        return None
    candidates.sort(key=lambda p: _version_key(os.path.basename(p)))
    return candidates[-1]


def _photogimp_backup(target: str) -> Optional[str]:
    if not os.path.isdir(target):
        return None
    backups_dir = os.path.join(ensure_state_dir(), "backups")
    os.makedirs(backups_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(backups_dir, f"gimp-config-{os.path.basename(target)}-{stamp}.tar.gz")
    with tarfile.open(backup, "w:gz") as tf:
        tf.add(target, arcname=os.path.basename(target))
    return backup


def _photogimp_apply(payload: str, target: str, job: Job) -> int:
    os.makedirs(target, exist_ok=True)
    manifest_path = os.path.join(target, PHOTOGIMP_MANIFEST)
    count = 0
    with open(manifest_path, "w", encoding="utf-8") as manifest:
        for root, _dirs, files in os.walk(payload):
            for name in files:
                src = os.path.join(root, name)
                rel = os.path.relpath(src, payload)
                if rel in PHOTOGIMP_EXCLUDE:
                    continue
                dst = os.path.join(target, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                os.chmod(dst, 0o644)
                manifest.write(rel + "\n")
                count += 1
    return count


def _photogimp_install_desktop_files(extracted: str, gimp_command: Optional[str], job: Job) -> None:
    share = None
    for root, dirs, _files in os.walk(extracted):
        if root.replace(os.sep, "/").endswith("/.local/share"):
            share = root
            break
    if not share:
        return
    ensure_state_dir()
    manifest_lines = []
    for root, _dirs, files in os.walk(share):
        for name in files:
            src = os.path.join(root, name)
            rel = os.path.relpath(src, share)
            dst = os.path.join(XDG_DATA_HOME, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            os.chmod(dst, 0o644)
            manifest_lines.append(dst)

    # Retarget Exec to the GIMP LazyGimp actually set up, and capture
    # Icon=/StartupWMClass= from the real entry along the way — both are
    # needed below to make the *hidden* shadow entry a fully working
    # launcher too, not just Exec-less bait.
    exec_line = f"{gimp_command or 'gimp'} %U"
    icon_name = "photogimp"
    wm_class = None
    for f in manifest_lines:
        if not f.endswith(".desktop"):
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                lines = fh.readlines()
            with open(f, "w", encoding="utf-8") as fh:
                for line in lines:
                    if line.startswith("Exec="):
                        fh.write(f"Exec={exec_line}\n")
                    elif line.startswith("TryExec=") or line.startswith("DBusActivatable="):
                        continue
                    else:
                        if line.startswith("Icon="):
                            icon_name = line.strip().split("=", 1)[1] or icon_name
                        elif line.startswith("StartupWMClass="):
                            wm_class = line.strip().split("=", 1)[1] or wm_class
                        fh.write(line)
        except OSError as e:
            job.log(f"Could not retarget {f}: {e} (not fatal)")

    # KDE/Plasma's taskbar resolves a *running window* back to a launcher
    # (for its icon, and for "pin to taskbar") primarily by desktop-file id
    # matching the window's own reported app id — which for GIMP is plain
    # "gimp", i.e. it looks up "gimp.desktop" specifically, NOT
    # "org.gimp.GIMP.desktop" (the file PhotoGIMP actually ships and the
    # one that correctly shows up in the app launcher/menu above). Every
    # distro also ships its own real /usr/share/applications/gimp.desktop,
    # so without a same-named override in this (higher-priority) user
    # data dir, the taskbar would use THAT one instead of ours — hence a
    # generic/system icon whenever the window is pinned or grouped.
    #
    # The previous approach wrote that override only as a bare
    # NoDisplay/no-Exec stub, purely to hide the duplicate stock menu
    # entry. That is exactly what broke the taskbar: Plasma resolved the
    # running GIMP window to precisely THIS file, found no Exec/Icon in
    # it, and both the generic/Wayland fallback icon and the "No Exec
    # field in .../gimp.desktop" launch-failure notification follow
    # directly from that. Fix: make this file a full, working duplicate
    # of the real launcher (same Exec/Icon/StartupWMClass) and keep
    # NoDisplay=true only so it never shows as a second menu entry.
    #
    # Always (re)written — never gated on "doesn't already exist yet" —
    # so re-running/repairing PhotoGIMP through the installer also heals
    # a broken stub left behind by an older version of this installer.
    hidden = os.path.join(XDG_DATA_HOME, "applications", "gimp.desktop")
    os.makedirs(os.path.dirname(hidden), exist_ok=True)
    entry = ["[Desktop Entry]", "Version=1.0", "Type=Application", "Name=GIMP",
             f"Icon={icon_name}", f"Exec={exec_line}",
             f"StartupWMClass={wm_class or 'gimp'}", "Terminal=false", "NoDisplay=true"]
    with open(hidden, "w", encoding="utf-8") as fh:
        fh.write("\n".join(entry) + "\n")
    if hidden not in manifest_lines:
        manifest_lines.append(hidden)
    job.log(f"Wrote a working shadow launcher at {hidden} "
            "(fixes the taskbar/window icon and pin-to-taskbar for GIMP)")

    with open(DESKTOP_FILES_MANIFEST, "w", encoding="utf-8") as fh:
        fh.write("\n".join(manifest_lines) + "\n")

    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", os.path.join(XDG_DATA_HOME, "applications")],
                        capture_output=True)
    icon_theme_dir = os.path.join(XDG_DATA_HOME, "icons", "hicolor")
    if shutil.which("gtk-update-icon-cache") and os.path.isdir(icon_theme_dir):
        subprocess.run(["gtk-update-icon-cache", "-q", "-t", "-f", icon_theme_dir], capture_output=True)
        job.log(f"Refreshed the icon cache ({icon_theme_dir})")
    job.log("PhotoGIMP desktop entry installed (launches the GIMP LazyGimp set up)")


def repair_desktop_integration(job: Job) -> bool:
    """Fixes the taskbar/window-icon + pin-to-taskbar bug WITHOUT
    re-downloading PhotoGIMP: reads the already-installed real launcher
    (found via its Icon=photogimp marker) and regenerates the
    ~/.local/share/applications/gimp.desktop shadow entry from it, exactly
    like install_photogimp() does at the end of a full run. Safe to run any
    time, does not touch the PhotoGIMP payload/config files at all — only
    the two .desktop files and the icon cache."""
    apps_dir = os.path.join(XDG_DATA_HOME, "applications")
    real_file = None
    for f in glob.glob(os.path.join(apps_dir, "*.desktop")):
        if os.path.basename(f) == "gimp.desktop":
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                content = fh.read()
        except OSError:
            continue
        if "Icon=photogimp" in content or "PhotoGIMP" in content:
            real_file = f
            break
    if not real_file:
        job.log("No installed PhotoGIMP launcher found — run Install/Repair PhotoGIMP first.")
        return False

    icon_name, wm_class, exec_line = "photogimp", "gimp", None
    for line in content.splitlines():
        if line.startswith("Icon="):
            icon_name = line.split("=", 1)[1] or icon_name
        elif line.startswith("StartupWMClass="):
            wm_class = line.split("=", 1)[1] or wm_class
        elif line.startswith("Exec="):
            exec_line = line.split("=", 1)[1] or exec_line
    exec_line = exec_line or f"{find_gimp_binary() or 'gimp'} %U"

    hidden = os.path.join(apps_dir, "gimp.desktop")
    entry = ["[Desktop Entry]", "Version=1.0", "Type=Application", "Name=GIMP",
             f"Icon={icon_name}", f"Exec={exec_line}",
             f"StartupWMClass={wm_class}", "Terminal=false", "NoDisplay=true"]
    with open(hidden, "w", encoding="utf-8") as fh:
        fh.write("\n".join(entry) + "\n")
    job.log(f"Rewrote {hidden} as a working shadow launcher (Icon={icon_name}, "
            f"StartupWMClass={wm_class}) — restart GIMP (and re-pin it) to see the fix.")

    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", apps_dir], capture_output=True)
    icon_theme_dir = os.path.join(XDG_DATA_HOME, "icons", "hicolor")
    if shutil.which("gtk-update-icon-cache") and os.path.isdir(icon_theme_dir):
        subprocess.run(["gtk-update-icon-cache", "-q", "-t", "-f", icon_theme_dir], capture_output=True)
    return True


def _photogimp_remove_desktop_files(job: Job) -> None:
    if not os.path.isfile(DESKTOP_FILES_MANIFEST):
        return
    with open(DESKTOP_FILES_MANIFEST, encoding="utf-8") as fh:
        for line in fh:
            f = line.strip()
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
    os.remove(DESKTOP_FILES_MANIFEST)
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", os.path.join(XDG_DATA_HOME, "applications")],
                        capture_output=True)


def install_photogimp(job: Job, version_hint: Optional[str] = None, gimp_command: Optional[str] = None) -> bool:
    target = gimp_config_dir(version_hint)
    if not target:
        job.log("ERROR: cannot locate a GIMP config directory — launch GIMP once, then retry.")
        return False
    profile_name = os.path.basename(target)
    m = re.match(r"(\d+)\.", profile_name)
    if m and int(m.group(1)) < 3:
        job.log(f"ERROR: PhotoGIMP requires GIMP 3+, but the detected profile is {profile_name}")
        return False

    job.log(f"GIMP config directory: {target}")
    extracted = _photogimp_download_and_extract(job)
    if not extracted:
        return False
    payload = _photogimp_locate_payload(extracted)
    if not payload:
        job.log("ERROR: no GIMP payload (.config/GIMP/X.Y) found in the PhotoGIMP archive.")
        return False

    backup = _photogimp_backup(target)
    if backup:
        job.log(f"Existing configuration backed up to {backup}")

    count = _photogimp_apply(payload, target, job)
    _photogimp_install_desktop_files(extracted, gimp_command, job)
    shutil.rmtree(os.path.dirname(extracted), ignore_errors=True)
    job.log(f"PhotoGIMP layer installed ({count} files) into {profile_name}")
    return True


def remove_photogimp(job: Job) -> bool:
    found = False
    for target in gimp_version_dirs():
        manifest_path = os.path.join(target, PHOTOGIMP_MANIFEST)
        if not os.path.isfile(manifest_path):
            continue
        found = True
        job.log(f"Removing PhotoGIMP layer from {target}")
        with open(manifest_path, encoding="utf-8") as fh:
            rels = [l.strip() for l in fh if l.strip()]
        for rel in rels:
            p = os.path.join(target, rel)
            if os.path.isfile(p) or os.path.islink(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        os.remove(manifest_path)
        # prune now-empty directories
        for root, dirs, files in os.walk(target, topdown=False):
            if not dirs and not files:
                try:
                    os.rmdir(root)
                except OSError:
                    pass
    _photogimp_remove_desktop_files(job)
    if found:
        job.log(f"PhotoGIMP layer removed; personal files were left untouched. "
                f"Backups (if any) are in {os.path.join(STATE_DIR, 'backups')}")
    else:
        job.log("No PhotoGIMP layer found.")
    return True


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
    url = f"https://github.com/{BATCHER_REPO}/releases/download/{BATCHER_RELEASE_TAG}/batcher-{BATCHER_RELEASE_TAG}.zip"
    src = _download_zip_and_find(job, url, "batcher")
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


# ---------------------------------------------------------------------------
# SAM Python backend — venv, PyTorch, SAM1+SAM2 packages (the bridge imports
# both unconditionally), checkpoint downloads, self-test.
# ---------------------------------------------------------------------------

def venv_exists() -> bool:
    return os.path.isfile(VENV_PYTHON) and os.access(VENV_PYTHON, os.X_OK)


def backend_ready() -> bool:
    if not venv_exists():
        return False
    try:
        r = subprocess.run([VENV_PYTHON, "-c", "import torch"], capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def install_sam_backend(job: Job, torch_index: str) -> bool:
    os.makedirs(BACKEND_DIR, exist_ok=True)
    if not venv_exists():
        job.log(f"Creating virtualenv at {VENV_DIR}")
        if job.run_cmd([sys.executable, "-m", "venv", VENV_DIR]) != 0:
            job.log("Failed to create the virtualenv (is python3-venv installed?).")
            return False
    else:
        job.log(f"Reusing existing virtualenv at {VENV_DIR}")

    job.run_cmd([VENV_PIP, "install", "--upgrade", "pip"])
    job.log(f"Installing PyTorch from {torch_index}")
    if job.run_cmd([VENV_PIP, "install", "torch", "torchvision", "--index-url", torch_index]) != 0:
        job.log("PyTorch failed to install — almost always a network problem reaching "
                "download.pytorch.org rather than a bug here. Check your connection and retry.")
        return False
    job.log("Installing image dependencies (numpy, pillow, opencv)")
    job.run_cmd([VENV_PIP, "install", "numpy", "pillow", "opencv-python-headless"])
    job.log("Installing SAM1 backend (segment-anything)")
    job.run_cmd([VENV_PIP, "install", SAM1_PIP_SPEC])
    job.log("Installing SAM2 backend (segment-anything-2) — builds from source, can take a few minutes")
    if job.run_cmd([VENV_PIP, "install", SAM2_PIP_SPEC]) != 0:
        job.log("SAM2 failed to build/install — SAM1 models will still work, but the plug-in's bridge "
                f"imports both unconditionally. Install a C/C++ toolchain and retry — see {SEGANY_README}")
    job.log("Installing/upgrading huggingface_hub (needed for SAM 3.1)")
    job.run_cmd([VENV_PIP, "install", "-U", "huggingface_hub"])
    job.log("Python backend ready.")
    return True


def remove_sam_backend(job: Job) -> bool:
    if os.path.isdir(BACKEND_DIR):
        shutil.rmtree(BACKEND_DIR)
        job.log(f"SAM backend removed ({BACKEND_DIR})")
    else:
        job.log("No SAM backend found.")
    return True


def install_sam3_transformers(job: Job) -> bool:
    if not backend_ready():
        job.log("Set up the Python backend first.")
        return False
    job.log("Installing/upgrading transformers (needed to run SAM 3.1)")
    return job.run_cmd([VENV_PIP, "install", "-U", "transformers", "huggingface_hub"]) == 0


def bridge_self_test(job: Job, primary: ModelSpec) -> None:
    d = gimp_plugins_dir()
    plugin_dir = os.path.join(d, "seganyplugin") if d else None
    if not plugin_dir or not os.path.isdir(plugin_dir):
        return
    bridges = glob.glob(os.path.join(plugin_dir, "seganybridge*.py"))
    if not bridges:
        job.log("Bridge script not found; skipping self-test.")
        return
    job.log("Running the bridge self-test (first run compiles kernels, be patient)...")
    try:
        r = subprocess.run([VENV_PYTHON, bridges[0], "auto", model_path(primary)],
                            capture_output=True, text=True, cwd=plugin_dir, timeout=300)
        out = (r.stdout or "") + (r.stderr or "")
        if "success" in out.lower():
            job.log("Bridge self-test passed — the SAM backend is fully functional.")
        else:
            job.log(f"Bridge self-test did not report success — see {SEGANY_README} for troubleshooting.")
    except Exception as e:
        job.log(f"Bridge self-test could not run: {e}")


def write_sam_info(models: list[str]) -> str:
    os.makedirs(BACKEND_DIR, exist_ok=True)
    primary = MODEL_BY_KEY[models[0]]
    info = os.path.join(BACKEND_DIR, "INFO.txt")
    with open(info, "w", encoding="utf-8") as fh:
        fh.write(
            "LazyGimp — Segment Anything backend\n"
            "===================================\n\n"
            "On the FIRST run of the plug-in (GIMP -> Image -> Segment Anything Layers),\n"
            "fill in these two fields -- GIMP remembers them afterwards:\n\n"
            f"  Python3 Path:    {VENV_PYTHON}\n"
            f"  Checkpoint Path: {model_path(primary)}\n\n"
            "Model Type: leave \"Auto\" in the dialog -- inferred from the checkpoint filename.\n\n"
            f"Installed model(s): {', '.join(models)}\n"
            f"Checkpoints live in: {MODELS_DIR}\n"
        )
    return info


# ---------------------------------------------------------------------------
# SAM 3.1 — gated on Hugging Face. The generic huggingface_hub error text
# ("...we cannot find the requested files in the local cache...") is what
# you get for a plain 401/403 too, so string-sniffing the exception message
# alone cannot reliably tell "not approved yet" apart from "bad token" apart
# from "actually offline". Instead, probe explicitly and in order: does the
# token authenticate at all (whoami), does IT have access to the gated repo
# (model_info) — only THEN attempt the real (multi-GB) download. This is
# what actually fixes "non so perché non scarica il modello sam3.1": the
# failure now names the exact cause instead of a generic cache-miss message.
# ---------------------------------------------------------------------------

def build_sam3_download_script(dest: str, token: str) -> str:
    return (
        "import sys\n"
        "from huggingface_hub import HfApi, snapshot_download\n"
        "try:\n"
        "    from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError\n"
        "except ImportError:\n"
        "    GatedRepoError = RepositoryNotFoundError = Exception\n"
        f"token = {token!r} or None\n"
        "api = HfApi()\n"
        "try:\n"
        "    api.whoami(token=token)\n"
        "except Exception as e:\n"
        "    print('ERROR-AUTH: token was rejected — ' + str(e).splitlines()[0])\n"
        "    sys.exit(1)\n"
        "try:\n"
        f"    api.model_info({SAM3_HF_REPO_ID!r}, token=token)\n"
        "except GatedRepoError:\n"
        "    print('ERROR-GATED: access to " + SAM3_HF_REPO_ID + " has not been approved yet for this account')\n"
        "    sys.exit(1)\n"
        "except RepositoryNotFoundError:\n"
        "    print('ERROR-AUTH: this token has no access to " + SAM3_HF_REPO_ID + " (401)')\n"
        "    sys.exit(1)\n"
        "except Exception as e:\n"
        "    print('ERROR-NETWORK: ' + str(e).splitlines()[0])\n"
        "    sys.exit(1)\n"
        "try:\n"
        f"    snapshot_download(repo_id={SAM3_HF_REPO_ID!r}, local_dir={dest!r}, token=token)\n"
        f"    print('SAM 3.1 checkpoint downloaded to', {dest!r})\n"
        "except Exception as e:\n"
        "    print('ERROR-OTHER: ' + str(e).splitlines()[0])\n"
        "    sys.exit(1)\n"
    )


def classify_sam3_failure(lines: list[str]) -> Optional[str]:
    for line in reversed(lines):
        if line.startswith("ERROR-"):
            return line
    return None


SAM3_FAILURE_MESSAGES = {
    "ERROR-GATED": (
        "Access denied — your Hugging Face account has requested but not yet been approved for {repo}. "
        "Request access at {page} if you haven't, wait for the approval email, then try again with the same token."
    ),
    "ERROR-AUTH": (
        "The token was rejected or has no access to {repo}. Generate a fresh READ token at "
        "huggingface.co/settings/tokens (after being approved at {page}) and paste it in again."
    ),
    "ERROR-NETWORK": (
        "Couldn't reach Hugging Face — check your internet connection (and any proxy/firewall), then retry. "
        "This is a several-GB download, so a flaky connection is a common cause."
    ),
}


def sam3_failure_message(tag: Optional[str]) -> str:
    if tag is None:
        return "Couldn't download the SAM 3.1 checkpoint — see the log above for the exact error."
    kind = tag.split(":", 1)[0].strip()
    detail = tag.split(":", 1)[1].strip() if ":" in tag else ""
    template = SAM3_FAILURE_MESSAGES.get(kind)
    if template is None:
        return f"Couldn't download the SAM 3.1 checkpoint: {detail or tag}"
    base = template.format(repo=SAM3_HF_REPO_ID, page=SAM3_HF_PAGE)
    return f"{base}\n\nDetails: {detail}" if detail else base


def download_sam3(job: Job, token: str) -> tuple[bool, Optional[str]]:
    if not backend_ready():
        job.log("Set up the Python backend first.")
        return False, None
    dest = model_path(MODEL_BY_KEY["sam3"])
    os.makedirs(dest, exist_ok=True)
    script = build_sam3_download_script(dest, token)
    job.log(f"Checking Hugging Face access for {SAM3_HF_REPO_ID}...")
    rc, lines = job.run_cmd_capture([VENV_PYTHON, "-c", script])
    ok = rc == 0
    tag = classify_sam3_failure(lines)
    job.log("SAM 3.1 checkpoint ready." if ok else "Download failed.")
    return ok, tag


def remove_sam3(job: Job) -> bool:
    dest = model_path(MODEL_BY_KEY["sam3"])
    if os.path.isdir(dest):
        shutil.rmtree(dest)
        job.log(f"Removed {dest}")
    else:
        job.log("SAM 3.1 was not installed.")
    return True


# ===========================================================================
# Everything below this line is the optional GUI. None of the functions
# above import tkinter, so `python3 lazygimp.py status` (etc.) works fine
# on a headless box with no Tk installed at all — see the CLI section
# further down and main() at the very end.
# ===========================================================================

if _TK_OK:
    # --- dark theme palette -------------------------------------------------
    BG = "#1b1d21"
    CARD_BG = "#26282e"
    CARD_BORDER = "#35373e"
    TEXT = "#e7e8ea"
    TEXT_MUTED = "#9a9da4"
    ACCENT = "#4dc3f0"
    ACCENT_HOVER = "#6fd0f5"
    ACCENT_TEXT = "#08222b"
    SUCCESS = "#3fbf7f"
    SUCCESS_HOVER = "#57cf93"
    DANGER = "#ee5a5f"
    DANGER_HOVER = "#f27478"
    WARNING = "#f2a93c"
    DISABLED_BG = "#34363c"
    DISABLED_TEXT = "#6d7076"

    # ------------------------------------------------------------------
    # Small monochrome vector icons — one geometry definition per icon
    # against a tiny backend-agnostic painter, targeting either a Tk
    # Canvas (no anti-aliasing) or a Pillow surface rendered at 4x and
    # downsampled (genuinely anti-aliased). Pillow stays optional so the
    # GUI has no hard dependency beyond Tkinter itself.
    # ------------------------------------------------------------------

    class _Painter:
        def __init__(self, target, pil=False):
            self.target = target
            self.pil = pil

        def line(self, pts, color, width=2):
            if self.pil:
                self.target.line(pts, fill=color, width=max(1, round(width)), joint="curve")
            else:
                self.target.create_line(*pts, fill=color, width=width, capstyle="round", joinstyle="round")

        def polygon(self, pts, color=None, outline=None, width=2):
            if self.pil:
                if color is not None:
                    self.target.polygon(pts, fill=color)
                if outline is not None:
                    self.target.polygon(pts, outline=outline, width=max(1, round(width)))
            else:
                self.target.create_polygon(*pts, fill=color or "", outline=outline or "", width=width)

        def rect(self, x1, y1, x2, y2, color=None, outline=None, width=2, radius=0):
            if self.pil:
                if radius > 0:
                    self.target.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=color, outline=outline,
                                                   width=max(1, round(width)))
                else:
                    self.target.rectangle([x1, y1, x2, y2], fill=color, outline=outline, width=max(1, round(width)))
            else:
                self.target.create_rectangle(x1, y1, x2, y2, fill=color or "", outline=outline or "", width=width)

        def oval(self, x1, y1, x2, y2, color=None, outline=None, width=2):
            if self.pil:
                self.target.ellipse([x1, y1, x2, y2], fill=color, outline=outline, width=max(1, round(width)))
            else:
                self.target.create_oval(x1, y1, x2, y2, fill=color or "", outline=outline or "", width=width)

        def arc(self, x1, y1, x2, y2, start, extent, color, width=2):
            if self.pil:
                self.target.arc([x1, y1, x2, y2], start=-(start + extent), end=-start, fill=color,
                                 width=max(1, round(width)))
            else:
                self.target.create_arc(x1, y1, x2, y2, start=start, extent=extent, style="arc", outline=color,
                                        width=width)

    def _paint_icon(p: _Painter, cx, cy, kind, color, s, frame=0):
        w = max(1.6, s * 0.16)
        if kind == "gear":
            outer_r, inner_r = s, s * 0.6
            tooth_half = s * 0.42
            for i in range(8):
                ang = math.radians(i * 45)
                ca, sa = math.cos(ang), math.sin(ang)
                corners = []
                for rr, tt in ((inner_r, -tooth_half), (outer_r, -tooth_half), (outer_r, tooth_half),
                               (inner_r, tooth_half)):
                    corners += [cx + rr * ca - tt * sa, cy + rr * sa + tt * ca]
                p.polygon(corners, color)
            p.oval(cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r, outline=color, width=s * 0.3)
        elif kind == "bolt":
            p.polygon([
                cx + s * 0.15, cy - s, cx - s * 0.65, cy + s * 0.1, cx - s * 0.05, cy + s * 0.1,
                cx - s * 0.15, cy + s, cx + s * 0.65, cy - s * 0.1, cx + s * 0.05, cy - s * 0.1,
            ], color)
        elif kind == "link":
            rx, ry, offset = s * 0.55, s * 0.4, s * 0.32
            ring_w = max(2.0, s * 0.24)
            p.oval(cx - offset - rx, cy - ry, cx - offset + rx, cy + ry, outline=color, width=ring_w)
            p.oval(cx + offset - rx, cy - ry, cx + offset + rx, cy + ry, outline=color, width=ring_w)
        elif kind == "trash":
            top, bottom = cy - s * 0.55, cy + s * 0.95
            top_half, bottom_half = s * 0.62, s * 0.5
            p.polygon([cx - top_half, top, cx + top_half, top, cx + bottom_half, bottom, cx - bottom_half, bottom],
                       outline=color, width=w)
            p.line([cx - s * 0.85, top, cx + s * 0.85, top], color, width=w)
            p.line([cx - s * 0.28, top, cx - s * 0.28, top - s * 0.28], color, width=w)
            p.line([cx + s * 0.28, top, cx + s * 0.28, top - s * 0.28], color, width=w)
            p.line([cx - s * 0.28, top - s * 0.28, cx + s * 0.28, top - s * 0.28], color, width=w)
            rib_w = max(1.4, s * 0.1)
            for fx in (-0.26, 0, 0.26):
                p.line([cx + fx * s, top + s * 0.2, cx + fx * s * 0.85, bottom - s * 0.12], color, width=rib_w)
        elif kind == "install":
            p.line([cx - s, cy + s * 0.15, cx - s, cy + s], color, width=w)
            p.line([cx - s, cy + s, cx + s, cy + s], color, width=w)
            p.line([cx + s, cy + s * 0.15, cx + s, cy + s], color, width=w)
            p.line([cx - s * 0.55, cy - s * 0.15, cx - s * 0.05, cy + s * 0.35, cx + s * 0.7, cy - s * 0.55],
                   color, width=max(2.0, s * 0.2))
        elif kind == "folder":
            p.polygon([
                cx - s, cy - s * 0.35, cx - s * 0.32, cy - s * 0.35, cx - s * 0.15, cy - s * 0.15,
                cx + s, cy - s * 0.15, cx + s, cy + s * 0.55, cx - s, cy + s * 0.55,
            ], color)
        elif kind == "undo":
            p.arc(cx - s * 0.8, cy - s * 0.75, cx + s * 0.8, cy + s * 0.75, 200, 250, color, width=w)
            p.polygon([cx - s * 0.9, cy - s * 0.1, cx - s * 0.32, cy - s * 0.52, cx - s * 0.42, cy + s * 0.08], color)
        elif kind == "warn":
            p.polygon([cx, cy - s, cx - s, cy + s * 0.7, cx + s, cy + s * 0.7], outline=color, width=w)
            p.line([cx, cy - s * 0.15, cx, cy + s * 0.28], color, width=w)
            p.oval(cx - 1.4, cy + s * 0.42, cx + 1.4, cy + s * 0.5, color)
        elif kind == "info":
            p.oval(cx - s * 0.85, cy - s * 0.85, cx + s * 0.85, cy + s * 0.85, outline=color, width=w)
            p.line([cx, cy - s * 0.05, cx, cy + s * 0.55], color, width=w)
            p.oval(cx - 1.2, cy - s * 0.55, cx + 1.2, cy - s * 0.3, color)
        elif kind == "check":
            p.line([cx - s * 0.7, cy, cx - s * 0.1, cy + s * 0.6, cx + s * 0.8, cy - s * 0.6], color,
                   width=max(2.0, s * 0.22))
        elif kind == "x":
            w2 = max(1.8, s * 0.2)
            p.line([cx - s * 0.6, cy - s * 0.6, cx + s * 0.6, cy + s * 0.6], color, width=w2)
            p.line([cx - s * 0.6, cy + s * 0.6, cx + s * 0.6, cy - s * 0.6], color, width=w2)
        elif kind == "refresh":
            p.arc(cx - s * 0.8, cy - s * 0.8, cx + s * 0.8, cy + s * 0.8, 30, 260, color, width=w)
            p.polygon([cx + s * 0.55, cy - s * 0.85, cx + s * 0.95, cy - s * 0.35, cx + s * 0.4, cy - s * 0.25],
                       color)
        elif kind == "spinner":
            start = (frame * 30) % 360
            p.arc(cx - s, cy - s, cx + s, cy + s, start, 110, color, width=w)
        elif kind == "box":
            p.rect(cx - s, cy - s * 0.55, cx + s, cy + s, outline=color, width=w, radius=s * 0.12)
            p.line([cx - s, cy - s * 0.05, cx + s, cy - s * 0.05], color, width=w)
            p.line([cx, cy - s * 0.55, cx, cy + s], color, width=w)

    _ICON_PHOTO_CACHE: dict = {}

    def render_icon_photo(kind, color, size=18, frame=0):
        if not _PIL_OK:
            return None
        key = (kind, color, size, frame)
        cached = _ICON_PHOTO_CACHE.get(key)
        if cached is not None:
            return cached
        big = size * 4
        img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        _paint_icon(_Painter(draw, pil=True), big / 2, big / 2, kind, color, big * 0.36, frame)
        photo = ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))
        _ICON_PHOTO_CACHE[key] = photo
        return photo

    def draw_icon(canvas, cx, cy, kind, color=TEXT, s=7, frame=0):
        _paint_icon(_Painter(canvas, pil=False), cx, cy, kind, color, s, frame)

    def blit_icon(canvas, cx, cy, kind, color=TEXT, size=18, frame=0):
        photo = render_icon_photo(kind, color, size, frame)
        if photo is not None:
            canvas.create_image(cx, cy, image=photo)
        else:
            draw_icon(canvas, cx, cy, kind, color=color, s=size * 0.42, frame=frame)

    def icon_canvas(parent, kind, color=TEXT, size=18, bg=None):
        c = tk.Canvas(parent, width=size, height=size, highlightthickness=0, bd=0, bg=bg or parent["bg"])
        blit_icon(c, size / 2, size / 2, kind, color=color, size=size)
        return c

    # ------------------------------------------------------------------
    # Rounded-corner widgets
    # ------------------------------------------------------------------

    def _rounded_points(x1, y1, x2, y2, r):
        r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
        return [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]

    def draw_round_rect(canvas, x1, y1, x2, y2, r=16, **kwargs):
        return canvas.create_polygon(_rounded_points(x1, y1, x2, y2, r), smooth=True, **kwargs)

    def autowrap_label(parent, text, fg=TEXT_MUTED, bg=None, font=("Sans", 9), justify="left"):
        lbl = tk.Label(parent, text=text, fg=fg, bg=bg or parent["bg"], font=font, justify=justify, anchor="w")

        def _resize(event):
            new_wrap = max(60, event.width - 4)
            if lbl.cget("wraplength") != new_wrap:
                lbl.configure(wraplength=new_wrap)

        lbl.bind("<Configure>", _resize)
        return lbl

    def flatten_entry(entry, bg=CARD_BG):
        try:
            entry.configure(highlightthickness=0, highlightbackground=bg, highlightcolor=bg)
        except tk.TclError:
            pass

    def rating_widget(parent, quality, speed, bg=CARD_BG):
        row = tk.Frame(parent, bg=bg)

        def dots(container, score):
            for i in range(5):
                c = tk.Canvas(container, width=10, height=10, highlightthickness=0, bd=0, bg=bg)
                c.pack(side="left", padx=1)
                color = ACCENT if i < score else CARD_BORDER
                c.create_oval(1, 1, 9, 9, fill=color, outline="")

        tk.Label(row, text="Quality", bg=bg, fg=TEXT_MUTED, font=("Sans", 9)).pack(side="left", padx=(0, 4))
        qf = tk.Frame(row, bg=bg)
        qf.pack(side="left", padx=(0, 16))
        dots(qf, quality)
        tk.Label(row, text="Speed", bg=bg, fg=TEXT_MUTED, font=("Sans", 9)).pack(side="left", padx=(0, 4))
        sf = tk.Frame(row, bg=bg)
        sf.pack(side="left")
        dots(sf, speed)
        return row

    class RoundedButton(tk.Canvas):
        _PALETTE = {
            "primary": (ACCENT, ACCENT_HOVER, ACCENT_TEXT),
            "success": (SUCCESS, SUCCESS_HOVER, "#08210f"),
            "danger": (DANGER, DANGER_HOVER, "#2b0b0c"),
            "secondary": (CARD_BORDER, "#3f424a", TEXT),
        }

        def __init__(self, parent, text, command=None, variant="secondary", icon=None,
                     width=None, height=34, radius=13, font=("Sans", 10, "bold"), bg=None, on_blocked=None):
            super().__init__(parent, height=height, width=width or 1, highlightthickness=0, bd=0,
                              bg=bg or parent["bg"])
            self.command = command
            self.on_blocked = on_blocked
            self.variant = variant
            self.icon = icon
            self.radius = radius
            self.text = text
            self.font = font
            self._enabled = True
            self._hover = False
            self._fixed_width = width
            self._loading = False
            self._loading_base = ""
            self._loading_frame = 0
            self.bind("<Configure>", lambda e: self._draw())
            self.bind("<Enter>", lambda e: self._set_hover(True))
            self.bind("<Leave>", lambda e: self._set_hover(False))
            self.bind("<Button-1>", self._on_click)

        def _set_hover(self, hover):
            if self._enabled:
                self._hover = hover
                self._draw()
                self.configure(cursor="hand2" if hover else "")

        def _on_click(self, _event=None):
            if self._enabled:
                if self.command:
                    self.command()
            elif self.on_blocked:
                self.on_blocked()

        def set_enabled(self, enabled: bool):
            self._enabled = enabled
            self._hover = False
            self._draw()

        def set_text(self, text: str):
            self.text = text
            self._draw()

        def set_variant(self, variant: str):
            self.variant = variant
            self._draw()

        def start_loading(self, base_text="Working"):
            if self._loading:
                return
            self._loading = True
            self._loading_base = base_text
            self._loading_frame = 0
            self._enabled = False
            self._animate()

        def stop_loading(self):
            self._loading = False

        def _animate(self):
            if not self._loading or not self.winfo_exists():
                return
            self._loading_frame += 1
            self._draw()
            self.after(100, self._animate)

        def _draw(self):
            self.delete("all")
            w = max(self.winfo_width(), self._fixed_width or 1, 10)
            h = int(self["height"])
            base_fill, hover_fill, fg = self._PALETTE[self.variant]
            if not self._enabled and not self._loading:
                fill, fg = DISABLED_BG, DISABLED_TEXT
            elif self._loading:
                fill = base_fill
            elif self._hover:
                fill = hover_fill
            else:
                fill = base_fill
            draw_round_rect(self, 1, 1, w - 1, h - 1, self.radius, fill=fill, outline="")
            if self._loading:
                blit_icon(self, 22, h / 2, "spinner", color=fg, size=16, frame=self._loading_frame % 12)
                self.create_text(38, h / 2, text=self._loading_base + "…", fill=fg, font=self.font, anchor="w")
            elif self.icon:
                blit_icon(self, 22, h / 2, self.icon, color=fg, size=17)
                self.create_text(38, h / 2, text=self.text, fill=fg, font=self.font, anchor="w")
            else:
                self.create_text(w / 2, h / 2, text=self.text, fill=fg, font=self.font, anchor="center")

    class RoundedCard(tk.Frame):
        def __init__(self, parent, bg=CARD_BG, border=CARD_BORDER, radius=18, pad=18, width=None, height=None):
            super().__init__(parent, bg=parent["bg"])
            self._bg, self._border, self._radius, self._pad = bg, border, radius, pad
            self._fixed_height = height
            self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=parent["bg"])
            if width:
                self.canvas.configure(width=width)
            if height:
                self.canvas.configure(height=height)
            self.canvas.pack(fill="both", expand=True)
            self.body = tk.Frame(self.canvas, bg=bg)
            self._win = self.canvas.create_window(pad, pad, window=self.body, anchor="nw")
            self._last_h = None
            self.canvas.bind("<Configure>", self._on_canvas_configure)
            self.body.bind("<Configure>", self._on_body_configure)

        def _on_canvas_configure(self, event=None):
            w = self.canvas.winfo_width()
            opts = {"width": max(0, w - 2 * self._pad)}
            if self._fixed_height:
                opts["height"] = max(0, self._fixed_height - 2 * self._pad)
            self.canvas.itemconfig(self._win, **opts)
            self._redraw(w, self.canvas.winfo_height())

        def _on_body_configure(self, event=None):
            if self._fixed_height:
                h = self._fixed_height
            else:
                h = self.body.winfo_reqheight() + 2 * self._pad
                if h != self._last_h:
                    self._last_h = h
                    self.canvas.configure(height=h)
            self._redraw(self.canvas.winfo_width(), h)

        def _redraw(self, w, h):
            self.canvas.delete("card_bg")
            if w > 4 and h > 4:
                draw_round_rect(self.canvas, 1, 1, w - 1, h - 1, self._radius,
                                 fill=self._bg, outline=self._border, width=1, tags="card_bg")
                self.canvas.tag_lower("card_bg")

        def finalize(self):
            self.update_idletasks()
            self._on_body_configure()
            self._on_canvas_configure()

    class ProgressBar(tk.Canvas):
        def __init__(self, parent, width=200, height=7, bg=None, track=CARD_BORDER, fill=ACCENT):
            super().__init__(parent, width=width, height=height, highlightthickness=0, bd=0, bg=bg or parent["bg"])
            self._frac = 0.0
            self._track, self._fillc = track, fill
            self.bind("<Configure>", lambda e: self._draw())

        def set_fraction(self, frac: float):
            self._frac = max(0.0, min(1.0, frac))
            self._draw()

        def _draw(self):
            self.delete("all")
            w = self.winfo_width() or int(self["width"])
            h = int(self["height"])
            draw_round_rect(self, 0, 0, w, h, h / 2, fill=self._track, outline="")
            fw = w * self._frac
            if fw >= h:
                draw_round_rect(self, 0, 0, fw, h, h / 2, fill=self._fillc, outline="")

    class ModernCheckbox(tk.Canvas):
        def __init__(self, parent, variable, command=None, size=20, bg=None):
            super().__init__(parent, width=size, height=size, highlightthickness=0, bd=0, bg=bg or parent["bg"])
            self.variable = variable
            self.command = command
            self.size = size
            self._trace_id = variable.trace_add("write", lambda *_a: self._draw())
            self.bind("<Configure>", lambda e: self._draw())
            self.bind("<Button-1>", self._toggle)
            self.bind("<Enter>", lambda e: self.configure(cursor="hand2"))
            self.bind("<Destroy>", self._on_destroy)
            self._draw()

        def _toggle(self, _event=None):
            self.variable.set(not self.variable.get())
            if self.command:
                self.command()

        def _on_destroy(self, _event=None):
            try:
                self.variable.trace_remove("write", self._trace_id)
            except Exception:
                pass

        def _draw(self):
            if not self.winfo_exists():
                return
            self.delete("all")
            s = self.size
            if self.variable.get():
                draw_round_rect(self, 1, 1, s - 1, s - 1, 6, fill=ACCENT, outline="")
                blit_icon(self, s / 2, s / 2, "check", color=ACCENT_TEXT, size=max(10, int(s * 0.75)))
            else:
                draw_round_rect(self, 1.5, 1.5, s - 1.5, s - 1.5, 6, fill="", outline=CARD_BORDER, width=2)

    def bind_click_recursive(widget, handler, skip=()):
        if widget in skip:
            return
        try:
            widget.configure(cursor="hand2")
        except tk.TclError:
            pass
        widget.bind("<Button-1>", lambda e: handler())
        for child in widget.winfo_children():
            bind_click_recursive(child, handler, skip)

    class ScrollableFrame(tk.Frame):
        def __init__(self, parent, bg=BG):
            super().__init__(parent, bg=bg)
            self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
            vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="Modern.Vertical.TScrollbar")
            self.inner = tk.Frame(self.canvas, bg=bg)
            self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
            self.canvas.configure(yscrollcommand=vsb.set)
            self.canvas.pack(side="left", fill="both", expand=True)
            vsb.pack(side="right", fill="y", padx=(4, 0))
            self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
            self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self._win, width=e.width))
            self._wheel_bound_ids: set = set()
            self.bind_mousewheel_recursive()

        def bind_mousewheel_recursive(self, widget=None):
            widget = widget or self.inner
            if id(widget) not in self._wheel_bound_ids:
                widget.bind("<MouseWheel>", self._on_wheel, add="+")
                widget.bind("<Button-4>", self._on_up, add="+")
                widget.bind("<Button-5>", self._on_down, add="+")
                self._wheel_bound_ids.add(id(widget))
            for child in widget.winfo_children():
                self.bind_mousewheel_recursive(child)

        def _on_wheel(self, event):
            if self.canvas.winfo_exists():
                self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

        def _on_up(self, event):
            if self.canvas.winfo_exists():
                self.canvas.yview_scroll(-2, "units")

        def _on_down(self, event):
            if self.canvas.winfo_exists():
                self.canvas.yview_scroll(2, "units")

    def page_header(parent, title):
        tk.Label(parent, text=title, bg=BG, fg=TEXT, font=("Sans", 18, "bold")).pack(anchor="w", pady=(0, 16))

    def callout(parent, text, tone="info"):
        colors = {"info": ("#16303a", "#7fd0f0"), "warn": ("#3a2e14", WARNING), "ok": ("#123522", SUCCESS)}
        icon_kind = {"info": "info", "warn": "warn", "ok": "check"}[tone]
        bgc, fg = colors[tone]
        card = RoundedCard(parent, bg=bgc, border=bgc, radius=14, pad=12)
        card.pack(fill="x", pady=(4, 12))
        row = tk.Frame(card.body, bg=bgc)
        row.pack(fill="x")
        icon_canvas(row, icon_kind, color=fg, size=18, bg=bgc).pack(side="left", padx=(0, 8), anchor="n")
        autowrap_label(row, text, fg=fg, bg=bgc, font=("Sans", 9)).pack(side="left", fill="x", expand=True)
        card.finalize()
        return card

    def themed_dialog(root, title, message, kind="info"):
        win = tk.Toplevel(root)
        win.configure(bg=BG)
        win.title(title)
        win.transient(root)
        win.resizable(False, False)
        card = RoundedCard(win, radius=18, pad=20, width=380)
        card.pack(padx=2, pady=2)
        tk.Label(card.body, text=title, bg=CARD_BG, fg=TEXT, font=("Sans", 13, "bold")).pack(anchor="w")
        autowrap_label(card.body, message, fg=TEXT_MUTED, bg=CARD_BG, font=("Sans", 10)).pack(
            anchor="w", fill="x", pady=(10, 18))
        result = {"value": None}
        btns = tk.Frame(card.body, bg=CARD_BG)
        btns.pack(anchor="e")

        def close(v):
            result["value"] = v
            win.destroy()

        if kind == "confirm":
            RoundedButton(btns, "Cancel", variant="secondary", width=90, command=lambda: close(False)).pack(
                side="left", padx=(0, 8))
            RoundedButton(btns, "Confirm", variant="danger", icon="trash", width=120,
                          command=lambda: close(True)).pack(side="left")
        else:
            RoundedButton(btns, "OK", variant="primary", width=90, command=lambda: close(True)).pack(side="left")
        card.finalize()
        win.update_idletasks()
        rx, ry, rw, rh = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{rx + max(0, (rw - ww) // 2)}+{ry + max(0, (rh - wh) // 2)}")
        win.grab_set()
        win.wait_window()
        return result["value"]

    def themed_info(root, title, message):
        themed_dialog(root, title, message, kind="info")

    def themed_confirm(root, title, message) -> bool:
        return bool(themed_dialog(root, title, message, kind="confirm"))

    def show_snackbar(app, message: str, tone: str = "warn", duration_ms: int = 2200):
        colors = {"warn": ("#3a2e14", WARNING), "error": ("#3a1414", DANGER), "ok": ("#123522", SUCCESS)}
        bgc, fg = colors.get(tone, colors["warn"])
        root = app.root
        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=root["bg"])
        card = RoundedCard(win, bg=bgc, border=bgc, radius=14, pad=14)
        card.pack()
        row = tk.Frame(card.body, bg=bgc)
        row.pack()
        icon_canvas(row, "warn" if tone == "warn" else ("x" if tone == "error" else "check"), color=fg, size=16,
                    bg=bgc).pack(side="left", padx=(0, 8))
        tk.Label(row, text=message, bg=bgc, fg=fg, font=("Sans", 10, "bold")).pack(side="left")
        card.finalize()
        win.update_idletasks()
        x = root.winfo_rootx() + max(0, (root.winfo_width() - win.winfo_reqwidth()) // 2)
        y = root.winfo_rooty() + root.winfo_height() - 110
        win.geometry(f"+{x}+{y}")
        win.after(duration_ms, lambda: win.destroy() if win.winfo_exists() else None)

    # ------------------------------------------------------------------
    # SAM model download queue — one model downloads at a time, everything
    # else Install-clicked while that's running just joins the queue.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # GUI password prompt for the package-manager (sudo) install path.
    # ------------------------------------------------------------------

    class TkPasswordPrompt:
        def __init__(self, root):
            self.root = root

        def __call__(self, prompt_text: str) -> str:
            result: dict = {}
            done = threading.Event()

            def ask():
                result["pw"] = simpledialog.askstring(
                    "Password required",
                    f"{prompt_text}\n\n(needed to install/remove system packages; this is your normal "
                    "login password, sent straight to sudo, never stored)",
                    show="*", parent=self.root,
                )
                done.set()

            self.root.after(0, ask)
            done.wait()
            return result.get("pw") or ""

    # ------------------------------------------------------------------
    # What's on this system, in the uninstall screen's vocabulary.
    # ------------------------------------------------------------------

    def detect_targets() -> list[tuple[str, str, str]]:
        targets = []
        distro = detect_distro()
        if gimp_native_installed():
            targets.append(("package-manager", "Native GIMP (+ G'MIC) packages", f"installed via {distro}"))
        if appimage_present():
            targets.append(("appimage", "GIMP AppImage", APPIMAGE_DIR))
        if photogimp_installed():
            targets.append(("photogimp", "PhotoGIMP configuration layer",
                             "icons, desktop entry, shortcuts, splash screen, UI layout"))
        if batcher_installed():
            targets.append(("batcher", "Batcher plug-in", "plug-ins/batcher — only this folder"))
        if segany_plugin_installed() or os.path.isdir(BACKEND_DIR):
            targets.append(("sam", "SAM plug-in + Python backend + models",
                             f"plug-ins/seganyplugin and {BACKEND_DIR} — only these"))
        return targets

    def anything_installed() -> bool:
        return bool(detect_targets())

    # ------------------------------------------------------------------
    # The app itself. One landing screen (Quick setup / Manage / Uninstall),
    # a paginated setup wizard (GIMP > PhotoGIMP > G'MIC > SAM > Batcher >
    # Review) that only ever *queues* actions into an InstallPlan, and one
    # shared install-progress screen that actually runs a plan — whether it
    # came from the wizard's Review page or from Quick Setup's own prefilled
    # plan. Every wizard page is fully self-contained and re-reads live
    # filesystem state on every render, exactly so "I already have GIMP, I just
    # want to add G'MIC" (or Batcher, or SAM) is a single click.
    # ------------------------------------------------------------------

    class LazyGimpApp:
        def __init__(self, root):
            self.root = root
            root.title("LazyGimp installer")
            root.geometry("1040x800")
            root.minsize(920, 660)
            root.configure(bg=BG)
            self._style()

            self.log_queue: "queue.Queue[str]" = queue.Queue()
            self.busy = False
            self.current_job = None
            self.current_screen = "landing"
            self.hw = detect_hardware()
            self.password_prompt = TkPasswordPrompt(root)

            # Wizard/plan state — (re)initialized fresh by show_wizard()/
            # show_install_progress() each time either screen is entered.
            self.plan = InstallPlan()
            self.wizard_steps: list[WizardStep] = []
            self.wizard_index = 0
            self.plan_actions: list[PlannedAction] = []
            self._exec_log_lines: list[str] = []

            self.root_frame = tk.Frame(root, bg=BG)
            self.root_frame.pack(fill="both", expand=True)
            self.show_landing()
            self.root.after(150, self._drain_log_queue)

        # ---- generic Tk plumbing (theme, status bar, background jobs) ----

        def _style(self):
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass
            style.configure("TEntry", fieldbackground="#303237", foreground=TEXT, insertcolor=TEXT,
                             bordercolor="#303237", lightcolor="#303237", darkcolor="#303237",
                             borderwidth=0, relief="flat", padding=6)
            style.configure("TCombobox", fieldbackground="#303237", background="#303237", foreground=TEXT,
                             arrowcolor=TEXT, bordercolor="#303237", lightcolor="#303237", darkcolor="#303237",
                             borderwidth=0, relief="flat", padding=6)
            style.map("TCombobox", fieldbackground=[("readonly", "#303237")], foreground=[("readonly", TEXT)],
                      background=[("readonly", "#303237")])
            style.layout("Modern.Vertical.TScrollbar", [
                ("Vertical.Scrollbar.trough", {"children": [
                    ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"}),
                ], "sticky": "ns"}),
            ])
            style.configure("Modern.Vertical.TScrollbar", gripcount=0, background="#4a4d54",
                             troughcolor=BG, bordercolor=BG, lightcolor="#4a4d54", darkcolor="#4a4d54",
                             relief="flat", width=8, arrowsize=0)
            style.configure("TSeparator", background=CARD_BORDER)
            self.root.option_add("*TCombobox*Listbox.background", "#303237")
            self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
            self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
            self.root.option_add("*TCombobox*Listbox.selectForeground", ACCENT_TEXT)

        def _build_status_bar(self, parent):
            bar = tk.Frame(parent, bg=BG)
            bar.pack(fill="x", padx=26, pady=(0, 14), side="bottom")
            self.status_spinner = tk.Canvas(bar, width=16, height=16, highlightthickness=0, bd=0, bg=BG)
            self.status_spinner.pack(side="left", padx=(0, 8))
            self.status_var = tk.StringVar(value="Full log is also printed to the terminal this was launched from.")
            tk.Label(bar, textvariable=self.status_var, bg=BG, fg=TEXT_MUTED, font=("Sans", 9), anchor="w").pack(
                side="left", fill="x", expand=True)
            self._status_spin_frame = 0
            self._status_spinning = False

        def _spin_status(self):
            if not self._status_spinning or not self.status_spinner.winfo_exists():
                return
            self.status_spinner.delete("all")
            blit_icon(self.status_spinner, 8, 8, "spinner", color=ACCENT, size=14, frame=self._status_spin_frame % 12)
            self._status_spin_frame += 1
            self.root.after(90, self._spin_status)

        _STATUS_MAX_CHARS = 160

        def _drain_log_queue(self):
            msgs = []
            try:
                while True:
                    msgs.append(self.log_queue.get_nowait())
            except queue.Empty:
                pass
            if msgs:
                last = msgs[-1]
                if hasattr(self, "status_var") and self.status_var is not None:
                    clean = " ".join(last.replace("\r", " ").split())
                    if len(clean) > self._STATUS_MAX_CHARS:
                        clean = "…" + clean[-(self._STATUS_MAX_CHARS - 1):]
                    try:
                        self.status_var.set(clean)
                    except tk.TclError:
                        pass
                if self.current_screen == "installing":
                    self._exec_log_lines.extend(msgs)
                    del self._exec_log_lines[:-500]
                    for m in msgs:
                        self._append_exec_log(m)
            self.root.after(150, self._drain_log_queue)

        def set_busy(self, busy: bool):
            self.busy = busy
            if not hasattr(self, "status_spinner") or not self.status_spinner.winfo_exists():
                return
            self._status_spinning = busy
            if busy:
                self._spin_status()
            else:
                self.status_spinner.delete("all")

        def run_in_background(self, fn, on_done=None):
            if self.busy:
                themed_info(self.root, "Busy", "Another operation is already running.")
                return
            self.set_busy(True)
            job = Job(self.log_queue, password_prompt=self.password_prompt)
            self.current_job = job

            def wrapper():
                try:
                    fn(job)
                except Exception as e:
                    job.log(f"ERROR: {e}")
                finally:
                    if self.current_job is job:
                        self.current_job = None
                    self.root.after(0, lambda: (self.set_busy(False), (on_done() if on_done else None)))

            threading.Thread(target=wrapper, daemon=True).start()

        def cancel_current_job(self):
            if self.current_job is not None:
                self.current_job.log("Cancel requested by user — stopping...")
                self.current_job.cancel()

        # ---- landing screen -----------------------------------------------

        def show_landing(self):
            self.current_screen = "landing"
            for w in self.root_frame.winfo_children():
                w.destroy()

            wrap = tk.Frame(self.root_frame, bg=BG)
            wrap.pack(fill="both", expand=True)
            center = tk.Frame(wrap, bg=BG)
            center.place(relx=0.5, rely=0.4, anchor="center")

            tk.Label(center, text="LazyGimp", bg=BG, fg=TEXT, font=("Sans", 28, "bold")).pack()
            tk.Label(center, text="GIMP + PhotoGIMP + G'MIC + SAM + Batcher, ready to use",
                     bg=BG, fg=TEXT_MUTED, font=("Sans", 11)).pack(pady=(2, 10))
            distro = detect_distro()
            method_note = f"Recommended for this system: {'package manager (' + distro + ')' if distro else 'AppImage'}"
            tk.Label(center, text=method_note, bg=BG, fg=TEXT_MUTED, font=("Sans", 9)).pack(pady=(0, 24))

            row = tk.Frame(center, bg=BG)
            row.pack()
            CARD_W, CARD_H = 320, 255

            manage = RoundedCard(row, radius=20, pad=24, width=CARD_W, height=CARD_H)
            manage.grid(row=0, column=0, padx=10)
            title_row = tk.Frame(manage.body, bg=CARD_BG)
            title_row.pack(anchor="w")
            icon_canvas(title_row, "gear", color=TEXT, size=20).pack(side="left", padx=(0, 8))
            tk.Label(title_row, text="Manage components", bg=CARD_BG, fg=TEXT, font=("Sans", 14, "bold")).pack(
                side="left")
            autowrap_label(
                manage.body,
                "Walk through PhotoGIMP, G'MIC, SAM and Batcher one page at a time, queue exactly what you "
                "want installed or removed, then run the whole checklist in one pass.",
                bg=CARD_BG, font=("Sans", 9),
            ).pack(anchor="w", fill="x", pady=(8, 16))
            open_btn = RoundedButton(manage.body, "Open", variant="secondary", width=272, height=40,
                                      command=self.show_wizard)
            open_btn.pack(anchor="w", side="bottom")
            manage.finalize()
            bind_click_recursive(manage, self.show_wizard, skip=(open_btn,))

            auto = RoundedCard(row, radius=20, pad=24, width=CARD_W, height=CARD_H)
            auto.grid(row=0, column=1, padx=10)
            title_row2 = tk.Frame(auto.body, bg=CARD_BG)
            title_row2.pack(anchor="w")
            icon_canvas(title_row2, "bolt", color=TEXT, size=20).pack(side="left", padx=(0, 8))
            tk.Label(title_row2, text="Quick setup", bg=CARD_BG, fg=TEXT, font=("Sans", 14, "bold")).pack(side="left")
            autowrap_label(
                auto.body,
                "Installs everything still missing, in order: PhotoGIMP, G'MIC, SAM (with a model picked "
                "for your hardware) and Batcher. Already-installed pieces are left alone.",
                bg=CARD_BG, font=("Sans", 9),
            ).pack(anchor="w", fill="x", pady=(8, 16))
            start_btn = RoundedButton(auto.body, "Start", variant="primary", width=272, height=40,
                                       command=self.start_quick_setup)
            start_btn.pack(anchor="w", side="bottom")
            auto.finalize()
            bind_click_recursive(auto, self.start_quick_setup, skip=(start_btn,))

            if anything_installed():
                btn_row = tk.Frame(center, bg=BG)
                btn_row.pack(pady=(18, 0))
                if find_gimp_command():
                    RoundedButton(btn_row, "Close installer and open GIMP", variant="primary", icon="bolt", width=340,
                                  command=self.launch_gimp_and_close).pack(pady=(0, 10))
                RoundedButton(btn_row, "Uninstall from this system", variant="danger", icon="trash", width=340,
                              command=self.show_uninstall_confirm).pack()

        def launch_gimp_and_close(self):
            cmd = find_gimp_command()
            if not cmd:
                show_snackbar(self, "GIMP not found", tone="error")
                return
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            except Exception as e:
                show_snackbar(self, f"Couldn't launch GIMP: {e}", tone="error")
                return
            self.root.destroy()

        # ---- quick setup: everything missing, in priority order -----------

        def start_quick_setup(self):
            if self.busy:
                themed_info(self.root, "Busy", "Setup is already running.")
                return
            # One-click setup is just a prefilled plan handed straight to the
            # same executor the wizard's Review page uses — no separate code
            # path, no separate "what to install" logic to keep in sync.
            self.show_install_progress(self._build_quick_setup_plan())

        def _build_quick_setup_plan(self) -> list["PlannedAction"]:
            actions: list[PlannedAction] = []

            if not find_gimp_binary() and not appimage_present():
                if detect_distro():
                    actions.append(PlannedAction(
                        "gimp:install", "Install GIMP (package manager)", "install",
                        lambda job: install_gimp_package_manager(job, include_gmic=False)))
                else:
                    actions.append(PlannedAction(
                        "gimp:install", "Install GIMP (AppImage)", "install",
                        lambda job: install_gimp_appimage(job)))

            if not photogimp_installed():
                actions.append(PlannedAction(
                    "photogimp:install", "Install PhotoGIMP", "install",
                    lambda job: install_photogimp(job, gimp_command=(find_gimp_command() or [None])[0])))

            if gmic_available_on_this_release() and not gmic_installed():
                actions.append(PlannedAction("gmic:install", "Install G'MIC", "install",
                                              lambda job: install_gmic_only(job)))

            if not segany_plugin_installed():
                actions.append(PlannedAction("sam_plugin:install", "Install the SAM plug-in", "install",
                                              lambda job: install_segany_plugin(job)))

            if not backend_ready():
                actions.append(PlannedAction(
                    "sam_backend:install", "Set up the SAM Python backend", "install",
                    lambda job: install_sam_backend(job, recommended_torch_index(self.hw))))

            if not any_model_installed():
                rec = MODEL_BY_KEY[recommended_model_key(self.hw)]

                def install_recommended(job: Job, rec=rec):
                    if job.download(rec.url, model_path(rec), job.cancel_event):
                        write_segany_plugin_settings(rec)
                        write_sam_info([rec.key])
                        bridge_self_test(job, rec)

                actions.append(PlannedAction(f"sam_model:{rec.key}:install",
                                              f"Download the recommended SAM model: {rec.label}",
                                              "install", install_recommended))

            if not batcher_installed():
                actions.append(PlannedAction("batcher:install", "Install Batcher", "install",
                                              lambda job: install_batcher(job)))

            return actions

        # ---- uninstall screen ----------------------------------------------

        def show_uninstall_confirm(self):
            self.current_screen = "uninstall"
            for w in self.root_frame.winfo_children():
                w.destroy()

            wrap = tk.Frame(self.root_frame, bg=BG)
            wrap.pack(fill="both", expand=True)
            self._build_status_bar(wrap)

            content = tk.Frame(wrap, bg=BG)
            content.pack(fill="both", expand=True, padx=40, pady=30)

            title_row = tk.Frame(content, bg=BG)
            title_row.pack(anchor="w")
            icon_canvas(title_row, "trash", color=DANGER, size=24).pack(side="left", padx=(0, 10))
            tk.Label(title_row, text="Uninstall LazyGimp", bg=BG, fg=TEXT, font=("Sans", 20, "bold")).pack(side="left")
            tk.Label(content, text="Choose what to remove. Personal GIMP files (brushes, scripts, settings not "
                                    "shipped by PhotoGIMP) are never touched — only what LazyGimp itself installed.",
                     bg=BG, fg=TEXT_MUTED, font=("Sans", 10), wraplength=760, justify="left").pack(anchor="w",
                                                                                                     pady=(4, 18))

            targets = detect_targets()
            btns = tk.Frame(content, bg=BG)
            btns.pack(fill="x", pady=(20, 0), side="bottom")

            card = RoundedCard(content)
            card.pack(fill="both", expand=True)
            check_vars: list[tuple] = []
            if targets:
                for key, name, detail in targets:
                    row = tk.Frame(card.body, bg=CARD_BG)
                    row.pack(fill="x", pady=7, anchor="w")
                    var = tk.BooleanVar(value=True)
                    ModernCheckbox(row, var, command=lambda: update_confirm_label(), bg=CARD_BG).pack(
                        side="left", padx=(0, 10))
                    icon_canvas(row, "trash", color=DANGER, size=18, bg=CARD_BG).pack(side="left", padx=(0, 10))
                    col = tk.Frame(row, bg=CARD_BG)
                    col.pack(side="left", fill="x", expand=True)
                    tk.Label(col, text=name, bg=CARD_BG, fg=TEXT, font=("Sans", 10, "bold"), anchor="w").pack(
                        anchor="w")
                    autowrap_label(col, detail, fg=TEXT_MUTED, bg=CARD_BG, font=("Sans", 9)).pack(anchor="w",
                                                                                                    fill="x")
                    check_vars.append((var, key))
            else:
                tk.Label(card.body, text="Nothing found to remove.", bg=CARD_BG, fg=TEXT_MUTED).pack(anchor="w")
            card.finalize()

            RoundedButton(btns, "Cancel", variant="secondary", width=110, command=self.show_landing).pack(
                side="left")
            confirm_btn = RoundedButton(btns, "Delete selected", variant="danger", icon="trash", width=200,
                                         command=lambda: self.on_confirm_uninstall(
                                             [k for v, k in check_vars if v.get()]))
            confirm_btn.pack(side="left", padx=8)
            RoundedButton(btns, "Delete all", variant="danger", icon="trash", width=140,
                          command=lambda: self.on_confirm_uninstall([k for _, k in check_vars])).pack(side="left")

            def update_confirm_label():
                n = sum(1 for v, _ in check_vars if v.get())
                confirm_btn.set_text(f"Delete selected ({n})")
                confirm_btn.set_enabled(n > 0)

            update_confirm_label()

        def on_confirm_uninstall(self, keys: list[str]):
            if not keys:
                return
            needs_root = "package-manager" in keys

            def task(job: Job):
                if "photogimp" in keys:
                    remove_photogimp(job)
                if "batcher" in keys:
                    remove_batcher(job)
                if "sam" in keys:
                    remove_segany_plugin(job)
                    remove_sam_backend(job)
                if "appimage" in keys:
                    remove_gimp_appimage(job)
                if "package-manager" in keys:
                    if needs_root:
                        job.log("Removing native packages needs administrator rights — "
                                "a password prompt may appear below.")
                    remove_gimp_package_manager(job)
                job.log("Uninstall finished.")

            self.run_in_background(task, on_done=self.show_landing)

        # ---- manage screen: one card per component, priority order ---------
        # PhotoGIMP > G'MIC > SAM > Batcher, with GIMP itself as the one
        # prerequisite card ahead of all four (per the user's own ordering).

        # ---- paginated setup wizard -----------------------------------------
        # Every page only ever queues PlannedActions into self.plan; nothing
        # here touches disk. The wizard is entered fresh every time (own
        # plan, own step list) so reopening it always reflects current
        # reality — an already-installed component simply renders with
        # Install disabled and Uninstall enabled instead of vanishing.

        _WIZARD_RENDERERS = {
            "gimp": "_wizard_render_gimp",
            "photogimp": "_wizard_render_photogimp",
            "gmic": "_wizard_render_gmic",
            "sam": "_wizard_render_sam",
            "batcher": "_wizard_render_batcher",
            "review": "_wizard_render_review",
        }

        def show_wizard(self):
            self.plan = InstallPlan()
            default_choice = list(TORCH_INDEX_URLS.keys())[
                list(TORCH_INDEX_URLS.values()).index(recommended_torch_index(self.hw))]
            self.torch_choice = tk.StringVar(value=default_choice)
            self.hf_token_var = tk.StringVar()
            self.wizard_steps = self._build_wizard_steps()
            self.wizard_index = 0
            self._render_wizard_step()

        def _build_wizard_steps(self) -> list[WizardStep]:
            steps = []
            if not (gimp_native_installed() or appimage_present()):
                steps.append(WizardStep("gimp", "GIMP (prerequisite)", prerequisite=True))
            steps.append(WizardStep("photogimp", "PhotoGIMP"))
            steps.append(WizardStep("gmic", "G'MIC"))
            steps.append(WizardStep("sam", "SAM (segmentation models)"))
            steps.append(WizardStep("batcher", "Batcher"))
            steps.append(WizardStep("review", "Review & install"))
            return steps

        def _wizard_can_advance(self) -> bool:
            step = self.wizard_steps[self.wizard_index]
            if step.key == "gimp":
                return self.plan.has("gimp_install_pm") or self.plan.has("gimp_install_appimage")
            return True

        def _wizard_advance(self):
            if not self._wizard_can_advance():
                return
            self.wizard_index += 1
            self._render_wizard_step()

        def _wizard_back(self):
            if self.wizard_index == 0:
                if len(self.plan) and not themed_confirm(
                        self.root, "Leave setup", "Discard your selections and go back to the start screen?"):
                    return
                self.show_landing()
                return
            self.wizard_index -= 1
            self._render_wizard_step()

        def _wizard_toggle_action(self, key: str, label: str, kind: str, run):
            self.plan.toggle(PlannedAction(key=key, label=label, kind=kind, run=run))
            self._render_wizard_step()

        def _render_wizard_step(self):
            self.current_screen = "wizard"
            for w in self.root_frame.winfo_children():
                w.destroy()
            step = self.wizard_steps[self.wizard_index]

            outer = tk.Frame(self.root_frame, bg=BG)
            outer.pack(fill="both", expand=True)

            top = tk.Frame(outer, bg=BG)
            top.pack(fill="x", padx=26, pady=(16, 0))
            tk.Label(top, text=step.title, bg=BG, fg=TEXT, font=("Sans", 16, "bold")).pack(side="left")
            tk.Label(top, text=f"Step {self.wizard_index + 1} of {len(self.wizard_steps)}", bg=BG,
                     fg=TEXT_MUTED, font=("Sans", 10)).pack(side="right")

            nav = tk.Frame(outer, bg=BG)
            nav.pack(fill="x", padx=26, pady=(10, 16), side="bottom")
            RoundedButton(nav, "← Back", variant="secondary", width=110, command=self._wizard_back).pack(
                side="left")
            if step.key != "review":
                next_btn = RoundedButton(nav, "Next →", variant="primary", width=140,
                                          command=self._wizard_advance)
                next_btn.pack(side="right")
                next_btn.set_enabled(self._wizard_can_advance())
                if not step.prerequisite:
                    RoundedButton(nav, "Skip →", variant="secondary", width=110,
                                  command=self._wizard_advance).pack(side="right", padx=(0, 8))

            scroller = ScrollableFrame(outer)
            scroller.pack(fill="both", expand=True, padx=26, pady=(6, 0))
            getattr(self, self._WIZARD_RENDERERS[step.key])(scroller.inner)
            scroller.bind_mousewheel_recursive()

        def _status_row(self, body, ok: bool, text: str):
            row = tk.Frame(body, bg=CARD_BG)
            row.pack(fill="x", pady=(0, 10))
            icon_canvas(row, "check" if ok else "x", color=SUCCESS if ok else TEXT_MUTED, size=16,
                        bg=CARD_BG).pack(side="left", padx=(0, 8))
            autowrap_label(row, text, fg=TEXT, bg=CARD_BG, font=("Sans", 10)).pack(side="left", fill="x",
                                                                                     expand=True)

        def _wizard_toggle_card(self, parent, *, key: str, installed: bool, status_text: str, install_label: str,
                                 install_run, uninstall_run, uninstall_label: str = "Remove",
                                 install_enabled: bool = True, extra=None):
            """One reusable card covering every simple component page
            (PhotoGIMP, G'MIC, the SAM plug-in, the SAM backend, Batcher):
            not installed -> a single toggle that queues/unqueues Install;
            installed -> Install disabled, Uninstall enabled and toggleable."""
            card = RoundedCard(parent)
            card.pack(fill="x", pady=(0, 10))
            body = card.body
            self._status_row(body, installed, status_text)
            if extra:
                extra(body)
            btn_row = tk.Frame(body, bg=CARD_BG)
            btn_row.pack(fill="x", pady=(6, 0))
            if installed:
                done_btn = RoundedButton(btn_row, "Installed", icon="check", variant="secondary", width=160)
                done_btn.pack(side="left", padx=(0, 8))
                done_btn.set_enabled(False)
                remove_key = f"{key}:remove"
                queued = self.plan.has(remove_key)
                remove_btn = RoundedButton(
                    btn_row, "Cancel removal" if queued else uninstall_label,
                    icon="undo" if queued else "trash", variant="secondary" if queued else "danger", width=200,
                    command=lambda: self._wizard_toggle_action(remove_key, f"Remove {install_label}", "remove",
                                                                uninstall_run))
                remove_btn.pack(side="left")
            else:
                install_key = f"{key}:install"
                queued = self.plan.has(install_key)
                install_btn = RoundedButton(
                    btn_row, "Queued ✓" if queued else install_label, icon="check" if queued else "install",
                    variant="secondary" if queued else "success", width=200,
                    command=lambda: self._wizard_toggle_action(install_key, install_label, "install", install_run))
                install_btn.pack(side="left", padx=(0, 8))
                install_btn.set_enabled(install_enabled or queued)
                no_remove = RoundedButton(btn_row, "Remove", icon="trash", variant="danger", width=130)
                no_remove.pack(side="left")
                no_remove.set_enabled(False)
            card.finalize()

        # -- GIMP (prerequisite; mandatory, exclusive choice of method) -------

        def _wizard_render_gimp(self, parent):
            native = gimp_native_installed()
            appimg = appimage_present()
            distro = detect_distro()
            card = RoundedCard(parent)
            card.pack(fill="x", pady=(0, 4))
            body = card.body
            self._status_row(body, native, f"Native package ({distro or 'no supported distro detected'})"
                                            + (" — installed" if native else " — not installed"))
            self._status_row(body, appimg, f"AppImage in {APPIMAGE_DIR}"
                                            + (" — installed" if appimg else " — not installed"))

            btn_row = tk.Frame(body, bg=CARD_BG)
            btn_row.pack(fill="x", pady=(6, 0))
            pm_selected = self.plan.has("gimp_install_pm")
            ai_selected = self.plan.has("gimp_install_appimage")
            pm_btn = RoundedButton(
                btn_row, "Queued ✓ — package manager" if pm_selected else "Install via package manager",
                icon="check" if pm_selected else "install", variant="secondary" if pm_selected else "success",
                width=270, command=lambda: self._wizard_pick_gimp_method("pm"))
            pm_btn.pack(side="left", padx=(0, 8))
            pm_btn.set_enabled(bool(distro))
            ai_btn = RoundedButton(
                btn_row, "Queued ✓ — AppImage" if ai_selected else "Install AppImage",
                icon="check" if ai_selected else "install", variant="secondary" if ai_selected else "success",
                width=210, command=lambda: self._wizard_pick_gimp_method("appimage"))
            ai_btn.pack(side="left")
            if not distro:
                callout(body, "No supported distribution detected (arch, debian, ubuntu, fedora, opensuse) — "
                               "use the AppImage instead.", "warn")
            callout(body, "GIMP is a prerequisite for everything else, so this page can't be skipped — "
                          "pick one of the two methods above to continue.", "info")
            card.finalize()

        def _wizard_pick_gimp_method(self, method: str):
            self.plan.discard("gimp_install_pm")
            self.plan.discard("gimp_install_appimage")
            if method == "pm":
                action = PlannedAction("gimp_install_pm", "Install GIMP (package manager)", "install",
                                        lambda job: install_gimp_package_manager(job, include_gmic=False))
            else:
                action = PlannedAction("gimp_install_appimage", "Install GIMP (AppImage)", "install",
                                        lambda job: install_gimp_appimage(job))
            self.plan.toggle(action)
            self._render_wizard_step()

        # -- PhotoGIMP ---------------------------------------------------------

        def _wizard_render_photogimp(self, parent):
            installed = photogimp_installed()

            def extra(body):
                autowrap_label(body, "Also fixes the taskbar/window icon showing a generic icon instead of "
                                      "PhotoGIMP's — every (re)install regenerates that desktop-file fix.",
                               fg=TEXT_MUTED, bg=CARD_BG, font=("Sans", 9)).pack(anchor="w", fill="x", pady=(0, 10))
                if installed:
                    RoundedButton(body, "Fix taskbar icon now", icon="refresh", variant="secondary", width=200,
                                  command=self._repair_photogimp_desktop).pack(anchor="w", pady=(0, 8))

            self._wizard_toggle_card(
                parent, key="photogimp", installed=installed,
                status_text="Icons, shortcuts, splash screen, UI layout"
                             + (" — installed" if installed else " — not installed"),
                install_label="Install PhotoGIMP",
                install_run=lambda job: install_photogimp(job, gimp_command=(find_gimp_command() or [None])[0]),
                uninstall_run=lambda job: remove_photogimp(job),
                extra=extra,
            )

        def _repair_photogimp_desktop(self):
            def task(job: Job):
                repair_desktop_integration(job)

            def done():
                self._render_wizard_step()
                show_snackbar(self, "Desktop entry fixed — restart GIMP and re-pin it", tone="ok")

            self.run_in_background(task, on_done=done)

        # -- G'MIC ---------------------------------------------------------------

        def _wizard_render_gmic(self, parent):
            installed = gmic_installed()
            available = gmic_available_on_this_release()

            def extra(body):
                if not available:
                    callout(body, f"No G'MIC package on this distribution release — see {GMIC_DOWNLOAD_PAGE} "
                                   "for a manual build.", "warn")

            self._wizard_toggle_card(
                parent, key="gmic", installed=installed,
                status_text="Extra filter collection for GIMP" + (" — installed" if installed else " — not installed"),
                install_label="Install G'MIC",
                install_run=lambda job: install_gmic_only(job),
                uninstall_run=lambda job: remove_gmic_only(job),
                install_enabled=available,
                extra=extra,
            )

        # -- SAM: plug-in + backend + models + SAM 3.1 ---------------------------

        def _wizard_render_sam(self, parent):
            self._wizard_toggle_card(
                parent, key="sam_plugin", installed=segany_plugin_installed(),
                status_text="Plug-in files" + (" — installed" if segany_plugin_installed() else " — not installed"),
                install_label="Install SAM plug-in",
                install_run=lambda job: install_segany_plugin(job),
                uninstall_run=lambda job: remove_segany_plugin(job),
            )

            ready = backend_ready()
            exists = venv_exists()

            def backend_extra(body):
                if ready:
                    callout(body, f"Ready at {VENV_DIR}", "ok")
                elif exists:
                    callout(body, "A virtualenv exists but PyTorch isn't importable — queuing Install backend "
                                   "again will repair it.", "warn")
                else:
                    callout(body, "Not set up yet.", "warn")
                tk.Label(body, text="PyTorch build", bg=CARD_BG, fg=TEXT, font=("Sans", 10, "bold")).pack(
                    anchor="w", pady=(8, 6))
                combo = ttk.Combobox(body, textvariable=self.torch_choice, values=list(TORCH_INDEX_URLS.keys()),
                                      state="readonly", width=34, font=("Sans", 10))
                combo.pack(anchor="w", pady=(0, 6))
                flatten_entry(combo)

            self._wizard_toggle_card(
                parent, key="sam_backend", installed=ready,
                status_text="Python backend (PyTorch venv)" + (" — ready" if ready else " — not ready"),
                install_label="Repair backend" if exists else "Install backend",
                install_run=lambda job: install_sam_backend(job, TORCH_INDEX_URLS[self.torch_choice.get()]),
                uninstall_run=lambda job: remove_sam_backend(job),
                uninstall_label="Remove backend (+ all models)",
                extra=backend_extra,
            )

            autowrap_label(
                parent,
                "Quality/Speed are rough 1-5 estimates, comparable within a family. Already-downloaded models "
                "are never a checkbox again — Remove just queues their deletion for the final install step.",
                fg=TEXT_MUTED, bg=BG, font=("Sans", 9),
            ).pack(anchor="w", fill="x", pady=(6, 10))
            rec_key = recommended_model_key(self.hw)
            for family in ("SAM1", "SAM2"):
                fam_card = RoundedCard(parent)
                fam_card.pack(fill="x", pady=(0, 10))
                head = tk.Frame(fam_card.body, bg=CARD_BG)
                head.pack(fill="x", pady=(0, 4))
                tk.Label(head, text=family, bg=CARD_BG, fg=ACCENT, font=("Sans", 11, "bold")).pack(side="left")
                RoundedButton(head, "Queue all missing", icon="install", variant="secondary", width=170,
                              command=lambda fam=family: self._wizard_queue_all_models(fam)).pack(side="right")
                for spec in [m for m in MODEL_REGISTRY if m.family == family]:
                    self._wizard_render_model_row(fam_card.body, spec, recommended=(spec.key == rec_key))
                fam_card.finalize()

            self._wizard_render_sam3(parent)

        @staticmethod
        def _sam_model_install_run(spec: ModelSpec):
            def run(job: Job):
                dest = model_path(spec)
                if os.path.isfile(dest):
                    job.log(f"{spec.label} already downloaded at {dest}")
                    return
                if job.download(spec.url, dest, job.cancel_event):
                    write_segany_plugin_settings(spec)
                    write_sam_info([spec.key])
            return run

        @staticmethod
        def _sam_model_remove_run(spec: ModelSpec):
            def run(job: Job):
                dest = model_path(spec)
                try:
                    if os.path.isdir(dest):
                        shutil.rmtree(dest)
                    elif os.path.isfile(dest):
                        os.remove(dest)
                    job.log(f"Removed {dest}")
                except Exception as e:
                    job.log(f"ERROR removing {dest}: {e}")
            return run

        def _wizard_render_model_row(self, parent, spec: ModelSpec, recommended: bool):
            row = RoundedCard(parent, pad=14, radius=16)
            row.pack(fill="x", pady=6)
            body = row.body
            top = tk.Frame(body, bg=CARD_BG)
            top.pack(fill="x")
            left = tk.Frame(top, bg=CARD_BG)
            left.pack(side="left", fill="x", expand=True)
            name_row = tk.Frame(left, bg=CARD_BG)
            name_row.pack(anchor="w")
            tk.Label(name_row, text=spec.label, bg=CARD_BG, fg=TEXT, font=("Sans", 12, "bold")).pack(side="left")
            tk.Label(name_row, text=f"   {spec.size}", bg=CARD_BG, fg=TEXT_MUTED, font=("Sans", 9)).pack(side="left")
            if recommended:
                tk.Label(name_row, text="  ★ Recommended", bg=CARD_BG, fg=ACCENT, font=("Sans", 9, "bold")).pack(
                    side="left")
            rating_widget(left, spec.quality, spec.speed, bg=CARD_BG).pack(anchor="w", pady=(4, 0))

            installed = model_installed(spec)
            install_key, remove_key = f"sam_model:{spec.key}:install", f"sam_model:{spec.key}:remove"
            queued_install = self.plan.has(install_key)
            queued_remove = self.plan.has(remove_key)
            status = ("Installed" if installed else
                      "Queued for install" if queued_install else
                      "Queued for removal" if queued_remove else "")
            if status:
                tk.Label(left, text=status, bg=CARD_BG, fg=(DANGER if queued_remove else SUCCESS),
                         font=("Sans", 9, "bold")).pack(anchor="w", pady=(4, 0))

            right = tk.Frame(top, bg=CARD_BG)
            right.pack(side="right")
            if installed:
                done_btn = RoundedButton(right, "Installed", icon="check", variant="secondary", width=140)
                done_btn.pack(side="left", padx=(0, 8))
                done_btn.set_enabled(False)
                remove_btn = RoundedButton(
                    right, "Cancel removal" if queued_remove else "Remove",
                    icon="undo" if queued_remove else "trash", variant="secondary" if queued_remove else "danger",
                    width=160, command=lambda: self._wizard_toggle_action(
                        remove_key, f"Remove {spec.label}", "remove", self._sam_model_remove_run(spec)))
                remove_btn.pack(side="left")
            else:
                install_btn = RoundedButton(
                    right, "Queued ✓" if queued_install else "Add to plan",
                    icon="check" if queued_install else "install", variant="secondary" if queued_install else "success",
                    width=150, command=lambda: self._wizard_toggle_action(
                        install_key, f"Download {spec.label}", "install", self._sam_model_install_run(spec)))
                install_btn.pack(side="left", padx=(0, 8))
                remove_btn = RoundedButton(right, "Remove", icon="trash", variant="danger", width=160)
                remove_btn.pack(side="left")
                remove_btn.set_enabled(False)
            row.finalize()

        def _wizard_queue_all_models(self, family: str):
            missing = [m for m in MODEL_REGISTRY if m.family == family and not model_installed(m)]
            if not missing:
                themed_info(self.root, "Nothing to do", f"All {family} models are already installed.")
                return
            for spec in missing:
                key = f"sam_model:{spec.key}:install"
                if not self.plan.has(key):
                    self.plan.add(PlannedAction(key, f"Download {spec.label}", "install",
                                                 self._sam_model_install_run(spec)))
            self._render_wizard_step()

        # -- SAM 3.1 (gated on Hugging Face) --

        def _wizard_render_sam3(self, parent):
            spec = MODEL_BY_KEY["sam3"]
            installed = model_installed(spec)
            card = RoundedCard(parent)
            card.pack(fill="x", pady=(0, 10))
            body = card.body

            top = tk.Frame(body, bg=CARD_BG)
            top.pack(fill="x")
            left = tk.Frame(top, bg=CARD_BG)
            left.pack(side="left", fill="x", expand=True)
            name_row = tk.Frame(left, bg=CARD_BG)
            name_row.pack(anchor="w")
            tk.Label(name_row, text=f"{spec.label} (SAM3)", bg=CARD_BG, fg=TEXT, font=("Sans", 12, "bold")).pack(
                side="left")
            tk.Label(name_row, text=f"   {spec.size}", bg=CARD_BG, fg=TEXT_MUTED, font=("Sans", 9)).pack(side="left")
            rating_widget(left, spec.quality, spec.speed, bg=CARD_BG).pack(anchor="w", pady=(4, 0))

            install_key, remove_key = "sam3:install", "sam3:remove"
            queued_install = self.plan.has(install_key)
            queued_remove = self.plan.has(remove_key)
            status = ("Installed" if installed else
                      "Queued for download" if queued_install else
                      "Queued for removal" if queued_remove else "")
            if status:
                tk.Label(left, text=status, bg=CARD_BG, fg=(DANGER if queued_remove else SUCCESS),
                         font=("Sans", 9, "bold")).pack(anchor="w", pady=(4, 0))

            autowrap_label(
                body, f"Gated on Hugging Face ({SAM3_HF_REPO_ID}) — request access, wait for approval, then "
                      "paste a READ token below. The token is only checked against the repo once the plan "
                      "actually runs, so queuing it now is free.",
                fg=TEXT_MUTED, bg=CARD_BG, font=("Sans", 9),
            ).pack(anchor="w", fill="x", pady=(12, 14))

            row1 = tk.Frame(body, bg=CARD_BG)
            row1.pack(fill="x", pady=(0, 10))
            RoundedButton(row1, "Request access on Hugging Face", icon="link", variant="secondary", width=270,
                          command=lambda: webbrowser.open(SAM3_HF_PAGE)).pack(side="left")
            transformers_key = "sam3:transformers"
            t_queued = self.plan.has(transformers_key)
            RoundedButton(
                row1, "Queued ✓" if t_queued else "Install/upgrade transformers",
                icon="check" if t_queued else "box", variant="secondary", width=230,
                command=lambda: self._wizard_toggle_action(
                    transformers_key, "Install/upgrade transformers", "install",
                    lambda job: install_sam3_transformers(job)),
            ).pack(side="left", padx=8)

            row2 = tk.Frame(body, bg=CARD_BG)
            row2.pack(fill="x")
            tk.Label(row2, text="HF token", bg=CARD_BG, fg=TEXT, font=("Sans", 10, "bold")).pack(side="left")
            hf_entry = ttk.Entry(row2, textvariable=self.hf_token_var, show="*", width=30, font=("Sans", 10))
            hf_entry.pack(side="left", padx=8, ipady=3)
            flatten_entry(hf_entry)

            if installed:
                done_btn = RoundedButton(row2, "Installed", icon="check", variant="secondary", width=140)
                done_btn.pack(side="left", padx=(0, 8))
                done_btn.set_enabled(False)
                remove_btn = RoundedButton(
                    row2, "Cancel removal" if queued_remove else "Remove",
                    icon="undo" if queued_remove else "trash", variant="secondary" if queued_remove else "danger",
                    width=130, command=lambda: self._wizard_toggle_action(remove_key, "Remove SAM 3.1", "remove",
                                                                           lambda job: remove_sam3(job)))
                remove_btn.pack(side="left")
            else:
                def token_ok():
                    return queued_install or bool(self.hf_token_var.get().strip())

                dl_btn = RoundedButton(
                    row2, "Queued ✓" if queued_install else "Add to plan",
                    icon="check" if queued_install else "install", variant="secondary" if queued_install else "success",
                    width=140,
                    command=lambda: self._wizard_toggle_action(
                        install_key, "Download SAM 3.1", "install",
                        lambda job: self._run_sam3_download(job)),
                    on_blocked=lambda: show_snackbar(self, "Enter a Hugging Face token first", tone="warn"),
                )
                dl_btn.pack(side="left", padx=(0, 8))
                dl_btn.set_enabled(token_ok())
                trace_id = self.hf_token_var.trace_add("write", lambda *_a: dl_btn.set_enabled(token_ok()))
                dl_btn.bind("<Destroy>", lambda _e, tid=trace_id: self.hf_token_var.trace_remove("write", tid))
                no_remove = RoundedButton(row2, "Remove", icon="trash", variant="danger", width=130)
                no_remove.pack(side="left")
                no_remove.set_enabled(False)
            card.finalize()

        def _run_sam3_download(self, job: Job):
            token = self.hf_token_var.get().strip()
            if not token:
                job.log("No Hugging Face token was entered — skipping SAM 3.1.")
                return
            ok, tag = download_sam3(job, token)
            if not ok:
                job.log(sam3_failure_message(tag))

        # -- Batcher -----------------------------------------------------

        def _wizard_render_batcher(self, parent):
            installed = batcher_installed()
            self._wizard_toggle_card(
                parent, key="batcher", installed=installed,
                status_text="Batch image processing / export layers"
                             + (" — installed" if installed else " — not installed"),
                install_label="Install Batcher",
                install_run=lambda job: install_batcher(job),
                uninstall_run=lambda job: remove_batcher(job),
            )

        # -- Review & install --------------------------------------------------

        def _wizard_render_review(self, parent):
            if len(self.plan) == 0:
                card = RoundedCard(parent)
                card.pack(fill="x")
                tk.Label(card.body, text="Nothing queued yet — go back and pick at least one action.",
                         bg=CARD_BG, fg=TEXT_MUTED, font=("Sans", 10)).pack(anchor="w")
                card.finalize()
                return
            for action in self.plan:
                row = RoundedCard(parent, pad=14, radius=14)
                row.pack(fill="x", pady=5)
                line = tk.Frame(row.body, bg=CARD_BG)
                line.pack(fill="x")
                icon_canvas(line, "trash" if action.kind == "remove" else "install",
                            color=DANGER if action.kind == "remove" else SUCCESS, size=16,
                            bg=CARD_BG).pack(side="left", padx=(0, 10))
                tk.Label(line, text=action.label, bg=CARD_BG, fg=TEXT, font=("Sans", 10, "bold")).pack(
                    side="left", fill="x", expand=True)
                RoundedButton(line, "✕", variant="secondary", width=36,
                              command=lambda k=action.key: self._wizard_discard_action(k)).pack(side="right")
                row.finalize()

            RoundedButton(parent, f"Proceed to installation ({len(self.plan)})", icon="bolt", variant="primary",
                          width=320, height=44, command=self._wizard_start_install).pack(anchor="w", pady=(14, 0))

        def _wizard_discard_action(self, key: str):
            self.plan.discard(key)
            self._render_wizard_step()

        def _wizard_start_install(self):
            self.show_install_progress(list(self.plan))

        # ---- shared install-progress screen ---------------------------------
        # Runs a list[PlannedAction] sequentially, in one background thread,
        # with a live progress bar and log — used by both the wizard's Review
        # page and Quick Setup's prefilled plan, so there is exactly one place
        # that actually executes anything.

        def show_install_progress(self, actions: list[PlannedAction]):
            self.plan_actions = list(actions)
            self.exec_total = len(self.plan_actions)
            self.exec_done = 0
            self.exec_cancelled = False
            self.exec_finished = False
            self._exec_log_lines = []
            self._render_install_progress()
            self._run_plan()

        def _exec_progress_text(self) -> str:
            if self.exec_total == 0:
                return "Nothing was queued."
            if self.exec_finished:
                if self.exec_cancelled:
                    return f"Stopped after {self.exec_done} of {self.exec_total} steps."
                return f"Finished {self.exec_done} of {self.exec_total} steps."
            return f"Step {min(self.exec_done + 1, self.exec_total)} of {self.exec_total}"

        def _render_install_progress(self):
            self.current_screen = "installing"
            for w in self.root_frame.winfo_children():
                w.destroy()

            content = tk.Frame(self.root_frame, bg=BG)
            content.pack(fill="both", expand=True, padx=32, pady=24)

            title = "Installation finished" if self.exec_finished else "Installing…"
            tk.Label(content, text=title, bg=BG, fg=TEXT, font=("Sans", 18, "bold")).pack(anchor="w")

            self.exec_step_lbl = tk.Label(content, text=self._exec_progress_text(), bg=BG, fg=TEXT_MUTED,
                                           font=("Sans", 10))
            self.exec_step_lbl.pack(anchor="w", pady=(4, 10))

            self.exec_progress_bar = ProgressBar(content, width=760, height=10)
            self.exec_progress_bar.pack(anchor="w", fill="x")
            self.exec_progress_bar.set_fraction(self.exec_done / self.exec_total if self.exec_total else 1.0)

            log_card = RoundedCard(content, pad=12)
            log_card.pack(fill="both", expand=True, pady=(16, 0))
            text_frame = tk.Frame(log_card.body, bg=CARD_BG)
            text_frame.pack(fill="both", expand=True)
            self.exec_log_text = tk.Text(text_frame, bg="#101114", fg=TEXT, insertbackground=TEXT, relief="flat",
                                          wrap="word", font=("Monospace", 9), height=16, state="disabled")
            sb = ttk.Scrollbar(text_frame, orient="vertical", command=self.exec_log_text.yview,
                                style="Modern.Vertical.TScrollbar")
            self.exec_log_text.configure(yscrollcommand=sb.set)
            self.exec_log_text.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            for line in self._exec_log_lines:
                self._append_exec_log(line)
            log_card.finalize()

            btn_row = tk.Frame(content, bg=BG)
            btn_row.pack(fill="x", pady=(16, 0))
            if self.exec_finished:
                RoundedButton(btn_row, "Done", variant="primary", width=140,
                              command=self.show_landing).pack(side="left")
            else:
                RoundedButton(btn_row, "Stop", icon="x", variant="danger", width=140,
                              command=self._stop_plan_execution).pack(side="left")

        def _append_exec_log(self, line: str):
            if not hasattr(self, "exec_log_text") or not self.exec_log_text.winfo_exists():
                return
            self.exec_log_text.configure(state="normal")
            self.exec_log_text.insert("end", line + "\n")
            self.exec_log_text.see("end")
            self.exec_log_text.configure(state="disabled")

        def _bump_exec_progress(self):
            if hasattr(self, "exec_step_lbl") and self.exec_step_lbl.winfo_exists():
                self.exec_step_lbl.configure(text=self._exec_progress_text())
            if hasattr(self, "exec_progress_bar") and self.exec_progress_bar.winfo_exists():
                self.exec_progress_bar.set_fraction(self.exec_done / self.exec_total if self.exec_total else 1.0)

        def _run_plan(self):
            actions = self.plan_actions

            def task(job: Job):
                for action in actions:
                    if job.cancel_event.is_set():
                        self.exec_cancelled = True
                        job.log(f"Stopped before: {action.label}")
                        break
                    job.log(f"→ {action.label}")
                    try:
                        action.run(job)
                    except Exception as e:
                        job.log(f"ERROR during {action.label}: {e}")
                    self.exec_done += 1
                    self.root.after(0, self._bump_exec_progress)
                if not actions:
                    job.log("Nothing was queued.")
                elif self.exec_cancelled:
                    job.log("Stopped — whatever finished so far was left in place.")
                else:
                    job.log("All done! Restart GIMP to see everything.")

            self.run_in_background(task, on_done=self._finish_plan)

        def _stop_plan_execution(self):
            self.cancel_current_job()

        def _finish_plan(self):
            self.exec_finished = True
            self._render_install_progress()


def launch_gui():
    if not _TK_OK:
        print("[fail] Tkinter is not available in this Python — install python3-tk (or the equivalent "
              "package for your distro) to use the graphical installer, or use the CLI: "
              "python3 lazygimp.py --help", file=sys.stderr)
        sys.exit(1)
    root = tk.Tk()
    LazyGimpApp(root)
    try:
        root.mainloop()
    finally:
        _self_destruct_if_ephemeral()


# ---------------------------------------------------------------------------
# Command-line interface — every action the GUI can do is also a plain CLI
# command, for headless boxes and scripting. Root actions (package-manager
# installs/removals) run with a real controlling terminal here, so sudo just
# prompts normally — no pty tricks needed outside the GUI.
# ---------------------------------------------------------------------------

def _cli_job() -> Job:
    return Job(log_queue=None, password_prompt=None)


def cmd_status(_args) -> int:
    job = _cli_job()
    distro = detect_distro()
    print(f"Distribution family : {distro or '(unsupported/unknown)'}")
    print(f"GIMP (native pkg)   : {'installed' if gimp_native_installed() else 'not installed'}")
    print(f"GIMP (AppImage)     : {'installed' if appimage_present() else 'not installed'}")
    print(f"GIMP on PATH        : {find_gimp_binary() or '(none)'}")
    print(f"PhotoGIMP           : {'installed' if photogimp_installed() else 'not installed'}")
    print(f"G'MIC               : {'installed' if gmic_installed() else 'not installed'}"
          + ("" if gmic_available_on_this_release() else "  (no package on this release)"))
    print(f"SAM plug-in         : {'installed' if segany_plugin_installed() else 'not installed'}")
    print(f"SAM Python backend  : {'ready' if backend_ready() else ('venv exists but broken' if venv_exists() else 'not installed')}")
    installed_models = [m.key for m in MODEL_REGISTRY if model_installed(m)]
    print(f"SAM models          : {', '.join(installed_models) if installed_models else '(none)'}")
    print(f"Batcher             : {'installed' if batcher_installed() else 'not installed'}")
    del job
    return 0


def cmd_install(args) -> int:
    job = _cli_job()
    ok = True
    for comp in args.components:
        if comp == "gimp":
            method = args.method or ("package-manager" if detect_distro() else "appimage")
            ok &= bool(install_gimp_package_manager(job, include_gmic=False) if method == "package-manager"
                       else install_gimp_appimage(job))
        elif comp == "photogimp":
            cmd = find_gimp_command()
            ok &= install_photogimp(job, gimp_command=(cmd[0] if cmd else None))
        elif comp == "gmic":
            ok &= install_gmic_only(job)
        elif comp == "sam":
            ok &= install_segany_plugin(job)
            hw = detect_hardware()
            ok &= install_sam_backend(job, recommended_torch_index(hw))
            if not any_model_installed():
                rec = MODEL_BY_KEY[recommended_model_key(hw)]
                if job.download(rec.url, model_path(rec), job.cancel_event):
                    write_segany_plugin_settings(rec)
                    write_sam_info([rec.key])
        elif comp == "batcher":
            ok &= install_batcher(job)
        else:
            print(f"unknown component: {comp}", file=sys.stderr)
            ok = False
    return 0 if ok else 1


def cmd_remove(args) -> int:
    job = _cli_job()
    for comp in args.components:
        if comp == "gimp":
            remove_gimp_package_manager(job)
            remove_gimp_appimage(job)
        elif comp == "photogimp":
            remove_photogimp(job)
        elif comp == "gmic":
            remove_gmic_only(job)
        elif comp == "sam":
            remove_segany_plugin(job)
            remove_sam_backend(job)
        elif comp == "batcher":
            remove_batcher(job)
        else:
            print(f"unknown component: {comp}", file=sys.stderr)
            return 1
    return 0


def cmd_sam_list(_args) -> int:
    hw = detect_hardware()
    rec = recommended_model_key(hw)
    print(f"Recommended for this hardware: {rec}\n")
    for m in MODEL_REGISTRY:
        mark = "*" if m.key == rec else " "
        state = "installed" if model_installed(m) else "-"
        print(f" {mark} {m.key:22s} {m.family:5s} {m.size:8s} quality={m.quality} speed={m.speed}  [{state}]")
    return 0


def cmd_sam_install(args) -> int:
    job = _cli_job()
    ok = True
    for key in args.keys:
        spec = MODEL_BY_KEY.get(key)
        if not spec:
            print(f"unknown SAM model: {key}", file=sys.stderr)
            ok = False
            continue
        if model_installed(spec):
            print(f"{key} already installed")
            continue
        if spec.family == "SAM3":
            print("Use 'sam3 download --token ...' for SAM 3.1 (it's gated).", file=sys.stderr)
            ok = False
            continue
        if job.download(spec.url, model_path(spec), job.cancel_event):
            write_segany_plugin_settings(spec)
            write_sam_info([spec.key])
        else:
            ok = False
    return 0 if ok else 1


def cmd_sam_remove(args) -> int:
    job = _cli_job()
    for key in args.keys:
        spec = MODEL_BY_KEY.get(key)
        if not spec:
            print(f"unknown SAM model: {key}", file=sys.stderr)
            continue
        dest = model_path(spec)
        if os.path.isdir(dest):
            shutil.rmtree(dest)
            job.log(f"Removed {dest}")
        elif os.path.isfile(dest):
            os.remove(dest)
            job.log(f"Removed {dest}")
        else:
            job.log(f"{key} was not installed")
    return 0


def cmd_sam3_download(args) -> int:
    job = _cli_job()
    ok, tag = download_sam3(job, args.token)
    if not ok:
        print(sam3_failure_message(tag), file=sys.stderr)
    return 0 if ok else 1


def cmd_sam3_remove(_args) -> int:
    job = _cli_job()
    remove_sam3(job)
    return 0


def cmd_fix_desktop(_args) -> int:
    job = _cli_job()
    return 0 if repair_desktop_integration(job) else 1


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lazygimp.py",
        description="GIMP + PhotoGIMP + G'MIC + SAM + Batcher — one standalone installer. "
                     "No subcommand opens the GUI.",
    )
    p.add_argument("--ephemeral", action="store_true", help="self-delete this file when the GUI closes")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("status", help="show what's installed").set_defaults(func=cmd_status)

    p_install = sub.add_parser("install", help="install one or more components")
    p_install.add_argument("components", nargs="+", choices=["gimp", "photogimp", "gmic", "sam", "batcher"])
    p_install.add_argument("--method", choices=["package-manager", "appimage"], default=None,
                            help="GIMP install method (default: auto-detected)")
    p_install.set_defaults(func=cmd_install)

    p_remove = sub.add_parser("remove", help="remove one or more components")
    p_remove.add_argument("components", nargs="+", choices=["gimp", "photogimp", "gmic", "sam", "batcher"])
    p_remove.set_defaults(func=cmd_remove)

    p_sam = sub.add_parser("sam", help="manage individual SAM models")
    sam_sub = p_sam.add_subparsers(dest="sam_command", required=True)
    sam_sub.add_parser("list", help="list every SAM model and its install state").set_defaults(func=cmd_sam_list)
    p_sam_install = sam_sub.add_parser("install", help="download one or more SAM models")
    p_sam_install.add_argument("keys", nargs="+")
    p_sam_install.set_defaults(func=cmd_sam_install)
    p_sam_remove = sam_sub.add_parser("remove", help="delete one or more SAM models")
    p_sam_remove.add_argument("keys", nargs="+")
    p_sam_remove.set_defaults(func=cmd_sam_remove)

    p_sam3 = sub.add_parser("sam3", help="SAM 3.1 (gated on Hugging Face)")
    sam3_sub = p_sam3.add_subparsers(dest="sam3_command", required=True)
    p_sam3_dl = sam3_sub.add_parser("download", help="check access and download the SAM 3.1 checkpoint")
    p_sam3_dl.add_argument("--token", required=True, help="Hugging Face read token")
    p_sam3_dl.set_defaults(func=cmd_sam3_download)
    sam3_sub.add_parser("remove", help="delete the SAM 3.1 checkpoint").set_defaults(func=cmd_sam3_remove)

    sub.add_parser("fix-desktop", help="repair the PhotoGIMP taskbar/window-icon desktop entry "
                                        "without reinstalling").set_defaults(func=cmd_fix_desktop)

    return p


def _self_destruct_if_ephemeral():
    ephemeral = "--ephemeral" in sys.argv or os.environ.get("LAZYGIMP_INSTALLER_EPHEMERAL") == "1"
    if not ephemeral:
        return
    try:
        path = os.path.abspath(__file__)
        if os.path.isfile(path):
            os.remove(path)
    except (NameError, OSError):
        pass


def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    if getattr(args, "command", None) is None:
        launch_gui()
        return
    rc = args.func(args)
    _self_destruct_if_ephemeral()
    sys.exit(rc)


if __name__ == "__main__":
    main()
