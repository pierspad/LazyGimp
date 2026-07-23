from __future__ import annotations

from .constants import FLATPAK_CONFIG_DIR, FLATPAK_GIMP_ID, XDG_CONFIG_HOME, ensure_state_dir
from .job import Job
from typing import Optional
import os
import re
import shutil
import subprocess

# ---------------------------------------------------------------------------
# GIMP detection — install kind, version, per-user config dir. Nothing here
# hardcodes a GIMP version: the config directory (3.0, 3.2, ...) is always
# resolved at runtime.
# ---------------------------------------------------------------------------

import sys

def find_gimp_binary() -> Optional[str]:
    found = (shutil.which("gimp") or shutil.which("gimp-3.0") or shutil.which("gimp-2.10") or
             shutil.which("gimp.exe") or shutil.which("gimp-3.0.exe"))
    if found:
        return found
    if sys.platform == "win32":
        for pf in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if not pf:
                continue
            for sub in (os.path.join("GIMP 3", "bin", "gimp-3.0.exe"),
                        os.path.join("GIMP 3", "bin", "gimp.exe"),
                        os.path.join("GIMP 2", "bin", "gimp-2.10.exe"),
                        os.path.join("GIMP 2", "bin", "gimp.exe")):
                candidate = os.path.join(pf, sub)
                if os.path.isfile(candidate):
                    return candidate
    return None


