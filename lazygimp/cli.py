from __future__ import annotations

from .distro import detect_distro
from .gimp_detect import find_gimp_binary, find_gimp_command
from .gimp_install import appimage_present, gimp_native_installed, gmic_available_on_this_release, gmic_installed, install_gimp_appimage, install_gimp_package_manager, install_gmic_only, remove_gimp_appimage, remove_gimp_package_manager, remove_gmic_only
from .gui import launch_gui
from .gui_qt import launch_gui_qt
from .hardware import detect_hardware, recommended_model_key, recommended_torch_index
from .job import Job
from .models import MODEL_BY_KEY, MODEL_REGISTRY, any_model_installed, model_installed, model_path
from .photogimp import install_photogimp, photogimp_installed, remove_photogimp, repair_desktop_integration
from .plugins import batcher_installed, install_batcher, install_segany_plugin, remove_batcher, remove_segany_plugin, segany_plugin_installed, write_segany_plugin_settings
from .sam3 import download_sam3, remove_sam3, sam3_failure_message
from .sam_backend import backend_ready, install_sam_backend, remove_sam_backend, venv_exists, write_sam_info
from .util import _self_destruct_if_ephemeral
import argparse
import os
import shutil
import sys

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
        prog="installer.py",
        description="GIMP + PhotoGIMP + G'MIC + SAM + Batcher — one standalone installer. "
                     "No subcommand opens the GUI.",
    )
    p.add_argument("--ephemeral", action="store_true", help="self-delete this file when the GUI closes")
    # --qt / LAZYGIMP_GUI=qt: opt in to the PySide6 GUI (lazygimp/gui_qt/),
    # which is being staged alongside the CustomTkinter GUI (lazygimp/gui/,
    # still the default) so a human can A/B the two before either is
    # dropped. The env var exists for launchers that can't easily pass an
    # extra CLI flag (e.g. a desktop shortcut); either one being set is
    # enough to select Qt — see main() below.
    p.add_argument("--qt", action="store_true",
                    help="launch the PySide6 GUI instead of the default CustomTkinter one "
                         "(same effect as LAZYGIMP_GUI=qt)")
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


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    if getattr(args, "command", None) is None:
        use_qt = bool(getattr(args, "qt", False)) or os.environ.get("LAZYGIMP_GUI", "").strip().lower() == "qt"
        if use_qt:
            launch_gui_qt()
        else:
            launch_gui()
        return
    rc = args.func(args)
    _self_destruct_if_ephemeral()
    sys.exit(rc)
