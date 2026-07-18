from __future__ import annotations

from .constants import APPIMAGE_DIR, XDG_CONFIG_HOME, ensure_state_dir
from .job import Job
from typing import Optional
import glob
import os
import re
import shutil
import subprocess

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
