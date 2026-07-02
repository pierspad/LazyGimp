#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# uninstall.sh — remove everything LazyGimp installed, so you can start
# clean (e.g. to reinstall with a different method).
#
# It detects which installations are actually present (native packages,
# flatpak, AppImage, PhotoGIMP layers) and removes only what you confirm.
# Personal GIMP files (brushes, scripts, plug-ins, settings not shipped by
# PhotoGIMP) are never touched; pre-install backups are kept unless --purge.
#
# Usage:
#   ./uninstall.sh                      interactive: detect, list, confirm
#   ./uninstall.sh --method <m> [...]   non-interactive removal of one or
#                                       more of: package-manager|flatpak|
#                                       appimage|photogimp
#   ./uninstall.sh --all --yes          remove everything detected, no prompt
#   ./uninstall.sh --purge              also delete backups and state dir
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
  exec bash "${bootstrap_dir}/lazygimp/uninstall.sh" "$@"
fi
# shellcheck source=lib/photogimp.sh
source "${SCRIPT_DIR}/lib/photogimp.sh"
# shellcheck source=lib/segany_backend.sh
source "${SCRIPT_DIR}/lib/segany_backend.sh"

usage() {
  cat <<EOF
LazyGimp — uninstaller

Usage: ${0##*/} [options]

Options:
  --method <m>   remove a specific installation; repeatable
                 (package-manager | flatpak | appimage | photogimp | plugins)
  --all          remove every installation detected
  --purge        also delete LazyGimp backups/state and flatpak app data
  --yes          do not ask for confirmation
  -h, --help     show this help

Run without options for an interactive, detect-and-confirm flow.
EOF
}

# ------------------------------- detection --------------------------------
detected_flatpak() { have flatpak && flatpak info "${GIMP_FLATPAK_ID}" >/dev/null 2>&1; }

detected_appimage() {
  local dir="${LAZYGIMP_APPIMAGE_DIR:-${HOME}/Applications}"
  compgen -G "${dir}/GIMP-*.AppImage" >/dev/null 2>&1
}

detected_package_manager() {
  lazygimp::detect_distro >/dev/null 2>&1 || return 1
  have gimp
}

detected_photogimp() {
  local kind base dir
  for kind in native flatpak; do
    base="$(gimp::config_base "$kind")"
    for dir in "$base"/*/; do
      [[ -f "${dir}${PHOTOGIMP_MANIFEST}" ]] && return 0
    done
  done
  return 1
}

detected_plugins() {
  [[ -s "$(plugins::state_file)" || -d "$(segany::backend_dir)" ]]
}

# -------------------------------- removal ---------------------------------

# Revert font-access overrides exactly as recorded by flatpak-install.sh.
revert_font_overrides() {
  local state="${LAZYGIMP_STATE_DIR}/flatpak-font-overrides" fs
  [[ -f "$state" ]] || return 0
  while IFS= read -r fs; do
    if [[ -n "$fs" ]]; then
      flatpak override --user --nofilesystem="${fs%%:*}" "${GIMP_FLATPAK_ID}" 2>/dev/null || true
    fi
  done <"$state"
  rm -f -- "$state"
  log::info "font-access sandbox overrides reverted"
}

remove_flatpak() {
  log::info "removing ${GIMP_FLATPAK_ID} (flatpak)"
  revert_font_overrides
  flatpak uninstall -y "${GMIC_FLATPAK_ID}" 2>/dev/null || true
  flatpak uninstall -y "${GIMP_FLATPAK_ID}"
  if ((PURGE)); then
    rm -rf "${HOME}/.var/app/${GIMP_FLATPAK_ID}"
    log::info "flatpak app data purged"
  fi
  log::ok "flatpak installation removed"
}

remove_appimage() {
  local dir="${LAZYGIMP_APPIMAGE_DIR:-${HOME}/Applications}" file
  for file in "${dir}"/GIMP-*.AppImage "${dir}/GIMP.AppImage"; do
    [[ -e "$file" || -L "$file" ]] && rm -f -- "$file" && log::info "removed ${file}"
  done
  log::ok "AppImage installation removed"
}

remove_package_manager() {
  local distro
  distro="$(lazygimp::detect_distro)" ||
    die "unsupported distribution — remove the packages with your package manager"
  # shellcheck source=/dev/null
  source "${SCRIPT_DIR}/shell_scripts/${distro}.sh"
  declare -F lazygimp::remove_packages >/dev/null ||
    die "shell_scripts/${distro}.sh does not define lazygimp::remove_packages"
  lazygimp::remove_packages
  log::ok "native packages removed"
}

# Remove every PhotoGIMP layer found (any version dir, native and flatpak).
remove_photogimp() {
  local kind base dir found=0
  for kind in native flatpak; do
    base="$(gimp::config_base "$kind")"
    for dir in "$base"/*/; do
      if [[ -f "${dir}${PHOTOGIMP_MANIFEST}" ]]; then
        log::info "removing PhotoGIMP layer from ${dir}"
        photogimp::remove "${dir%/}"
        found=1
      fi
    done
  done
  photogimp::remove_desktop_files
  if ((found)); then
    log::ok "PhotoGIMP layer removed; personal files were left untouched"
  else
    log::info "no PhotoGIMP layer found"
  fi
}

purge_state() {
  rm -rf "${LAZYGIMP_STATE_DIR}"
  log::ok "LazyGimp state and backups purged (${LAZYGIMP_STATE_DIR})"
}

# --------------------------------- flow -----------------------------------
confirm() { # <question> — honours --yes; needs a tty otherwise
  ((ASSUME_YES)) && return 0
  local tty=/dev/tty answer
  [[ -r "$tty" && -w "$tty" ]] || die "no terminal for confirmation — re-run with --yes"
  printf '%s [y/N]: ' "$1" >"$tty"
  read -r answer <"$tty" || return 1
  [[ "$answer" == y || "$answer" == Y || "$answer" == yes ]]
}

ASSUME_YES=0
PURGE=0
ALL=0
TARGETS=()
while (($#)); do
  case "$1" in
    --method)
      TARGETS+=("${2:?--method requires a value}")
      shift
      ;;
    --method=*) TARGETS+=("${1#*=}") ;;
    --all) ALL=1 ;;
    --purge) PURGE=1 ;;
    --yes | -y) ASSUME_YES=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
  shift
