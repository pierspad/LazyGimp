from __future__ import annotations

from typing import Optional
import json
import os
import re
import shutil
import ssl
import sys
import urllib.request


def clean_subprocess_env() -> dict:
    """An environment safe to hand to an EXTERNAL program (pacman, flatpak,
    gimp, ps, ...).

    PyInstaller's onefile bootloader points LD_LIBRARY_PATH at its own
    extraction dir (_MEIxxxxx) so the frozen Python interpreter finds ITS
    bundled .so files, stashing whatever LD_LIBRARY_PATH originally held (if
    anything) in LD_LIBRARY_PATH_ORIG first. That same variable, inherited by
    every subprocess we spawn, makes system tools load OUR bundled
    libssl.so.3/libcrypto.so.3/etc instead of their own — surfacing as
    version-mismatch crashes (flatpak/pacman refusing to run) or, quieter and
    worse, a detection command exiting nonzero so LazyGimp wrongly concludes
    something isn't installed. A source checkout / the zipapp never set
    LD_LIBRARY_PATH_ORIG in the first place, so this is a no-op there.
    """
    env = os.environ.copy()
    orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if orig is not None:
        env["LD_LIBRARY_PATH"] = orig
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env


# Same underlying cause as clean_subprocess_env(), different symptom: the
# frozen binary's own Python links against a bundled OpenSSL whose
# compiled-in default certificate path is wherever the CI build image kept
# its CA bundle, not wherever *this* host keeps its own — so
# ssl.create_default_context()'s implicit set_default_verify_paths() finds
# nothing and every HTTPS request fails with CERTIFICATE_VERIFY_FAILED, even
# though the host has perfectly valid CA certificates sitting right there.
# Only relevant when frozen; a source checkout already uses the system
# Python's own (correctly configured) OpenSSL.
_SYSTEM_CA_BUNDLE_CANDIDATES = (
    "/etc/ssl/certs/ca-certificates.crt",   # Debian, Ubuntu, Arch, Gentoo
    "/etc/pki/tls/certs/ca-bundle.crt",     # Fedora, RHEL, CentOS
    "/etc/ssl/ca-bundle.pem",               # openSUSE
    "/etc/ssl/cert.pem",                    # Alpine, macOS
)

_ssl_context_cache: Optional[ssl.SSLContext] = None


def download_ssl_context() -> Optional[ssl.SSLContext]:
    """SSLContext for urlopen() calls, pinned at the host's own CA bundle
    when frozen. Returns None outside a frozen build, which tells callers to
    just use urllib's normal default behaviour."""
    global _ssl_context_cache
    if not getattr(sys, "frozen", False):
        return None
    if _ssl_context_cache is not None:
        return _ssl_context_cache
    for candidate in _SYSTEM_CA_BUNDLE_CANDIDATES:
        if os.path.isfile(candidate):
            try:
                ctx = ssl.create_default_context(cafile=candidate)
            except ssl.SSLError:
                continue
            _ssl_context_cache = ctx
            return ctx
    return None


def urlopen(req, **kwargs):
    """urllib.request.urlopen with the host-pinned SSLContext applied when
    running frozen. A thin wrapper instead of a module-level default so every
    call site (here and in job.py) stays a one-line change."""
    kwargs.setdefault("context", download_ssl_context())
    return urllib.request.urlopen(req, **kwargs)


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
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def fetch_github_repo_info(repo: str) -> Optional[dict]:
    """Fetch repository metadata (default_branch, etc.) from GitHub."""
    url = f"https://api.github.com/repos/{repo}"
    req = urllib.request.Request(url, headers={"User-Agent": "LazyGimp-Installer"})
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def github_branch_archive_url(repo: str, branch: str) -> str:
    """Codeload zip of a branch's HEAD — not release-gated, always the
    latest commit, and not subject to the api.github.com rate limit."""
    return f"https://github.com/{repo}/archive/refs/heads/{branch}.zip"


def _install_artifact_paths() -> list[str]:
    """Paths that make up this installation, for --ephemeral self-destruction.

    Depending on how LazyGimp was launched this is:
      * the PyInstaller binary   (frozen single-file build)
      * the zipapp archive       (lazygimp.pyz)
      * the source checkout      (lazygimp/ package + installer.py launcher)
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
    for name in ("installer.py", "lazygimp.py"):  # current + historic launcher
        launcher = os.path.join(os.path.dirname(pkg_dir), name)
        if os.path.isfile(launcher):
            paths.append(launcher)
    return paths


def _self_destruct_if_ephemeral() -> None:
    # If running inside a git source repository checkout, do not self-destruct!
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(pkg_dir)
    if os.path.isdir(os.path.join(root_dir, ".git")):
        return

    # The env var is authoritative when set (the GUI's "delete this
    # installer" checkbox writes it, so un-ticking beats --ephemeral);
    # otherwise the CLI flag decides.
    env = os.environ.get("LAZYGIMP_INSTALLER_EPHEMERAL")
    ephemeral = (env == "1") if env is not None else ("--ephemeral" in sys.argv)
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
