#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# install.sh — LazyGimp: one command to a fully configured GIMP
#              (latest stable GIMP + PhotoGIMP + G'MIC).
#
# Usage:
#   ./install.sh [--method auto|flatpak|package-manager|appimage] [options]
#
# Piped usage (no checkout needed):
#   curl -fsSL https://raw.githubusercontent.com/pierspad/LazyGimp/main/install.sh | bash
# ---------------------------------------------------------------------------
set -euo pipefail

LAZYGIMP_VERSION="0.0.0-dev" # replaced by the release pipeline
LAZYGIMP_REPO_SLUG="${LAZYGIMP_REPO_SLUG:-pierspad/LazyGimp}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd)"

# When run via `curl | bash` there is no repository on disk: download the
# latest release bundle and re-exec from there.
if [[ ! -d "${SCRIPT_DIR}/lib" ]]; then
  bootstrap_dir="$(mktemp -d "${TMPDIR:-/tmp}/lazygimp-bootstrap.XXXXXX")"
  trap 'rm -rf "$bootstrap_dir"' EXIT
  echo "[info] fetching the latest LazyGimp bundle..." >&2
  curl -fsSL "https://github.com/${LAZYGIMP_REPO_SLUG}/releases/latest/download/lazygimp.tar.gz" |
    tar -xz -C "$bootstrap_dir"
  exec bash "${bootstrap_dir}/lazygimp/install.sh" "$@"
fi

# shellcheck source=lib/methods/flatpak.sh
source "${SCRIPT_DIR}/lib/methods/flatpak.sh"
# shellcheck source=lib/methods/appimage.sh
source "${SCRIPT_DIR}/lib/methods/appimage.sh"

usage() {
  cat <<EOF
LazyGimp v${LAZYGIMP_VERSION} — GIMP + PhotoGIMP + G'MIC, ready to use.

Usage: ${0##*/} [options]

Options:
  -m, --method <m>        auto (default) | flatpak | package-manager | appimage
      --skip-photogimp    do not apply the PhotoGIMP configuration layer
      --uninstall-photogimp [kind]
                          remove the PhotoGIMP layer (kind: native|flatpak, default native)
  -h, --help              show this help

Methods:
  flatpak          GIMP + G'MIC from Flathub, auto-updated  (recommended)
  package-manager  native distro packages, updated by your system
  appimage         official gimp.org AppImage, single portable file
EOF
}

METHOD=auto
while (($#)); do
  case "$1" in
    -m | --method)
      METHOD="${2:?--method requires a value}"
      shift
      ;;
    --method=*) METHOD="${1#*=}" ;;
    --skip-photogimp) export LAZYGIMP_SKIP_PHOTOGIMP=1 ;;
    --uninstall-photogimp)
      photogimp::uninstall "${2:-native}"
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

# Pick the best method for this machine: flatpak when available (current
# GIMP everywhere + automatic updates), then native packages, then the
# official AppImage as the universal fallback.
choose_method() {
  if [[ "$METHOD" != auto ]]; then
    printf '%s\n' "$METHOD"
    return 0
  fi
  if have flatpak; then
    printf 'flatpak\n'
  elif lazygimp::detect_distro >/dev/null 2>&1; then
    printf 'package-manager\n'
  else
    printf 'appimage\n'
  fi
}

main() {
  local method
  method="$(choose_method)"
  log::info "LazyGimp v${LAZYGIMP_VERSION} — installation method: ${method}"

  case "$method" in
    flatpak) method_flatpak::install ;;
    appimage) method_appimage::install ;;
    package-manager | pm)
      local args=()
      if [[ "${LAZYGIMP_SKIP_PHOTOGIMP:-0}" == 1 ]]; then
        args+=(--skip-photogimp)
      fi
      exec "${SCRIPT_DIR}/install_with_package_manager.sh" "${args[@]}"
      ;;
    *) die "unknown method: ${method} (see --help)" ;;
  esac
}

main
