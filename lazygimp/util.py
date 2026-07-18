from __future__ import annotations

from typing import Optional
import json
import os
import re
import shutil
import sys
import urllib.request

def clean_output_line(line: str) -> str:
    """Strip ANSI escape sequences (colors, cursor movements) and resolve
    carriage returns (keeping only the final overwritten text)."""
    # Regex matching ANSI escape sequences
    ansi_escape = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    line = ansi_escape.sub('', line)
    if '\r' in line:
        parts = line.split('\r')
        non_empty = [p for p in parts if p.strip()]
        if non_empty:
            line = non_empty[-1]
        else:
            line = parts[-1]
    return line


def fetch_latest_github_release_assets(repo: str) -> Optional[dict]:
    """Fetch the latest release payload from GitHub for a given repository."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": "LazyGimp-Installer"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _install_artifact_paths() -> list[str]:
    """Paths that make up this installation, for --ephemeral self-destruction.

    Depending on how LazyGimp was launched this is:
      * the PyInstaller binary   (frozen single-file build)
      * the zipapp archive       (lazygimp.pyz)
      * the source checkout      (lazygimp/ package + lazygimp.py launcher)
    """
    if getattr(sys, "frozen", False):  # PyInstaller
        return [sys.executable]
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isdir(pkg_dir):
        # Running from inside an archive (zipapp): walk up to the archive file.
        probe = pkg_dir
        while probe and not os.path.isfile(probe):
            probe = os.path.dirname(probe)
        return [probe] if probe else []
    paths = [pkg_dir]
    launcher = os.path.join(os.path.dirname(pkg_dir), "lazygimp.py")
    if os.path.isfile(launcher):
        paths.append(launcher)
    return paths


def _self_destruct_if_ephemeral() -> None:
    ephemeral = "--ephemeral" in sys.argv or os.environ.get("LAZYGIMP_INSTALLER_EPHEMERAL") == "1"
    if not ephemeral:
        return
    for path in _install_artifact_paths():
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.isfile(path):
                os.remove(path)
            pycache = os.path.join(os.path.dirname(path), "__pycache__")
            if os.path.isdir(pycache):
                shutil.rmtree(pycache, ignore_errors=True)
        except OSError:
            pass
