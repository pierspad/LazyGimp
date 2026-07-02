#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# install_with_package_manager.sh — install GIMP + G'MIC from the *native*
# package manager (so the system keeps GIMP updated), then apply the
# PhotoGIMP configuration layer.
#
# The script only detects the distribution and dispatches to the matching
# shell_scripts/<distro>.sh; every distro-specific decision lives there.
#
# Usage:
#   ./install_with_package_manager.sh [--skip-photogimp] [--uninstall-photogimp]
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
# shellcheck source=lib/photogimp.sh
source "${SCRIPT_DIR}/lib/photogimp.sh"

usage() {
  cat <<EOF
LazyGimp — native package manager installer

Usage: ${0##*/} [options]

Options:
  --skip-photogimp        do not apply the PhotoGIMP configuration layer
  --skip-plugins          do not install the optional plug-ins (Batcher, SAM)
  --no-sam                install Batcher but skip Segment Anything (~1 GB)
  --uninstall-photogimp   remove the PhotoGIMP layer (personal files are kept)
  -h, --help              show this help

By default EVERYTHING is set up: GIMP + G'MIC + PhotoGIMP + Batcher +
Segment Anything with its automated Python backend.

Supported distribution families: $(find "${SCRIPT_DIR}/shell_scripts" -name '*.sh' -printf '%f ' | sed 's/\.sh//g')
EOF
}

SKIP_PHOTOGIMP="${LAZYGIMP_SKIP_PHOTOGIMP:-0}"
SKIP_PLUGINS="${LAZYGIMP_SKIP_PLUGINS:-0}"
NO_SAM="${LAZYGIMP_NO_SAM:-0}"
while (($#)); do
  case "$1" in
    --skip-photogimp) SKIP_PHOTOGIMP=1 ;;
    --skip-plugins) SKIP_PLUGINS=1 ;;
    --no-sam) NO_SAM=1 ;;
    --uninstall-photogimp)
      photogimp::uninstall native
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
  if [[ ${EUID} -eq 0 ]]; then
    die "run as a regular user — sudo is invoked only where needed, and the \
PhotoGIMP layer must land in *your* home, not root's"
  fi

  local distro
  distro="$(lazygimp::detect_distro)" ||
    die "unsupported distribution — add shell_scripts/<id>.sh for it (see docs/ARCHITECTURE.md)"
  log::info "detected distribution family: ${distro}"

  # shellcheck source=/dev/null
  source "${SCRIPT_DIR}/shell_scripts/${distro}.sh"
  declare -F lazygimp::install_packages >/dev/null ||
    die "shell_scripts/${distro}.sh does not define lazygimp::install_packages"

  lazygimp::install_packages
  if declare -F lazygimp::post_install_notes >/dev/null; then
    lazygimp::post_install_notes
  fi

  if [[ "$SKIP_PHOTOGIMP" != 1 ]]; then
    # Run in a subshell so a refusal (e.g. distro ships GIMP 2.x) degrades
    # to a warning instead of aborting after packages were installed.
    if ! (photogimp::install native); then
      log::warn "PhotoGIMP layer not applied (see message above); GIMP itself is installed"
    fi
  fi

  if [[ "$SKIP_PLUGINS" != 1 ]]; then
    local plugin_args=(--kind native --batcher)
    if [[ "$NO_SAM" != 1 ]]; then
      plugin_args+=(--segment-anything)
    fi
    if ! "${SCRIPT_DIR}/install_plugins.sh" "${plugin_args[@]}"; then
      log::warn "plug-ins step failed — re-run it later with: ./install_plugins.sh"
    fi
  fi

  log::ok "all done — launch GIMP and enjoy"
}

main