def flatpak_gimp_installed() -> bool:
    if not shutil.which("flatpak"):
        return False
    res = subprocess.run(["flatpak", "info", FLATPAK_GIMP_ID], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return res.returncode == 0


def find_gimp_command() -> Optional[list[str]]:
    """The command to *launch* GIMP with — native binary on PATH, or Flatpak."""
    bin_ = find_gimp_binary()
    if bin_:
        return [bin_]
    if flatpak_gimp_installed():
        return ["flatpak", "run", FLATPAK_GIMP_ID]
    return None


def gimp_version_string() -> Optional[str]:
    cmd = find_gimp_command()
    if not cmd:
        return None
    try:
        out = subprocess.run(cmd + ["--version"], capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    m = re.search(r"(\d+)\.(\d+)(?:\.\d+)?", out.stdout or "")
    return f"{m.group(1)}.{m.group(2)}" if m else None


def gimp_config_base(target: Optional[str] = None) -> str:
    native_base = os.path.join(XDG_CONFIG_HOME, "GIMP")
    if target == "flatpak":
        return FLATPAK_CONFIG_DIR
    if target == "pm":
        return native_base
    if os.path.isdir(FLATPAK_CONFIG_DIR) and not os.path.isdir(native_base):
        return FLATPAK_CONFIG_DIR
    if flatpak_gimp_installed() and not find_gimp_binary():
        return FLATPAK_CONFIG_DIR
    return native_base


def _version_key(name: str):
    try:
        return tuple(int(p) for p in name.split("."))
    except ValueError:
        return (0,)


def gimp_version_dirs(target: Optional[str] = None) -> list[str]:
    dirs = []
    bases = [gimp_config_base(target)] if target else [gimp_config_base(), FLATPAK_CONFIG_DIR, os.path.join(XDG_CONFIG_HOME, "GIMP")]
    for base in bases:
        if os.path.isdir(base):
            names = [n for n in os.listdir(base) if re.fullmatch(r"\d+\.\d+", n) and os.path.isdir(os.path.join(base, n))]
            names.sort(key=_version_key)
            for n in names:
                d = os.path.join(base, n)
                if d not in dirs:
                    dirs.append(d)
    return dirs


def gimp_live_config_dir(target: Optional[str] = None) -> Optional[str]:
    """The config dir GIMP actually reads, proven by a live `pluginrc` —
    more reliable than trusting `gimp --version`, whose reported MAJOR.MINOR
    is not guaranteed to equal the profile directory name GIMP actually
    uses."""
    for d in reversed(gimp_version_dirs(target)):
        if os.path.isfile(os.path.join(d, "pluginrc")):
            return d
    return None


def gimp_config_dir(version_hint: Optional[str] = None, target: Optional[str] = None) -> Optional[str]:
    base = gimp_config_base(target)
    if version_hint:
        m = re.search(r"(\d+)\.(\d+)", version_hint)
        if m:
            return os.path.join(base, f"{m.group(1)}.{m.group(2)}")
    ver = gimp_version_string()
    if ver:
        return os.path.join(base, ver)
    dirs = gimp_version_dirs(target)
    if dirs:
        return dirs[-1]
    live = gimp_live_config_dir(target)
    if live:
        return live
    return os.path.join(base, "3.0")


def gimp_plugins_dir(version_hint: Optional[str] = None, target: Optional[str] = None) -> Optional[str]:
    cfg = gimp_config_dir(version_hint, target)
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
    """Launch GIMP once — with a real GUI startup, not just the console/
    batch engine — so it generates its FULL per-user config tree: menus,
    tool options, pluginrc, AND toolrc/sessionrc. Must happen before
    PhotoGIMP/plug-ins are applied on a fresh install, otherwise GIMP's own
    first-run setup can still run *after* PhotoGIMP has laid its files down
    and silently mangle them.

    Deliberately NOT run with --no-interface: toolrc/sessionrc are owned by
    GIMP's toolbox/session UI layer, which never initializes in pure
    console mode. A console-only warm-up leaves those two files missing
    entirely — so whatever GIMP the user opens for real afterwards becomes
    the *true* first run for them, and GIMP reconciles PhotoGIMP's freshly
    copied toolrc against its own tool registry on that first load/save
    cycle, which is what was silently reordering/dropping tool groups from
    the toolbox layout. `-b "(gimp-quit 0)"` still closes GIMP itself the
    moment startup finishes, so this is at most a brief flash on screen,
    not something the user has to close by hand.

    Guarded on pluginrc AND toolrc both existing (not just "any version
    directory exists", and not just pluginrc alone — a profile warmed up by
    an older, --no-interface-only build of this warm-up would have
    pluginrc but no toolrc, which used to make this a permanent no-op on
    every retry for anyone who'd already run it once)."""
    live = gimp_live_config_dir()
    if live and (os.path.isfile(os.path.join(live, "pluginrc")) or os.path.isfile(os.path.join(live, "gimprc"))):
        return
    cmd = gimp_cmd or find_gimp_binary()
    if not cmd:
        return
    warmup_log = os.path.join(ensure_state_dir(), "warmup.log")
    job.log("First GIMP start — initializing configuration headlessly in background...")
    timeout = int(os.environ.get("LAZYGIMP_WARMUP_TIMEOUT", "120"))
    rc = None
    try:
        with open(warmup_log, "wb") as lf:
            rc = subprocess.run(
                [cmd, "-d", "-f", "-i", "-s",
                 "--batch-interpreter=plug-in-script-fu-eval",
                 "-b", "(gimp-quit 0)"],
                stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT,
                timeout=timeout,
            ).returncode
    except subprocess.TimeoutExpired:
        job.log(f"GIMP warm-up did not finish within {timeout}s (log: {warmup_log}); continuing anyway")
    except Exception as e:
        job.log(f"GIMP warm-up did not finish cleanly ({e}); continuing anyway")

    live = gimp_live_config_dir()
    if live:
        job.log("GIMP configuration initialized")
    else:
        job.log(
            f"GIMP warm-up did not produce a usable profile (exit code {rc}; "
            f"see {warmup_log} for details). PhotoGIMP will still be applied, "
            "but if things look off afterwards, launch GIMP once from its "
            "menu entry, close it, then re-run PhotoGIMP install/repair."
        )
        ver = gimp_version_string()
        if ver:
            os.makedirs(os.path.join(gimp_config_base(), ver), exist_ok=True)
            job.log(f"created {gimp_config_base()}/{ver} (GIMP will adopt it on first launch)")
