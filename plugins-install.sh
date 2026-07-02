#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# plugins-install.sh — GIMP 3 plug-ins, on top of any LazyGimp installation
# (native packages, flatpak or AppImage):
#
#   batcher            batch processing / export layers  (BSD-3-Clause)
#   segment-anything   AI subject selection via Meta SAM (AGPL-3.0),
#                      including a fully automated Python backend
#
# Usage:
#   ./plugins-install.sh                     both, ready to use (default)
#   ./plugins-install.sh --batcher           install Batcher only
#   ./plugins-install.sh --segment-anything  install Segment Anything only
#   ./plugins-install.sh --uninstall-all     remove everything we installed
#   ./plugins-install.sh --kind flatpak ...  target the flatpak GIMP explicitly
# ---------------------------------------------------------------------------

# Tolerate being launched with `sh script.sh` (dash, or bash in POSIX mode,
# which rejects function names containing '::'): re-exec under real bash.
if [ -f "${0:-}" ]; then
  if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
  if shopt -qo posix 2>/dev/null; then exec bash "$0" "$@"; fi
fi

set -euo pipefail

LAZYGIMP_REPO_SLUG="${LAZYGIMP_REPO_SLUG:-pierspad/LazyGimp}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd)"

# Standalone download or `curl | bash`: fetch the release bundle and re-exec.
if [[ ! -d "${SCRIPT_DIR}/lib" ]]; then
  bootstrap_dir="$(mktemp -d "${TMPDIR:-/tmp}/lazygimp-bootstrap.XXXXXX")"
  trap 'rm -rf "$bootstrap_dir"' EXIT
  echo "[info] fetching the latest LazyGimp bundle..." >&2
  curl -fsSL "https://github.com/${LAZYGIMP_REPO_SLUG}/releases/latest/download/lazygimp.tar.gz" |
    tar -xz -C "$bootstrap_dir"
  exec bash "${bootstrap_dir}/lazygimp/plugins-install.sh" "$@"
fi

# shellcheck source=lib/segany_backend.sh
source "${SCRIPT_DIR}/lib/segany_backend.sh"

usage() {
  cat <<EOF
LazyGimp — plug-ins installer

Usage: ${0##*/} [options]

Options:
  --batcher            install Batcher (batch processing / export layers)
  --segment-anything   install Segment Anything, INCLUDING its Python backend
                       (PyTorch CPU + SAM checkpoint, ~1 GB download) — the
                       result is fully working out of the box
  --no-sam-backend     with --segment-anything: install the plug-in only,
                       e.g. if you already manage your own PyTorch/SAM setup
  --kind <k>           target GIMP install kind: native | flatpak
                       (default: auto-detected)
  --uninstall-all      remove every plug-in installed by LazyGimp
                       (and the SAM backend, if present)
  -h, --help           show this help

Without options BOTH plug-ins are installed, ready to use.
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
  # No selection → everything, ready to use. Lazy by default.
  if ((!WANT_BATCHER && !WANT_SEGANY)); then
    WANT_BATCHER=1
    WANT_SEGANY=1
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
