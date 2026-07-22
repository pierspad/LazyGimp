from __future__ import annotations

from .constants import DESKTOP_FILES_MANIFEST, PHOTOGIMP_BRANCH, PHOTOGIMP_EXCLUDE, PHOTOGIMP_MANIFEST, PHOTOGIMP_RELEASE_TAG, PHOTOGIMP_REPO, STATE_DIR, XDG_DATA_HOME, ensure_state_dir
from .gimp_detect import _version_key, find_gimp_binary, gimp_config_dir, gimp_live_config_dir, gimp_version_dirs
from .job import Job
from .util import fetch_github_repo_info, fetch_latest_github_release_assets, github_branch_archive_url
from typing import Optional
import glob
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile

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


def _gimp_is_running() -> bool:
    """True if a GIMP process (native or AppImage) is currently alive.

    GIMP rewrites toolrc/sessionrc/gimprc back to disk on exit to persist
    whatever tool order/dock layout it currently has in memory. If we lay
    PhotoGIMP's files down while an existing GIMP instance is still open,
    that instance's later, unrelated exit will silently overwrite them
    with its own (stock) state — the assets (splash, icons, .desktop)
    survive because GIMP never touches those, but toolrc/gimprc quietly
    revert, which looks exactly like "PhotoGIMP didn't apply"."""
    try:
        res = subprocess.run(["ps", "-eo", "pid,comm,args"], capture_output=True, text=True, timeout=5)
        if res.returncode != 0:
            return False
        mypid = os.getpid()
        for line in res.stdout.splitlines()[1:]:
            parts = line.strip().split(None, 2)
            if len(parts) < 3:
                continue
            pid_str, comm, args = parts[0], parts[1], parts[2]
            try:
                pid = int(pid_str)
            except ValueError:
                continue
            if pid == mypid:
                continue
            args_lower = args.lower()
            if "lazygimp" in args_lower or "pytest" in args_lower:
                continue
            comm_lower = comm.lower()
            if "gimp" in comm_lower or "gimp" in args_lower:
                if re.search(r"\bgimp(?:-\d+\.\d+)?(?:\.bin|\.appimage)?\b", args_lower) or "org.gimp.gimp" in args_lower:
                    return True
        return False
    except Exception:
        return False


def _photogimp_download_and_extract(job: Job) -> Optional[str]:
    tmp = tempfile.mkdtemp(prefix="lazygimp-photogimp-")
    zip_path = os.path.join(tmp, "photogimp.zip")

    # Prefer the repo's default-branch HEAD over a tagged release: PhotoGIMP
    # ships tool-layout fixes as plain commits well before cutting a new
    # release (verified directly — master was one commit ahead of the "3.1"
    # tag, with real toolrc content differences: an extra tool group and
    # reordered groups the tagged release didn't have yet).
    repo_info = fetch_github_repo_info(PHOTOGIMP_REPO)
    branch = (repo_info or {}).get("default_branch") or PHOTOGIMP_BRANCH
    branch_url = github_branch_archive_url(PHOTOGIMP_REPO, branch)
    job.log(f"Fetching PhotoGIMP from the latest commit on '{branch}': {branch_url}")
    if job.download(branch_url, zip_path):
        extracted = os.path.join(tmp, "extracted")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extracted)
        return extracted

    job.log("Could not fetch the latest commit — falling back to the latest tagged release.")
    release_info = fetch_latest_github_release_assets(PHOTOGIMP_REPO)
    download_url = None
    if release_info:
        assets = release_info.get("assets", [])
        for asset in assets:
            if asset.get("name") == "PhotoGIMP-linux.zip":
                download_url = asset.get("browser_download_url")
                break
        if not download_url:
            for asset in assets:
                if asset.get("name") == "PhotoGIMP.zip":
                    download_url = asset.get("browser_download_url")
                    break
        if download_url:
            job.log(f"Resolved latest PhotoGIMP release download URL from GitHub: {download_url}")

    if not download_url:
        job.log(f"Falling back to pinned PhotoGIMP release tag: {PHOTOGIMP_RELEASE_TAG}")
        base_url = f"https://github.com/{PHOTOGIMP_REPO}/releases/download/{PHOTOGIMP_RELEASE_TAG}"
        download_url = f"{base_url}/PhotoGIMP-linux.zip"

    if not job.download(download_url, zip_path):
        if not release_info:  # if we fell back, try the second asset
            fallback_url = f"https://github.com/{PHOTOGIMP_REPO}/releases/download/{PHOTOGIMP_RELEASE_TAG}/PhotoGIMP.zip"
            if not job.download(fallback_url, zip_path):
                return None
        else:
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
    if _gimp_is_running():
        job.log("ERROR: GIMP is currently running — close it first. GIMP saves its own "
                 "toolrc/sessionrc/gimprc to disk when it exits, which would silently "
                 "undo PhotoGIMP's layout right after this step finishes.")
        return False
    primary_target = gimp_config_dir(version_hint)
    if not primary_target:
        job.log("ERROR: cannot locate a GIMP config directory — launch GIMP once, then retry.")
        return False

    targets = [primary_target]
    for d in gimp_version_dirs():
        if d not in targets:
            targets.append(d)

    job.log(f"GIMP config directory: {primary_target} (applying across profiles: {', '.join([os.path.basename(t) for t in targets])})")
    extracted = _photogimp_download_and_extract(job)
    if not extracted:
        return False
    payload = _photogimp_locate_payload(extracted)
    if not payload:
        job.log("ERROR: no GIMP payload (.config/GIMP/X.Y) found in the PhotoGIMP archive.")
        return False

    total_files = 0
    for target in targets:
        profile_name = os.path.basename(target)
        backup = _photogimp_backup(target)
        if backup:
            job.log(f"Existing configuration backed up to {backup}")

        count = _photogimp_apply(payload, target, job)
        total_files += count
        job.log(f"PhotoGIMP layer installed ({count} files) into profile '{profile_name}'")

    _photogimp_install_desktop_files(extracted, gimp_command, job)
    shutil.rmtree(os.path.dirname(extracted), ignore_errors=True)
    job.log(f"PhotoGIMP layer installation complete ({total_files} total files copied across profiles)")
    return True


def remove_photogimp(job: Job) -> bool:
    if _gimp_is_running():
        job.log("ERROR: GIMP is currently running — close it first, otherwise its exit "
                 "will rewrite toolrc/sessionrc/gimprc and interfere with the removal.")
        return False
    found = False
    for target in gimp_version_dirs():
        manifest_path = os.path.join(target, PHOTOGIMP_MANIFEST)
        if not os.path.isfile(manifest_path):
            continue
        found = True
        job.log(f"Removing PhotoGIMP layer from {target}")
        with open(manifest_path, encoding="utf-8") as fh:
            rels = [ln.strip() for ln in fh if ln.strip()]
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
