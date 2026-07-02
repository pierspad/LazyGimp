#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# install_plugins.sh — optional GIMP 3 plug-ins, on top of any LazyGimp
# installation (native packages, flatpak or AppImage):
#
#   batcher            batch processing / export layers  (BSD-3-Clause)
#   segment-anything   AI subject selection via Meta SAM (AGPL-3.0) —
#                      EXPERIMENTAL: needs a separate Python backend
#                      (PyTorch + model checkpoints, several GB)
#
# Usage:
#   ./install_plugins.sh                     interactive menu
#   ./install_plugins.sh --batcher           install Batcher
#   ./install_plugins.sh --segment-anything  install Segment Anything
#   ./install_plugins.sh --uninstall-all     remove every plug-in we installed
#   ./install_plugins.sh --kind flatpak ...  target the flatpak GIMP explicitly
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
# shellcheck source=lib/segany_backend.sh
source "${SCRIPT_DIR}/lib/segany_backend.sh"

usage() {
  cat <<EOF
LazyGimp — optional plug-ins installer

Usage: ${0##*/} [options]

Options:
  --batcher            install Batcher (batch processing / export layers)
  --segment-anything   install Segment Anything, INCLUDING its Python backend
                       (PyTorch CPU + SAM checkpoint, ~1 GB download) — the
                       result is fully working out of the box
  --no-sam-backend     with --segment-anything: install the plug-in only,
                       manage the Python backend yourself
  --kind <k>           target GIMP install kind: native | flatpak
                       (default: auto-detected)
  --uninstall-all      remove every plug-in installed by LazyGimp
                       (and the SAM backend, if present)
  -h, --help           show this help

Run without options for an interactive menu.
GPU acceleration: LAZYGIMP_TORCH_INDEX_URL=<torch wheel index> (default: CPU wheels).
EOF
}

# Which GIMP should receive the plug-ins? Prefer whichever GIMP is actually
# detectable, native first; fail with guidance when neither is.
detect_kind() {
  if gimp::detect_version native >/dev/null 2>&1; then
    printf 'native\n'
  elif gimp::detect_version flatpak >/dev/null 2>&1; then
    printf 'flatpak\n'
  elif gimp::newest_config_dir "$(gimp::config_base native)" >/dev/null 2>&1; then
    printf 'native\n'
  elif gimp::newest_config_dir "$(gimp::config_base flatpak)" >/dev/null 2>&1; then
    printf 'flatpak\n'
  else
    return 1
  fi
}

choose_interactively() {
  local tty=/dev/tty choice
  [[ -r "$tty" && -w "$tty" ]] || return 1
  {
    printf '\nLazyGimp — optional plug-ins\n\n'
    printf '  1) both               everything, ready to use (default)\n'
    printf '  2) batcher            batch processing / export layers\n'
    printf '  3) segment-anything   AI subject selection, incl. automated\n'
    printf '                        PyTorch/SAM backend (~1 GB download)\n'
    printf '  q) quit\n\n'
  } >"$tty"
  while true; do
    printf 'Choice [1]: ' >"$tty"
    read -r choice <"$tty" || return 1
    case "$choice" in
      '' | 1)
        WANT_BATCHER=1
        WANT_SEGANY=1
        ;;
      2) WANT_BATCHER=1 ;;
      3) WANT_SEGANY=1 ;;
      q | quit) exit 0 ;;
      *)
        printf 'invalid choice: %s\n' "$choice" >"$tty"
        continue
        ;;
    esac
    return 0
  done
}

KIND=""
WANT_BATCHER=0
WANT_SEGANY=0
SAM_BACKEND=1
while (($#)); do
  case "$1" in
    --batcher) WANT_BATCHER=1 ;;
    --segment-anything | --segany) WANT_SEGANY=1 ;;
    --no-sam-backend) SAM_BACKEND=0 ;;
    --kind)
      KIND="${2:?--kind requires a value}"
      shift
      ;;
    --kind=*) KIND="${1#*=}" ;;
    --uninstall-all)
      plugins::uninstall_all
      segany::remove_backend
      exit 0
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
  shift
done

main() {
  if ((!WANT_BATCHER && !WANT_SEGANY)); then
    choose_interactively ||
      die "no terminal for the interactive menu — pass --batcher and/or --segment-anything"
  fi

  if [[ -z "$KIND" ]]; then
    KIND="$(detect_kind)" ||
      die "no GIMP installation detected — install GIMP first (./install.sh), or pass --kind"
  fi
  log::info "target GIMP install kind: ${KIND}"

  if ((WANT_BATCHER)); then
    plugins::install_batcher "$KIND"
  fi
  if ((WANT_SEGANY)); then
    plugins::install_segany "$KIND"
    if ((SAM_BACKEND)); then
      segany::install_backend "$KIND"
    else
      log::warn "SAM backend skipped (--no-sam-backend) — the plug-in needs one to run:"
      log::warn "see https://github.com/${SEGANY_REPO}#readme"
    fi
  fi

  log::ok "done — restart GIMP to load the new plug-ins"
}

main