done

main() {
  # Build the target list: explicit --method wins, then --all / interactive
  # detection.
  if ((${#TARGETS[@]} == 0)); then
    local detected=()
    detected_package_manager && detected+=(package-manager)
    detected_flatpak && detected+=(flatpak)
    detected_appimage && detected+=(appimage)
    detected_photogimp && detected+=(photogimp)
    detected_plugins && detected+=(plugins)

    if ((${#detected[@]} == 0)); then
      log::info "nothing installed by LazyGimp was detected"
      exit 0
    fi

    log::info "detected: ${detected[*]}"
    if ((!ALL)); then
      confirm "remove ALL of the above?" || {
        log::info "aborted — use --method <m> to remove selectively"
        exit 0
      }
    fi
    TARGETS=("${detected[@]}")
  fi

  # PhotoGIMP layers and plug-ins must go before the GIMP that owns their
  # config dir is removed, otherwise config-base detection loses its anchor.
  local t
  for t in photogimp plugins package-manager flatpak appimage; do
    local wanted=0 x
    for x in "${TARGETS[@]}"; do
      [[ "$x" == "$t" || "$x" == pm && "$t" == package-manager ]] && wanted=1
    done
    ((wanted)) || continue
    case "$t" in
      photogimp) remove_photogimp ;;
      plugins)
        plugins::uninstall_all
        segany::remove_backend
        ;;
      package-manager) confirm "remove GIMP and G'MIC native packages?" && remove_package_manager ;;
      flatpak) confirm "remove the GIMP flatpak?" && remove_flatpak ;;
      appimage) confirm "remove the GIMP AppImage?" && remove_appimage ;;
    esac
  done

  if ((PURGE)); then
    purge_state
  else
    log::info "backups kept in ${LAZYGIMP_STATE_DIR}/backups (delete with --purge)"
  fi

  log::ok "done — you can now reinstall with a different method (./install.sh)"
}

main
