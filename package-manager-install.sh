#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# package-manager-install.sh — GIMP + G'MIC from the *native* package
# manager (so the system keeps GIMP updated), then everything else:
# headless first launch, PhotoGIMP layer, Batcher, Segment Anything.
# Fully unattended: no questions asked.
#
# The script only detects the distribution and dispatches to the matching
# shell_scripts/<distro>.sh; every distro-specific decision lives there.
#
# Usage:
#   ./package-manager-install.sh [--skip-photogimp] [--skip-plugins] [--no-sam]
#
# Piped usage (no checkout needed):
#   curl -fsSL https://raw.githubusercontent.com/pierspad/LazyGimp/main/package-manager-install.sh | bash
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
  exec bash "${bootstrap_dir}/lazygimp/package-manager-install.sh" "$@"
fi

# shellcheck source=lib/photogimp.sh
source "${SCRIPT_DIR}/lib/photogimp.sh"

usage() {
  cat <<EOF
LazyGimp — native package manager installer (fully unattended)

Usage: ${0##*/} [options]

Options:
  --skip-photogimp        do not apply the PhotoGIMP configuration layer
  --skip-plugins          do not install the plug-ins (Batcher, SAM)
  --no-sam                install Batcher but skip Segment Anything (~1 GB)
  --skip-gmic             do not install the G'MIC plug-in package
  --uninstall-photogimp   remove the PhotoGIMP layer (personal files are kept)
  -h, --help              show this help

By default EVERYTHING is set up, no questions asked: GIMP + G'MIC +
PhotoGIMP + Batcher + Segment Anything (with its automated Python backend).

Supported distribution families: $(find "${SCRIPT_DIR}/shell_scripts" -name '*.sh' -printf '%f ' | sed 's/\.sh//g')
EOF
}

SKIP_PHOTOGIMP="${LAZYGIMP_SKIP_PHOTOGIMP:-0}"
SKIP_PLUGINS="${LAZYGIMP_SKIP_PLUGINS:-0}"
NO_SAM="${LAZYGIMP_NO_SAM:-0}"
export LAZYGIMP_SKIP_GMIC="${LAZYGIMP_SKIP_GMIC:-0}"
while (($#)); do
  case "$1" in
    --skip-photogimp) SKIP_PHOTOGIMP=1 ;;
    --skip-plugins) SKIP_PLUGINS=1 ;;
    --no-sam) NO_SAM=1 ;;
    --skip-gmic) export LAZYGIMP_SKIP_GMIC=1 ;;
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

  # GIMP must run once to generate its config tree before we layer on it.
  gimp::warm_up native

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
    if ! "${SCRIPT_DIR}/plugins-install.sh" "${plugin_args[@]}"; then
      log::warn "plug-ins step failed — re-run it later with: ./plugins-install.sh"
    fi
  fi

  log::ok "all done — launch GIMP and enjoy"
}

main
