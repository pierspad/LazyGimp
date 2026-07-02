#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# install.sh — LazyGimp orchestrator.
#
# This script installs NOTHING by itself: it only helps you pick a method
# and dispatches to the matching standalone installer, which you can also
# run directly:
#
#   install_with_package_manager.sh   native distro packages   (default)
#   install_with_flatpak.sh           Flathub + G'MIC extension
#   install_with_appimage.sh          official gimp.org AppImage
#
# Without --method an interactive menu is shown (it works for `curl | bash`
# too, via /dev/tty). Nothing is ever downloaded before you have chosen.
#
# Usage:
#   ./install.sh [--method package-manager|flatpak|appimage|auto] [--skip-photogimp]
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

# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

readonly METHODS=(package-manager flatpak appimage)

usage() {
  cat <<EOF
LazyGimp v${LAZYGIMP_VERSION} — GIMP + PhotoGIMP + G'MIC, ready to use.

Usage: ${0##*/} [options]

Options:
  -m, --method <m>      package-manager | flatpak | appimage | auto
                        (no flag → interactive menu; 'auto' → first available)
      --skip-photogimp  do not apply the PhotoGIMP configuration layer
  -h, --help            show this help

Methods (each is also a standalone script you can run directly):
  package-manager  native distro packages, updated by your system   [default]
                   → ./install_with_package_manager.sh
  flatpak          Flathub GIMP + G'MIC extension, auto-updated —
                   best on Debian stable / Ubuntu LTS, whose repos lag
                   → ./install_with_flatpak.sh
  appimage         official gimp.org AppImage, single portable file
                   → ./install_with_appimage.sh

To remove everything (and optionally reinstall with another method):
  ./uninstall.sh
EOF
}

method_available() { # <method>
  case "$1" in
    package-manager) lazygimp::detect_distro >/dev/null 2>&1 ;;
    flatpak) have flatpak ;;
    appimage) [[ "$(uname -s)" == Linux ]] ;;
    *) return 1 ;;
  esac
}

method_hint() { # <method> — one-line description for the menu
  case "$1" in
    package-manager) printf 'native distro packages, updated by your system' ;;
    flatpak) printf "Flathub GIMP + G'MIC extension, auto-updated" ;;
    appimage) printf 'official gimp.org AppImage, single portable file' ;;
  esac
}

recommended_method() {
  local m
  for m in "${METHODS[@]}"; do
    if method_available "$m"; then
      printf '%s\n' "$m"
      return 0
    fi
  done
  return 1
}

# Interactive menu on /dev/tty, so it also works when the script itself is
# piped into bash. Fails (return 1) when no terminal is attached.
choose_interactively() {
  local tty=/dev/tty
  [[ -r "$tty" && -w "$tty" ]] || return 1

  local default idx=0 m mark avail choice
  default="$(recommended_method)" || return 1

  {
    printf '\nLazyGimp v%s — how do you want to install GIMP?\n\n' "${LAZYGIMP_VERSION}"
    for m in "${METHODS[@]}"; do
      idx=$((idx + 1))
      mark=' '
      avail=''
      [[ "$m" == "$default" ]] && mark='*'
      method_available "$m" || avail='   [NOT available on this system]'
      printf ' %s %d) %-16s %s%s\n' "$mark" "$idx" "$m" "$(method_hint "$m")" "$avail"
    done
    printf '\nNothing is downloaded before you confirm. * = recommended here.\n'
  } >"$tty"

  while true; do
    printf 'Choice [%s]: ' "$default" >"$tty"
    read -r choice <"$tty" || return 1
    case "$choice" in
      '') METHOD="$default" ;;
      1) METHOD=package-manager ;;
      2) METHOD=flatpak ;;
      3) METHOD=appimage ;;
      package-manager | pm | flatpak | appimage) METHOD="${choice/pm/package-manager}" ;;
      q | quit) exit 0 ;;
      *)
        printf 'invalid choice: %s (1-3, a method name, or q to quit)\n' "$choice" >"$tty"
        continue
        ;;
    esac
    return 0
  done
}

METHOD=""
while (($#)); do
  case "$1" in
    -m | --method)
      METHOD="${2:?--method requires a value}"
      shift
      ;;
    --method=*) METHOD="${1#*=}" ;;
    --skip-photogimp) export LAZYGIMP_SKIP_PHOTOGIMP=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
  shift
done

main() {
  if [[ "$METHOD" == pm ]]; then
    METHOD=package-manager
  fi

  if [[ -z "$METHOD" ]]; then
    choose_interactively ||
      die "no terminal available for the interactive menu — pass --method explicitly (see --help)"
  elif [[ "$METHOD" == auto ]]; then
    METHOD="$(recommended_method)" || die "no installation method is available on this system"
    log::info "auto-selected method: ${METHOD}"
  fi

  if ! method_available "$METHOD"; then
    case "$METHOD" in
      flatpak) die "flatpak is not installed — install it first, or pick another method" ;;
      package-manager) die "unsupported distribution — pick another method, or add shell_scripts/<id>.sh" ;;
      *) die "method '${METHOD}' is not available on this system (see --help)" ;;
    esac
  fi

  case "$METHOD" in
    package-manager) exec "${SCRIPT_DIR}/install_with_package_manager.sh" ;;
    flatpak) exec "${SCRIPT_DIR}/install_with_flatpak.sh" ;;
    appimage) exec "${SCRIPT_DIR}/install_with_appimage.sh" ;;
    *) die "unknown method: ${METHOD} (see --help)" ;;
  esac
}

main
